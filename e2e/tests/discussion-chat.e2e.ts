/**
 * issue #107 端到端：玩家讨论区与主持人对话分流。
 *
 * 覆盖：讨论区广播 / 重发去重 / 玩家原话广播（修"聊天记录像被隔离"的 bug）/
 * 行动锁占用时他人提交入队 / 退房清空聊天 / 复盘纯净。
 *
 * 锁窗口不再需要人为延迟钩子：下面用 `action.broadcast` 到达（证明提交已被
 * 受理、锁已被持有）作为后续玩家入队的时机。
 */
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { dirname, resolve } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { type ServerToClientEvent } from 'trpg-sdk'

import { createRoomWithModule, legalCharacterPayload, registerPlayer } from './helpers.ts'

const LEGAL_ATTRIBUTES = {
  STR: 50, CON: 50, POW: 50, DEX: 50,
  APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
}
const EXPLICIT_KEEPER = { kind: 'keeper', entityId: null, explicit: true } as const
const DB_FILE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../trpg-backend/e2e.db'
)

function waitForEvent(
  socketOwner: { roomSocket: { onMessage: (h: (e: ServerToClientEvent) => void) => () => void } },
  predicate: (event: ServerToClientEvent) => boolean,
  timeoutMs = 5_000
): Promise<ServerToClientEvent> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      off()
      reject(new Error(`等待事件超时（${timeoutMs}ms）`))
    }, timeoutMs)
    const off = socketOwner.roomSocket.onMessage((event) => {
      if (!predicate(event)) return
      clearTimeout(timer)
      off()
      resolve(event)
    })
  })
}

/** 连接 + room.join + 等 session.bound 的完整绑定流程。 */
async function bindSocket(
  sdk: Awaited<ReturnType<typeof registerPlayer>>['sdk'],
  roomId: string,
  token: string,
  playerId: string,
  reconnectToken: string
): Promise<void> {
  const socket = sdk.roomSocket.connect(roomId, token)
  await sdk.roomSocket.waitForOpen(socket)
  const bound = waitForEvent(sdk, (e) => e.type === 'session.bound')
  sdk.roomSocket.joinRoom(playerId, { reconnectToken })
  await bound
}

async function buildCharacter(
  sdk: Awaited<ReturnType<typeof registerPlayer>>['sdk'],
  roomId: string,
  reconnectToken: string
): Promise<void> {
  const draft = await sdk.characters.createDraft(roomId, reconnectToken)
  await sdk.characters.save(
    roomId,
    draft.characterId,
    legalCharacterPayload(LEGAL_ATTRIBUTES),
    reconnectToken
  )
  await sdk.characters.complete(roomId, draft.characterId, reconnectToken)
}

