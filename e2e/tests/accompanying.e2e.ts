/** Published module → SDK → WebSocket → Host → engine → persisted PlayerView. */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { ServerToClientEvent } from 'trpg-sdk'
import { createRoomWithModule, legalCharacterPayload, unique, type TestRoom } from './helpers.ts'

type View = NonNullable<ReturnType<TestRoom['host']['sdk']['roomSocket']['getPlayerView']>>
const KEEPER = { kind: 'keeper', entityId: null, explicit: true } as const

function waitFor(
  room: TestRoom,
  predicate: (event: ServerToClientEvent) => boolean,
): Promise<ServerToClientEvent> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      off()
      reject(new Error('等待随行测试事件超时'))
    }, 15_000)
    const off = room.host.sdk.roomSocket.onMessage((event) => {
      if (!predicate(event)) return
      clearTimeout(timer)
      off()
      resolve(event)
    })
  })
}

function james(view: View) {
  const npc = view.scene.visible_entities.find((entity) => entity.id === 'james')
  assert.ok(npc, `詹姆斯应出现在 ${view.scene.id} 的可见 NPC / @ 候选中`)
  return npc
}

function assertFollowing(view: View, expected: boolean) {
  assert.equal(james(view).observable_state.find((state) => state.key === 'accompanying')?.value, expected)
}

async function action(room: TestRoom, utterance: string): Promise<View> {
  const turn = await room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
    clientActionId: unique('follow'), utterance, recipient: KEEPER,
  })
  return turn.player_view
}

async function dialogue(room: TestRoom, entityId: string, utterance: string) {
  const clientActionId = unique('lane-dialogue')
  const reply = waitFor(room, (e) => e.type === 'dialogue.npc' && e.payload.sourceActionId === clientActionId)
  const addressed = waitFor(room, (e) => e.type === 'dialogue.player' && e.payload.clientActionId === clientActionId)
  assert.equal(room.host.sdk.roomSocket.submitNpcDialogue(room.hostPlayerId, {
    clientActionId, utterance,
    recipient: { kind: 'npc', entityId, explicit: true },
  }), true)
  const [player, npc] = await Promise.all([addressed, reply])
  assert.equal(player.type, 'dialogue.player')
  assert.equal(npc.type, 'dialogue.npc')
  assert.equal(player.payload.interlocutorId, entityId)
  assert.equal(npc.payload.speakerId, entityId)
  // Unified Host replies may cite the committed keeper narration as their source.
  assert.equal(npc.payload.sourceActionId, player.payload.clientActionId)
  assert.equal(npc.payload.sceneId, 'lane_manor')
  assert.ok(npc.payload.text.trim())
  return npc.payload.messageId
}

async function withFrogRoom(run: (room: TestRoom, initial: View) => Promise<void>) {
  const room = await createRoomWithModule('follow', 1, 'happy-frog-village')
  const { sdk } = room.host
  await sdk.rooms.startStory(room.roomId, room.reconnectToken)
  const draft = await sdk.characters.createDraft(room.roomId, room.reconnectToken)
  await sdk.characters.save(room.roomId, draft.characterId, legalCharacterPayload({
    STR: 50, CON: 50, POW: 50, DEX: 50, APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
  }), room.reconnectToken)
  await sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken)
  const socket = sdk.roomSocket.connect(room.roomId, room.host.token)
  // Exercise the real check protocol whenever an authored rule requires a roll.
  const off = sdk.roomSocket.onMessage((event) => {
    if (event.type !== 'adjudication.pending') return
    const pending = event.payload
    if (pending.status === 'awaiting_skill_choice' && pending.pendingDecision) {
      const decision = pending.pendingDecision
      sdk.roomSocket.selectAdjudication(room.hostPlayerId, {
        clientActionId: pending.correlationId, requestId: unique('select'),
        sourceRevision: pending.sourceRevision, decisionId: decision.decision_id,
        decisionVersion: decision.decision_version, candidateId: decision.options[0].candidate_id,
      })
    } else if (pending.status === 'awaiting_post_roll_decision' && pending.checkRun) {
      const check = pending.checkRun
      const accept = check.post_roll_options?.find((option) => option.kind === 'accept_result')
      assert.ok(accept)
      sdk.roomSocket.decidePostRoll(room.hostPlayerId, {
        clientActionId: pending.correlationId, requestId: unique('accept'),
        sourceRevision: pending.sourceRevision, checkId: check.check_id,
        checkVersion: check.version, optionId: accept.option_id,
      })
    }
  })
  try {
    await sdk.roomSocket.waitForOpen(socket)
    const bound = waitFor(room, (e) => e.type === 'session.bound')
    sdk.roomSocket.joinRoom(room.hostPlayerId, { reconnectToken: room.reconnectToken })
    await bound
    const opened = waitFor(room, (e) => e.type === 'view.updated')
    sdk.roomSocket.startGame(room.hostPlayerId)
    const opening = await opened
    assert.equal(opening.type, 'view.updated')
    assert.equal(opening.payload.playerView.scene.id, 'lane_manor')
    await run(room, opening.payload.playerView)
  } finally {
    off()
    sdk.roomSocket.disconnect()
  }
}

