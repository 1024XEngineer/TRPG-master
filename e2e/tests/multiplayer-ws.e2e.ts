/**
 * 多人 + WebSocket 的端到端验证。
 *
 * 这是 SDK 层 e2e 相对浏览器 e2e 最有价值的地方：**在一个进程里起三个客户端**，
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

type PendingAdjudicationEvent = Extract<
  ServerToClientEvent,
  { type: 'adjudication.pending' }
>
type TestSdk = Awaited<ReturnType<typeof registerPlayer>>['sdk']

async function selectSkillAndAcceptResult(
  sdk: TestSdk,
  playerId: string,
  pendingEvent: PendingAdjudicationEvent,
  requestPrefix: string,
): Promise<PendingAdjudicationEvent> {
  const pending = pendingEvent.payload
  assert.equal(pending.status, 'awaiting_skill_choice')
  const decision = pending.pendingDecision
  assert.ok(decision)

  const rolledPromise = waitForEvent(
    sdk,
    (event) =>
      event.type === 'adjudication.pending' &&
      event.payload.correlationId === pending.correlationId &&
      event.payload.status === 'awaiting_post_roll_decision',
  )
  sdk.roomSocket.selectAdjudication(playerId, {
    clientActionId: pending.correlationId,
    requestId: `${requestPrefix}:select`,
    sourceRevision: pending.sourceRevision,
    decisionId: decision.decision_id,
    decisionVersion: decision.decision_version,
    candidateId: decision.options[0].candidate_id,
  })
  const rolled = await rolledPromise
  assert.equal(rolled.type, 'adjudication.pending')
  const checkRun = rolled.payload.checkRun
  assert.ok(checkRun)
  const accept = (checkRun.post_roll_options ?? []).find(
    (option) => option.kind === 'accept_result',
  )
  assert.ok(accept)
  sdk.roomSocket.decidePostRoll(playerId, {
    clientActionId: rolled.payload.correlationId,
    requestId: `${requestPrefix}:accept`,
    sourceRevision: rolled.payload.sourceRevision,
    checkId: checkRun.check_id,
    checkVersion: checkRun.version,
    optionId: accept.option_id,
  })
  return rolled
}

/** 收集事件直到出现终止事件，返回这期间收到的全部事件（含终止事件本身）。 */
function collectUntil(
  socketOwner: { roomSocket: { onMessage: (h: (e: ServerToClientEvent) => void) => () => void } },
  terminal: (event: ServerToClientEvent) => boolean,
  timeoutMs = 5_000
): Promise<ServerToClientEvent[]> {
  return new Promise((resolve, reject) => {
    const seen: ServerToClientEvent[] = []
    const timer = setTimeout(() => {
      off()
      reject(new Error(`等待终止事件超时（${timeoutMs}ms）；已收到 ${seen.length} 条`))
    }, timeoutMs)
    const off = socketOwner.roomSocket.onMessage((event) => {
      seen.push(event)
      if (!terminal(event)) return
      clearTimeout(timer)
      off()
      resolve(seen)
    })
  })
}

/** 建好角色卡并标记完成——`game.start` 要求全员建完卡。 */
async function buildCharacter(
  sdk: Awaited<ReturnType<typeof registerPlayer>>['sdk'],
  roomId: string,
  reconnectToken: string,
  characterName = 'E2E 调查员',
): Promise<void> {
  const draft = await sdk.characters.createDraft(roomId, reconnectToken)
  await sdk.characters.save(
    roomId,
    draft.characterId,
    { ...legalCharacterPayload(LEGAL_ATTRIBUTES), name: characterName },
    reconnectToken
  )
  await sdk.characters.complete(roomId, draft.characterId, reconnectToken)
}