test('🔴 讨论区消息广播给房间所有人（issue #107 端到端）', async () => {
  const room = await createRoomWithModule('chatbc', 2)
  const guest = await registerPlayer('chatbcguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '话痨访客' }, guest.token)

  try {
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )
    await bindSocket(guest.sdk, room.roomId, guest.token, joined.playerId, joined.reconnectToken)

    // 访客在讨论区发言，**房主**这一侧应该收到 chat.message 广播
    const hostHears = waitForEvent(
      room.host.sdk,
      (e) => e.type === 'chat.message' && e.payload.text === '我们先去图书馆吧'
    )
    guest.sdk.roomSocket.sendChat(joined.playerId, {
      text: '我们先去图书馆吧',
      clientMessageId: randomUUID(),
    })
    const heard = await hostHears
    assert.equal(heard.type, 'chat.message')
    if (heard.type === 'chat.message') {
      assert.equal(heard.payload.nickname, '话痨访客')
      assert.equal(heard.payload.playerId, joined.playerId)
    }
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})

test('🔴 重发相同 clientMessageId 不产生重复记录（重连去重）', async () => {
  const room = await createRoomWithModule('chatdup')

  try {
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )

    const clientMessageId = randomUUID()
    const first = waitForEvent(room.host.sdk, (e) => e.type === 'chat.message')
    room.host.sdk.roomSocket.sendChat(room.hostPlayerId, {
      text: '重发的同一条消息', clientMessageId,
    })
    const firstEvent = await first

    const second = waitForEvent(room.host.sdk, (e) => e.type === 'chat.message')
    room.host.sdk.roomSocket.sendChat(room.hostPlayerId, {
      text: '重发的同一条消息', clientMessageId,
    })
    const secondEvent = await second

    // 两次广播是同一条消息（同 messageId），历史里只有一行
    if (firstEvent.type === 'chat.message' && secondEvent.type === 'chat.message') {
      assert.equal(firstEvent.payload.messageId, secondEvent.payload.messageId)
    }
    const history = await room.host.sdk.rooms.listMessages(room.roomId, room.reconnectToken)
    assert.equal(history.length, 1)
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})

test('多人 roleplay 不调用主持，也不写入权威事件、记忆或摘要', async () => {
  const room = await createRoomWithModule('roleplay', 2)
  const guest = await registerPlayer('roleplayguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '扮演访客' }, guest.token)
  const roleplayId = `roleplay-${randomUUID()}`
  const roleplayText = `伊莱亚斯敲了两下桌面-${randomUUID()}`

  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken)

  try {
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )
    await bindSocket(guest.sdk, room.roomId, guest.token, joined.playerId, joined.reconnectToken)

    const hostOpening = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    const guestOpening = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([hostOpening, guestOpening])

    const observedTypes: string[] = []
    const off = guest.sdk.roomSocket.onMessage((event) => observedTypes.push(event.type))
    const hostHearsRoleplay = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'chat.message' && event.payload.text === roleplayText,
    )
    guest.sdk.roomSocket.sendActionChat(joined.playerId, {
      text: roleplayText,
      clientMessageId: roleplayId,
    })
    const roleplay = await hostHearsRoleplay
    assert.equal(roleplay.type, 'chat.message')
    if (roleplay.type === 'chat.message') {
      assert.equal(roleplay.payload.channel, 'roleplay')
      assert.ok(roleplay.payload.actorId)
      assert.equal(roleplay.payload.actorName, 'E2E 调查员')
    }

    // 用后一条讨论消息作为屏障：收到它时，前一条 roleplay 的服务端处理已完整结束。
    const barrierText = `处理屏障-${randomUUID()}`
    const barrier = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'chat.message' && event.payload.text === barrierText,
    )
    guest.sdk.roomSocket.sendChat(joined.playerId, {
      text: barrierText,
      clientMessageId: randomUUID(),
    })
    await barrier
    off()
    assert.equal(observedTypes.includes('turn.started'), false)
    assert.equal(observedTypes.includes('narration.push'), false)

    const conversation = await room.host.sdk.rooms.listConversation(
      room.roomId,
      room.reconnectToken,
    )
    assert.equal(
      conversation.some(
        (event) =>
          event.type === 'chat.message' &&
          event.payload.channel === 'roleplay' &&
          event.payload.text === roleplayText,
      ),
      true,
    )

    const db = new DatabaseSync(DB_FILE, { readOnly: true })
    try {
      const marker = `%${roleplayText}%`
      const traces = [
        [
          'events',
          'SELECT COUNT(*) AS count FROM events WHERE room_id = ? AND (correlation_id = ? OR CAST(payload AS TEXT) LIKE ?)',
          [room.roomId, roleplayId, marker],
        ],
        [
          'game_events',
          'SELECT COUNT(*) AS count FROM game_events WHERE room_id = ? AND (client_action_id = ? OR CAST(payload AS TEXT) LIKE ?)',
          [room.roomId, roleplayId, marker],
        ],
        [
          'action_executions',
          'SELECT COUNT(*) AS count FROM action_executions WHERE room_id = ? AND request_id = ?',
          [room.roomId, roleplayId],
        ],
        [
          'action_plan_runs',
          'SELECT COUNT(*) AS count FROM action_plan_runs WHERE room_id = ? AND parent_action_id = ?',
          [room.roomId, roleplayId],
        ],
        [
          'host_action_queue',
          'SELECT COUNT(*) AS count FROM host_action_queue WHERE room_id = ? AND client_action_id = ?',
          [room.roomId, roleplayId],
        ],
        [
          'memory_entries',
          'SELECT COUNT(*) AS count FROM memory_entries WHERE room_id = ? AND content LIKE ?',
          [room.roomId, marker],
        ],
        [
          'conversation_summaries',
          'SELECT COUNT(*) AS count FROM conversation_summaries WHERE room_id = ? AND CAST(summary_json AS TEXT) LIKE ?',
          [room.roomId, marker],
        ],
      ] as const
      for (const [table, sql, parameters] of traces) {
        const row = db.prepare(sql).get(...parameters) as { count: number }
        assert.equal(row.count, 0, `${table} 不应留下 roleplay 痕迹`)
      }
    } finally {
      db.close()
    }
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})

