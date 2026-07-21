/**
 * 多人 + WebSocket 的端到端验证。
 *
 * 这是 SDK 层 e2e 相对浏览器 e2e 最有价值的地方：**在一个进程里起两个客户端**，
 * 比开两个浏览器上下文便宜一个数量级，所以「第二个人加入房间」「广播有没有到达
 * 另一个人」这类断言才做得起。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ServerToClientEvent } from 'trpg-sdk'

import { createRoomWithModule, legalCharacterPayload, registerPlayer } from './helpers.ts'

const LEGAL_ATTRIBUTES = {
  STR: 50, CON: 50, POW: 50, DEX: 50,
  APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
}

/** 等一个满足条件的服务端事件，超时就失败——不要用固定 sleep。 */
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

/** 建好角色卡并标记完成——`game.start` 要求全员建完卡。 */
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

test('第二个玩家用房间码加入，房间预览里能看到两个人', async () => {
  const room = await createRoomWithModule('mp')
  const guest = await registerPlayer('guest')

  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  assert.equal(joined.roomId, room.roomId)

  const preview = await room.host.sdk.rooms.getInfo(room.roomCode)
  assert.equal(preview.players.length, 2)
  assert.equal(preview.players.filter((p) => p.isHost).length, 1, '有且只有一个房主')
})

test('WS 生命周期：join → session.bound，全员建卡后房主可以 game.start', async () => {
  const room = await createRoomWithModule('ws')
  const guest = await registerPlayer('wsguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  // 房间生命周期是 Lobby →(start_story)→ Building →(game.start)→ InGame。
  // 少了 start_story 这步，房间还在 Lobby，game.start 会被拒——第一版就是漏了
  // 它，现象是干等 session.bound 之后的旁白直到超时。
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)

  // 两人各自建卡——game.start 要求全员建完
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken)

  // ⚠️ `try` 必须从 **connect() 之后的第一行**就开始，把 waitForOpen 和绑定
  // 阶段也罩进去。这两步同样会失败/超时，而句柄那时已经建立了——漏在 try 外面
  // 的话 disconnect() 不会执行，WS 句柄会让 node 一直不退出，表现成"测试跑完了
  // 但命令挂住"，最后只能等 job 超时。
  const hostSocket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(hostSocket)

    const bound = waitForEvent(room.host.sdk, (e) => e.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    const boundEvent = await bound
    assert.equal(boundEvent.type, 'session.bound')

    // 房主开始游戏 → 应该收到开场旁白
    const narration = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    const narrationEvent = await narration
    assert.equal(narrationEvent.type, 'narration.push')
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})

test('提交行动会广播给房间里的所有人（不只是发起者）', async () => {
  const room = await createRoomWithModule('broadcast')
  const guest = await registerPlayer('bcguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken)

  // 同上：`try` 从第一个 connect() 之后就开始。这条用例有两个句柄，绑定阶段
  // 失败的机会翻倍，finally 里两个都要断开（访客那个即使还没 connect 成功，
  // disconnect 也是幂等的空操作）。
  const hostSocket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(hostSocket)
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await waitForEvent(room.host.sdk, (e) => e.type === 'session.bound')

    const guestSocket = guest.sdk.roomSocket.connect(room.roomId, guest.token)
    await guest.sdk.roomSocket.waitForOpen(guestSocket)
    guest.sdk.roomSocket.joinRoom(joined.playerId, {
      reconnectToken: joined.reconnectToken,
    })
    await waitForEvent(guest.sdk, (e) => e.type === 'session.bound')

    // 房主提交行动，**访客**这一侧应该收到广播
    const guestHears = waitForEvent(
      guest.sdk,
      (e) => e.type === 'narration.push' && String(e.payload?.text ?? '').includes('推开了门')
    )
    room.host.sdk.roomSocket.submitAction(room.hostPlayerId, { utterance: '我推开了门' })
    await guestHears
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})