test('第二个玩家用房间码加入，房间预览里能看到两个人', async () => {
  const room = await createRoomWithModule('mp', 2)
  const guest = await registerPlayer('guest')

  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  assert.equal(joined.roomId, room.roomId)

  const preview = await room.host.sdk.rooms.getInfo(room.roomCode)
  assert.equal(preview.players.length, 2)
  assert.equal(preview.players.filter((p) => p.isHost).length, 1, '有且只有一个房主')
})

test('WS 生命周期：开局后重连会重放同一条权威开场', async () => {
  const room = await createRoomWithModule('ws', 2)
  const guest = await registerPlayer('wsguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  // 房间生命周期是 Lobby →(start_story)→ Building →(game.start)→ InGame。
  // 少了 start_story 这步，房间还在 Lobby，game.start 会被拒——第一版就是漏了
  // 它，现象是干等 session.bound 之后的旁白直到超时。
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)

  // 两人各自建卡——game.start 要求全员建完
  await buildCharacter(
    room.host.sdk,
    room.roomId,
    room.reconnectToken,
    '房主调查员',
  )
  await buildCharacter(
    guest.sdk,
    room.roomId,
    joined.reconnectToken,
    '访客调查员',
  )

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
    assert.equal(narrationEvent.payload.messageId, 'game-opening')
    assert.match(narrationEvent.payload.text, /房主调查员/)
    assert.match(narrationEvent.payload.text, /访客调查员/)
    assert.match(narrationEvent.payload.text, /会计师/)

    // 刻意不先请求 conversation：即使一次历史请求恰好读在开场提交之前，
    // 新连接的 room.join 也必须直接收到数据库里同一个 game-opening。
    room.host.sdk.roomSocket.disconnect()
    const reconnected = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
    await room.host.sdk.roomSocket.waitForOpen(reconnected)
    const replayedOpening = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'narration.push' &&
        event.payload.messageId === 'game-opening',
    )
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    const replayedOpeningEvent = await replayedOpening
    assert.equal(replayedOpeningEvent.type, 'narration.push')
    assert.deepEqual(replayedOpeningEvent.payload, narrationEvent.payload)

    const conversation = await room.host.sdk.rooms.listConversation(
      room.roomId,
      room.reconnectToken,
    )
    const openings = conversation.filter(
      (event) =>
        event.type === 'narration.push' &&
        event.payload.messageId === 'game-opening',
    )
    assert.equal(openings.length, 1)
    assert.equal(openings[0]?.id, 'game-opening')
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})