test('🔴 所有人都能看到发起者的原话 + 守秘人回复（修"聊天像被隔离"bug）', async () => {
  const room = await createRoomWithModule('actbc', 2)
  const guest = await registerPlayer('actbcguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '围观访客' }, guest.token)

  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken)

  try {
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )
    await bindSocket(guest.sdk, room.roomId, guest.token, joined.playerId, joined.reconnectToken)

    const hostOpening = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    const guestOpening = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([hostOpening, guestOpening])

    // 房主提交行动，**访客**应该先看到房主的原话（action.broadcast，
    // 此前只在发送方本地显示，其他人只能看到守秘人转述——三人联机实测
    // 的"隔离"bug），再看到守秘人回复（narration.push）。
    const guestSeesUtterance = waitForEvent(
      guest.sdk,
      (e) => e.type === 'action.broadcast' && e.payload.utterance === '我与托马斯交谈'
    )
    const guestSeesNarration = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    const completed = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: 'discussion-echo-host',
      utterance: '我与托马斯交谈',
      recipient: EXPLICIT_KEEPER,
    })
    const echo = await guestSeesUtterance
    if (echo.type === 'action.broadcast') {
      assert.equal(echo.payload.playerId, room.hostPlayerId)
      assert.ok(echo.payload.nickname.length > 0)
      assert.equal(echo.payload.characterName, 'E2E 调查员')
    }
    await Promise.all([guestSeesNarration, completed])

    const conversation = await room.host.sdk.rooms.listConversation(room.roomId, room.reconnectToken)
    const action = conversation.find((event) => event.type === 'action.broadcast')
    assert.ok(action)
    if (action?.type === 'action.broadcast') {
      assert.equal(action.payload.characterName, 'E2E 调查员')
    }
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})

test('行动锁：处理中他人提交进入队列，完成后自动出队', async () => {
  const room = await createRoomWithModule('lock', 2)
  const guest = await registerPlayer('lockguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '抢话访客' }, guest.token)

  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken)

  try {
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )
    await bindSocket(guest.sdk, room.roomId, guest.token, joined.playerId, joined.reconnectToken)

    const hostOpening = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    const guestOpening = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([hostOpening, guestOpening])

    // 房主提交——整个回合期间锁都开着。等到原话广播到达（证明房主的提交已被
    // 受理、锁已被持有）再让访客抢。
    const hostNarration = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    const hostEcho = waitForEvent(room.host.sdk, (e) => e.type === 'action.broadcast')
    const hostCompleted = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: 'action-lock-host',
      utterance: '我与托马斯交谈',
      recipient: EXPLICIT_KEEPER,
    })
    await hostEcho

    const guestQueued = waitForEvent(
      guest.sdk,
      (e) =>
        e.type === 'room.action.state' &&
        Array.isArray(e.payload.queued) &&
        e.payload.queued.some((item) => item.clientActionId === 'action-lock-guest-queued')
    )
    const guestEcho = waitForEvent(
      guest.sdk,
      (e) => e.type === 'action.broadcast' && e.payload.utterance === '我翻抽屉'
    )
    const queuedAction = guest.sdk.roomSocket.submitPlannedAction(joined.playerId, {
      clientActionId: 'action-lock-guest-queued',
      utterance: '我翻抽屉',
      recipient: EXPLICIT_KEEPER,
    })
    await Promise.all([guestQueued, guestEcho])

    await Promise.all([hostNarration, hostCompleted])
    const queuedCompleted = await queuedAction
    assert.equal(queuedCompleted.player_view.player_id, joined.playerId)
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})

test('🔴 结束游戏清空聊天记录，复盘（replay）从头到尾不含聊天内容', async () => {
  const room = await createRoomWithModule('endchat')

  try {
    await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
    await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
    await bindSocket(
      room.host.sdk, room.roomId, room.host.token, room.hostPlayerId, room.reconnectToken
    )

    // 推进到 InGame（end 只允许结束进行中的游戏）
    const opening = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await opening

    const chatEcho = waitForEvent(room.host.sdk, (e) => e.type === 'chat.message')
    room.host.sdk.roomSocket.sendChat(room.hostPlayerId, {
      text: '这句话不该进复盘', clientMessageId: randomUUID(),
    })
    await chatEcho

    // end 前查得到聊天
    const before = await room.host.sdk.rooms.listMessages(room.roomId, room.reconnectToken)
    assert.equal(before.length, 1)

    await room.host.sdk.rooms.endGame(room.roomId, room.reconnectToken)

    // end 后聊天被清空
    const after = await room.host.sdk.rooms.listMessages(room.roomId, room.reconnectToken)
    assert.equal(after.length, 0)

    // replay 里没有任何聊天内容（聊天从不写 events 表）
    const replay = await room.host.sdk.rooms.getReplay(room.roomId, room.reconnectToken)
    assert.ok(!JSON.stringify(replay).includes('这句话不该进复盘'))
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})