async function reachReception(room: TestRoom) {
  await action(room, '接受委托寻找詹姆斯')
  const resort = await action(room, '前往蛙蛙度假村')
  assert.equal(resort.scene.id, 'frog_resort')
  const reception = await action(room, '进入接待大厅')
  assert.equal(reception.scene.id, 'resort_reception')
  assertFollowing(reception, false)
}

test('#516/#518：委托人可对话，强行带离后随行回庄园，重连仍在场', { timeout: 120_000 }, async () => {
  await withFrogRoom(async (room, initial) => {
    for (const id of ['richard_lane', 'mrs_lane']) {
      assert.ok(
        initial.scene.visible_entities.some((npc) => npc.id === id && npc.kind === 'npc'),
        `${id} 应当在庄园的可交互 NPC 列表中`,
      )
    }
    const fatherReply = await dialogue(room, 'richard_lane', '请问詹姆斯失踪前的情况？')
    await dialogue(room, 'mrs_lane', '您最后一次见到詹姆斯是什么时候？')
    await reachReception(room)
    // Use the published intent: the Fake also matches 度假村 against the visible map alias.
    const outside = await action(room, '强行把詹姆斯带出去')
    assert.equal(outside.scene.id, 'outside')
    assertFollowing(outside, true)
    // This is the previously broken utterance from #516, without the old 带/一起/同行 gate.
    const home = await action(room, '拽着詹姆斯回到莱恩庄园')
    assert.equal(home.scene.id, 'lane_manor')
    assertFollowing(home, true)
    assert.ok(home.scene.visible_entities.some((npc) => npc.id === 'richard_lane'))
    assert.ok(home.scene.visible_entities.some((npc) => npc.id === 'mrs_lane'))
    await dialogue(room, 'richard_lane', '我们把詹姆斯带回来了。')
    // A second ordinary move must follow without repeating a companion request.
    const forest = await action(room, '前往老林地碎石路')
    assert.equal(forest.scene.id, 'forest_road')
    assertFollowing(forest, true)
    const { sdk } = room.host
    sdk.roomSocket.disconnect()
    const reconnected = sdk.roomSocket.connect(room.roomId, room.host.token)
    await sdk.roomSocket.waitForOpen(reconnected)
    const restored = waitFor(room, (e) => e.type === 'view.updated')
    sdk.roomSocket.joinRoom(room.hostPlayerId, { reconnectToken: room.reconnectToken })
    const snapshot = await restored
    assert.equal(snapshot.type, 'view.updated')
    assert.equal(snapshot.payload.playerView.scene.id, 'forest_road')
    assertFollowing(snapshot.payload.playerView, true)
    const history = await sdk.rooms.listConversation(room.roomId, room.reconnectToken)
    assert.equal(history.filter((entry) => entry.id === fatherReply).length, 1)
  })
})

test('#516：开始随行、否定解除、门禁拒绝、明确解除后不再跟随', { timeout: 120_000 }, async () => {
  await withFrogRoom(async (room) => {
    await reachReception(room)
    assertFollowing(await action(room, '扛起詹姆斯'), true)
    assertFollowing(await action(room, '不要放下詹姆斯'), true)
    const blocked = await action(room, '带詹姆斯进入员工区')
    assert.equal(blocked.scene.id, 'resort_reception')
    assertFollowing(blocked, true)
    const guest = await action(room, '扶着詹姆斯去客房1')
    assert.equal(guest.scene.id, 'guest_room')
    assertFollowing(guest, true)
    assertFollowing(await action(room, '回到接待大厅'), true)
    assertFollowing(await action(room, '放下詹姆斯'), false)
    const alone = await action(room, '前往客房1')
    assert.equal(alone.scene.id, 'guest_room')
    assert.equal(alone.scene.visible_entities.some((npc) => npc.id === 'james'), false)
    assertFollowing(await action(room, '回到接待大厅'), false)
  })
})