test('三人推进时间需全员确认，最后一票只提交一次并恢复原行动', async () => {
  const room = await createRoomWithModule('time-consent', 3)
  const guest = await registerPlayer('time-consent-guest')
  const joined = await guest.sdk.rooms.join(
    room.roomCode,
    { nickname: '访客' },
    guest.token,
  )
  const third = await registerPlayer('time-consent-third')
  const thirdJoined = await third.sdk.rooms.join(
    room.roomCode,
    { nickname: '第三位玩家' },
    third.token,
  )
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken, '房主调查员')
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken, '访客调查员')
  await buildCharacter(third.sdk, room.roomId, thirdJoined.reconnectToken, '第三位调查员')

  const hostSocket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(hostSocket)
    const hostBound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await hostBound

    const guestSocket = guest.sdk.roomSocket.connect(room.roomId, guest.token)
    await guest.sdk.roomSocket.waitForOpen(guestSocket)
    const guestBound = waitForEvent(guest.sdk, (event) => event.type === 'session.bound')
    guest.sdk.roomSocket.joinRoom(joined.playerId, {
      reconnectToken: joined.reconnectToken,
    })
    await guestBound

    const thirdSocket = third.sdk.roomSocket.connect(room.roomId, third.token)
    await third.sdk.roomSocket.waitForOpen(thirdSocket)
    const thirdBound = waitForEvent(third.sdk, (event) => event.type === 'session.bound')
    third.sdk.roomSocket.joinRoom(thirdJoined.playerId, {
      reconnectToken: thirdJoined.reconnectToken,
    })
    await thirdBound

    const openingForHost = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    const openingForGuest = waitForEvent(
      guest.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    const openingForThird = waitForEvent(
      third.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([openingForHost, openingForGuest, openingForThird])
    const initialRevision = room.host.sdk.roomSocket.getPlayerView()?.revision
    assert.ok(initialRevision)

    const hostPendingPromise = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'time.advance.pending',
    )
    const guestPendingPromise = waitForEvent(
      guest.sdk,
      (event) => event.type === 'time.advance.pending',
    )
    const thirdPendingPromise = waitForEvent(
      third.sdk,
      (event) => event.type === 'time.advance.pending',
    )
    const actionId = `e2e-time-consent-${Date.now()}`
    // 时间提案不属于房主权限：由普通访客发起，房主只作为全员中的一票。
    const completedPromise = guest.sdk.roomSocket.submitPlannedAction(
      joined.playerId,
      {
        clientActionId: actionId,
        utterance: '全队等待到下一个时间点',
      },
    )
    const [hostPending, guestPending, thirdPending] = await Promise.all([
      hostPendingPromise,
      guestPendingPromise,
      thirdPendingPromise,
    ])
    assert.equal(hostPending.type, 'time.advance.pending')
    assert.equal(guestPending.type, 'time.advance.pending')
    assert.equal(thirdPending.type, 'time.advance.pending')
    assert.deepEqual(guestPending.payload, hostPending.payload)
    assert.deepEqual(thirdPending.payload, hostPending.payload)
    assert.deepEqual(hostPending.payload.acceptedPlayerIds, [joined.playerId])
    assert.equal(hostPending.payload.requesterPlayerId, joined.playerId)
    assert.notEqual(hostPending.payload.requesterPlayerId, room.hostPlayerId)

    const thirdUpdatedPromise = waitForEvent(
      third.sdk,
      (event) =>
        event.type === 'time.advance.pending' &&
        event.payload.acceptedPlayerIds.includes(joined.playerId),
    )
    room.host.sdk.roomSocket.respondToTimeAdvance(room.hostPlayerId, {
      proposalId: hostPending.payload.proposalId,
      proposalVersion: hostPending.payload.proposalVersion,
      sourceRevision: hostPending.payload.sourceRevision,
      accept: true,
    })
    await thirdUpdatedPromise

    const hostResolvedPromise = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'time.advance.resolved',
    )
    const guestResolvedPromise = waitForEvent(
      guest.sdk,
      (event) => event.type === 'time.advance.resolved',
    )
    const thirdResolvedPromise = waitForEvent(
      third.sdk,
      (event) => event.type === 'time.advance.resolved',
    )
    // 刻意复用三端最初收到的旧版本，验证别的玩家先确认后不会丢掉最后一票。
    third.sdk.roomSocket.respondToTimeAdvance(thirdJoined.playerId, {
      proposalId: hostPending.payload.proposalId,
      proposalVersion: hostPending.payload.proposalVersion,
      sourceRevision: hostPending.payload.sourceRevision,
      accept: true,
    })
    const [hostResolved, guestResolved, thirdResolved, completed] = await Promise.all([
      hostResolvedPromise,
      guestResolvedPromise,
      thirdResolvedPromise,
      completedPromise,
    ])

    assert.equal(hostResolved.type, 'time.advance.resolved')
    assert.equal(guestResolved.type, 'time.advance.resolved')
    assert.equal(thirdResolved.type, 'time.advance.resolved')
    assert.equal(hostResolved.payload.status, 'approved')
    assert.deepEqual(guestResolved.payload, hostResolved.payload)
    assert.deepEqual(thirdResolved.payload, hostResolved.payload)
    assert.equal(completed.player_id, joined.playerId)
    assert.notEqual(completed.player_view.revision, initialRevision)
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
    third.sdk.roomSocket.disconnect()
  }
})

test('提交行动会广播给房间里的所有人（不只是发起者）', async () => {
  const room = await createRoomWithModule('broadcast', 2)
  const guest = await registerPlayer('bcguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
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

    const hostOpening = waitForEvent(room.host.sdk, (e) => e.type === 'narration.push')
    const guestOpening = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    const [hostOpeningEvent, guestOpeningEvent] = await Promise.all([
      hostOpening,
      guestOpening,
    ])
    if (
      hostOpeningEvent.type === 'narration.push' &&
      guestOpeningEvent.type === 'narration.push'
    ) {
      assert.equal(hostOpeningEvent.payload.messageId, 'game-opening')
      assert.equal(guestOpeningEvent.payload.messageId, 'game-opening')
      assert.deepEqual(guestOpeningEvent.payload, hostOpeningEvent.payload)
    }

    // 房主提交行动，**访客**这一侧应该收到广播
    const guestHears = waitForEvent(guest.sdk, (e) => e.type === 'narration.push')
    const actionId = `e2e-action-${Date.now()}`
    const completed = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: actionId,
      utterance: '我询问托马斯藏书的情况',
    })
    const [guestNarration, turn] = await Promise.all([guestHears, completed])
    assert.equal(guestNarration.type, 'narration.push')
    assert.equal(turn.player_id, room.hostPlayerId)
    assert.equal(room.host.sdk.roomSocket.getPlayerView()?.player_id, room.hostPlayerId)
  } finally {
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
  }
})

test('三客户端串行动作、私有检定与重连快照保持隔离', async () => {
  const room = await createRoomWithModule('three-client', 3)
  const guest = await registerPlayer('three-client-guest')
  const third = await registerPlayer('three-client-third')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  const thirdJoined = await third.sdk.rooms.join(
    room.roomCode,
    { nickname: '第三位玩家' },
    third.token,
  )
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken, '房主调查员')
  await buildCharacter(guest.sdk, room.roomId, joined.reconnectToken, '访客调查员')
  await buildCharacter(third.sdk, room.roomId, thirdJoined.reconnectToken, '第三位调查员')

  const hostEvents: ServerToClientEvent[] = []
  const guestEvents: ServerToClientEvent[] = []
  const thirdEvents: ServerToClientEvent[] = []
  const offHost = room.host.sdk.roomSocket.onMessage((event) => hostEvents.push(event))
  const offGuest = guest.sdk.roomSocket.onMessage((event) => guestEvents.push(event))
  const offThird = third.sdk.roomSocket.onMessage((event) => thirdEvents.push(event))
  const hostSocket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(hostSocket)
    const hostBound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await hostBound

    const guestSocket = guest.sdk.roomSocket.connect(room.roomId, guest.token)
    await guest.sdk.roomSocket.waitForOpen(guestSocket)
    const guestBound = waitForEvent(guest.sdk, (event) => event.type === 'session.bound')
    guest.sdk.roomSocket.joinRoom(joined.playerId, { reconnectToken: joined.reconnectToken })
    await guestBound

    const thirdSocket = third.sdk.roomSocket.connect(room.roomId, third.token)
    await third.sdk.roomSocket.waitForOpen(thirdSocket)
    const thirdBound = waitForEvent(third.sdk, (event) => event.type === 'session.bound')
    third.sdk.roomSocket.joinRoom(thirdJoined.playerId, {
      reconnectToken: thirdJoined.reconnectToken,
    })
    await thirdBound

    const hostOpeningView = waitForEvent(room.host.sdk, (event) => event.type === 'view.updated')
    const guestOpeningView = waitForEvent(guest.sdk, (event) => event.type === 'view.updated')
    const thirdOpeningView = waitForEvent(third.sdk, (event) => event.type === 'view.updated')
    const allOpenings = [room.host.sdk, guest.sdk, third.sdk].map((sdk) =>
      waitForEvent(
        sdk,
        (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
      )
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    const [hostView, guestView, thirdView] = await Promise.all([
      hostOpeningView,
      guestOpeningView,
      thirdOpeningView,
      ...allOpenings,
    ])
    assert.equal(hostView.type, 'view.updated')
    assert.equal(guestView.type, 'view.updated')
    assert.equal(thirdView.type, 'view.updated')
    assert.equal(hostView.payload.playerId, room.hostPlayerId)
    assert.equal(guestView.payload.playerId, joined.playerId)
    assert.equal(thirdView.payload.playerId, thirdJoined.playerId)

    const travelActionId = `three-client-travel-${Date.now()}`
    const guestSeesProcessing = waitForEvent(
      guest.sdk,
      (event) =>
        event.type === 'room.action.state' &&
        event.payload.status === 'processing' &&
        event.payload.clientActionId === travelActionId,
    )
    const travelled = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: travelActionId,
      utterance: '我前往阿诺兹堡图书馆',
    })
    await guestSeesProcessing

    const rejectedActionId = `three-client-conflict-${Date.now()}`
    await assert.rejects(
      guest.sdk.roomSocket.submitPlannedAction(joined.playerId, {
        clientActionId: rejectedActionId,
        utterance: '我同时翻查书架',
      }),
      (error: unknown) =>
        error instanceof Error &&
        'code' in error &&
        error.code === 'ACTION_IN_PROGRESS',
    )
    const travelTurn = await travelled
    assert.equal(travelTurn.player_view.scene.id, 'library')
    assert.equal(
      thirdEvents.some(
        (event) =>
          event.type === 'action.broadcast' &&
          event.payload.clientActionId === rejectedActionId,
      ),
      false,
    )

    const retried = await guest.sdk.roomSocket.submitPlannedAction(joined.playerId, {
      clientActionId: `three-client-retry-${Date.now()}`,
      utterance: '我在图书馆整理刚才的路线',
    })
    assert.equal(retried.player_id, joined.playerId)

    const checkActionId = `three-client-check-${Date.now()}`
    const guestPrivateStart = guestEvents.length
    const thirdPrivateStart = thirdEvents.length
    const checkRequested = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' &&
        event.payload.correlationId === checkActionId &&
        event.payload.status === 'awaiting_skill_choice',
    )
    const guestHearsResult = waitForEvent(
      guest.sdk,
      (event) =>
        event.type === 'narration.push' && event.payload.messageId === checkActionId,
    )
    const thirdHearsResult = waitForEvent(
      third.sdk,
      (event) =>
        event.type === 'narration.push' && event.payload.messageId === checkActionId,
    )
    const checked = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: checkActionId,
      utterance: '我查阅当地旧报档案',
    })
    const pending = await checkRequested
    assert.equal(pending.type, 'adjudication.pending')
    await selectSkillAndAcceptResult(room.host.sdk, room.hostPlayerId, pending, checkActionId)
    const [checkedTurn] = await Promise.all([checked, guestHearsResult, thirdHearsResult])
    const guestPrivateEvents = guestEvents.slice(guestPrivateStart)
    const thirdPrivateEvents = thirdEvents.slice(thirdPrivateStart)
    for (const events of [guestPrivateEvents, thirdPrivateEvents]) {
      assert.equal(events.some((event) => event.type === 'adjudication.pending'), false)
      assert.equal(events.some((event) => event.type === 'check.result'), false)
      assert.ok(events.some((event) => event.type === 'narration.push'))
    }

    guest.sdk.roomSocket.disconnect()
    const reconnected = guest.sdk.roomSocket.connect(room.roomId, guest.token)
    await guest.sdk.roomSocket.waitForOpen(reconnected)
    const rebound = waitForEvent(guest.sdk, (event) => event.type === 'session.bound')
    const restoredView = waitForEvent(guest.sdk, (event) => event.type === 'view.updated')
    const restoredIdle = waitForEvent(
      guest.sdk,
      (event) => event.type === 'room.action.state' && event.payload.status === 'idle',
    )
    guest.sdk.roomSocket.joinRoom(joined.playerId, { reconnectToken: joined.reconnectToken })
    await rebound
    const [viewAfterReconnect] = await Promise.all([restoredView, restoredIdle])
    assert.equal(viewAfterReconnect.type, 'view.updated')
    assert.equal(viewAfterReconnect.payload.playerId, joined.playerId)
    assert.equal(viewAfterReconnect.payload.playerView.scene.id, checkedTurn.player_view.scene.id)
    assert.equal(viewAfterReconnect.payload.playerView.revision, checkedTurn.player_view.revision)
  } finally {
    offHost()
    offGuest()
    offThird()
    room.host.sdk.roomSocket.disconnect()
    guest.sdk.roomSocket.disconnect()
    third.sdk.roomSocket.disconnect()
  }
})

test('追书人纵切：首场景 → 托马斯 → 图书馆 → 旧报检定 → 视图更新', async () => {
  const room = await createRoomWithModule('vertical')
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)

  const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  const observed: ServerToClientEvent[] = []
  const off = room.host.sdk.roomSocket.onMessage((event) => observed.push(event))
  try {
    await room.host.sdk.roomSocket.waitForOpen(socket)
    const bound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await bound

    const openingView = waitForEvent(room.host.sdk, (event) => event.type === 'view.updated')
    const openingNarration = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push'
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    const [initialView, opening] = await Promise.all([
      openingView,
      openingNarration,
    ])
    assert.equal(initialView.type, 'view.updated')
    assert.equal(opening.type, 'narration.push')
    assert.equal(opening.payload.messageId, 'game-opening')
    assert.match(opening.payload.text, /托马斯的会客室/)
    assert.match(opening.payload.text, /E2E 调查员/)
    assert.match(opening.payload.text, /会计师/)
    assert.equal(initialView.payload.playerView.scene.name, '托马斯的会客室')
    assert.ok(
      (initialView.payload.playerView.known_locations ?? []).some(
        (location) =>
          location.id === 'library' &&
          location.existence === 'known' &&
          location.localization === 'located'
      )
    )

    await room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: `ask-thomas-${Date.now()}`,
      utterance: '我询问托马斯失踪藏书和叔叔的情况',
    })

    const travelled = await room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: `travel-library-${Date.now()}`,
      utterance: '我前往阿诺兹堡图书馆',
    })
    assert.equal(travelled.player_view.scene.id, 'library')
    assert.equal(room.host.sdk.roomSocket.getPlayerView()?.scene.id, 'library')

    const checkActionId = `research-newspaper-${Date.now()}`
    const checkRequested = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' &&
        event.payload.correlationId === checkActionId &&
        event.payload.status === 'awaiting_skill_choice'
    )
    const completed = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: checkActionId,
      utterance: '我查阅当地旧报档案，研究报纸旧刊',
    })
    const request = await checkRequested
    assert.equal(request.type, 'adjudication.pending')
    assert.deepEqual(
      request.payload.pendingDecision?.options.map((option) => option.skill_id),
      ['library-use'],
    )
    const rolled = await selectSkillAndAcceptResult(
      room.host.sdk,
      room.hostPlayerId,
      request,
      checkActionId,
    )
    assert.equal(rolled.payload.checkRun?.roll.passed, true)
    const turn = await completed
    assert.equal(turn.player_view.scene.id, 'library')
    assert.ok(
      turn.player_view.known_information.some((item) =>
        `${item.summary}${item.content}`.includes('公墓跳舞')
      ),
      JSON.stringify(turn.player_view.known_information)
    )
    assert.equal(
      room.host.sdk.roomSocket.getPlayerView()?.revision,
      turn.player_view.revision
    )

    const publicProgress = observed.filter(
      (event) =>
        event.type === 'turn.phase_changed' || event.type === 'adjudication.pending'
    )
    assert.ok(
      publicProgress.some(
        (event) =>
          event.type === 'turn.phase_changed' && event.payload.phase === 'waiting_for_check'
      )
    )
    assert.ok(publicProgress.some((event) => event.type === 'adjudication.pending'))
    const serializedProgress = JSON.stringify(publicProgress)
    assert.equal(serializedProgress.includes('fake_tool_call_001'), false)
    assert.equal(serializedProgress.includes('墓地旧闻档案'), false)
  } finally {
    off()
    room.host.sdk.roomSocket.disconnect()
  }
})

test('v3 规则检定完成后仍可继续提交行动', async () => {
  const room = await createRoomWithModule('v3-check-continuation')
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)

  const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(socket)
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')

    const openingView = waitForEvent(room.host.sdk, (event) => event.type === 'view.updated')
    const openingNarration = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push'
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([openingView, openingNarration])

    await room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: `travel-library-continuation-${Date.now()}`,
      utterance: '我前往阿诺兹堡图书馆',
    })

    const researchActionId = `research-library-continuation-${Date.now()}`
    const checkRequested = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' &&
        event.payload.correlationId === researchActionId &&
        event.payload.status === 'awaiting_skill_choice'
    )
    const checkedAction = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: researchActionId,
      utterance: '我查阅当地旧报档案',
    })
    const request = await checkRequested
    assert.equal(request.type, 'adjudication.pending')
    assert.deepEqual(
      request.payload.pendingDecision?.options.map((option) => option.skill_id),
      ['library-use'],
    )
    const rolled = await selectSkillAndAcceptResult(
      room.host.sdk,
      room.hostPlayerId,
      request,
      researchActionId,
    )
    assert.equal(rolled.payload.checkRun?.roll.passed, true)
    const turn = await checkedAction
    assert.ok(
      turn.player_view.known_information.some((item) => item.id === 'cemetery_dance_report')
    )

    const nextTurn = await room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: `after-v3-check-${Date.now()}`,
      utterance: '我在图书馆整理刚才查到的资料',
    })
    assert.equal(nextTurn.player_id, room.hostPlayerId)
    assert.doesNotMatch(nextTurn.narration.text, /CHECK_PENDING|契约校验/)
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})

test('渐进叙事：开场片段按序到达且拼接结果等于权威 narration.push', async () => {
  const room = await createRoomWithModule('chunk')
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken, '片段调查员')

  const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  try {
    await room.host.sdk.roomSocket.waitForOpen(socket)

    const bound = waitForEvent(room.host.sdk, (e) => e.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await bound

    const streamed = collectUntil(
      room.host.sdk,
      (event) =>
        event.type === 'narration.push' && event.payload.messageId === 'game-opening'
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    const events = await streamed

    const push = events.at(-1)
    assert.equal(push?.type, 'narration.push')
    const chunks = events.filter((event) => event.type === 'narration.chunk')
    assert.ok(chunks.length > 0, '开场应当先下发渐进片段')

    // 片段全部属于同一条消息，序号从 0 连续递增。
    assert.deepEqual(
      chunks.map((chunk) => chunk.payload.messageId),
      chunks.map(() => 'game-opening')
    )
    assert.deepEqual(
      chunks.map((chunk) => chunk.payload.sequence),
      chunks.map((_chunk, index) => index)
    )

    // 这条断言是本用例的核心：客户端把片段拼起来，必须与服务端持久化并推送的
    // 权威文本逐字一致，否则渐进展示会跟最终历史对不上。
    assert.equal(
      chunks.map((chunk) => chunk.payload.text).join(''),
      push?.type === 'narration.push' ? push.payload.text : ''
    )

    // 片段不进权威历史：会话历史里只有一条 game-opening。
    const conversation = await room.host.sdk.rooms.listConversation(
      room.roomId,
      room.reconnectToken
    )
    assert.equal(
      conversation.filter((event) => event.id === 'game-opening').length,
      1
    )
  } finally {
    room.host.sdk.roomSocket.disconnect()
  }
})
