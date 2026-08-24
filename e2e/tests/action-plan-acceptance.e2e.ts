import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import { test } from 'node:test'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { AgentPlayerView, ServerToClientEvent } from 'trpg-sdk'

import { createRoomWithModule, legalCharacterPayload, registerPlayer } from './helpers.ts'

const DB_FILE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../trpg-backend/e2e.db'
)
const LEGAL_ATTRIBUTES = {
  STR: 50, CON: 50, POW: 50, DEX: 50,
  APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
}
const EXPLICIT_KEEPER = { kind: 'keeper', entityId: null, explicit: true } as const

/**
 * 真实 provider 一次结构化输出要几十秒，一个两步计划要跑 planner + 两次步骤裁决
 * + 叙事。Fake 下的 10s / 30s 在真实模型下必然超时，所以按路线放大。
 *
 * 这些用例断言的是「一句话被拆成多步」「某一步要检定」「某条 Canon 信息被发放」，
 * 都是 A 侧模型行为；Fake 的 planner 只认连接词、步骤裁决器永远不出检定，结构上
 * 就不可能满足，因此它们只在 E2E_REAL_MODEL=1 下才有意义。
 */
const REAL_MODEL = process.env.E2E_REAL_MODEL === '1'
const EVENT_TIMEOUT_MS = REAL_MODEL ? 180_000 : 10_000
const TEST_TIMEOUT_MS = REAL_MODEL ? 600_000 : 30_000

function waitForEvent(
  owner: { roomSocket: { onMessage: (handler: (event: ServerToClientEvent) => void) => () => void } },
  predicate: (event: ServerToClientEvent) => boolean,
  timeoutMs = EVENT_TIMEOUT_MS,
): Promise<ServerToClientEvent> {
  return new Promise((resolvePromise, rejectPromise) => {
    const observedTypes: string[] = []
    const timer = setTimeout(() => {
      off()
      rejectPromise(
        new Error(
          `等待 ActionPlan 事件超时（${timeoutMs}ms）；期间收到：${observedTypes.join(', ')}`
        )
      )
    }, timeoutMs)
    const off = owner.roomSocket.onMessage((event) => {
      observedTypes.push(
        event.type === 'adjudication.pending'
          ? `${event.type}:${event.payload.correlationId}`
          : event.type
      )
      if (!predicate(event)) return
      clearTimeout(timer)
      off()
      resolvePromise(event)
    })
  })
}

type PendingAdjudicationEvent = Extract<
  ServerToClientEvent,
  { type: 'adjudication.pending' }
>
type TestSdk = Awaited<ReturnType<typeof registerPlayer>>['sdk']

async function selectPendingSkill(
  sdk: TestSdk,
  playerId: string,
  pendingEvent: PendingAdjudicationEvent,
  requestId: string,
): Promise<PendingAdjudicationEvent> {
  const pending = pendingEvent.payload
  assert.equal(pending.status, 'awaiting_skill_choice')
  const decision = pending.pendingDecision
  assert.ok(decision)
  assert.equal(decision.options.length, 1)

  const rolledPromise = waitForEvent(
    sdk,
    (event) =>
      event.type === 'adjudication.pending' &&
      event.payload.correlationId === pending.correlationId &&
      event.payload.status === 'awaiting_post_roll_decision',
  )
  sdk.roomSocket.selectAdjudication(playerId, {
    clientActionId: pending.correlationId,
    requestId,
    sourceRevision: pending.sourceRevision,
    decisionId: decision.decision_id,
    decisionVersion: decision.decision_version,
    candidateId: decision.options[0].candidate_id,
  })
  const rolled = await rolledPromise
  assert.equal(rolled.type, 'adjudication.pending')
  return rolled
}

function acceptPostRoll(
  sdk: TestSdk,
  playerId: string,
  rolledEvent: PendingAdjudicationEvent,
  requestId: string,
): void {
  const rolled = rolledEvent.payload
  assert.equal(rolled.status, 'awaiting_post_roll_decision')
  const checkRun = rolled.checkRun
  assert.ok(checkRun)
  const accept = (checkRun.post_roll_options ?? []).find(
    (option) => option.kind === 'accept_result',
  )
  assert.ok(accept)
  sdk.roomSocket.decidePostRoll(playerId, {
    clientActionId: rolled.correlationId,
    requestId,
    sourceRevision: rolled.sourceRevision,
    checkId: checkRun.check_id,
    checkVersion: checkRun.version,
    optionId: accept.option_id,
  })
}

async function buildCharacter(
  sdk: Awaited<ReturnType<typeof registerPlayer>>['sdk'],
  roomId: string,
  reconnectToken: string,
): Promise<void> {
  const draft = await sdk.characters.createDraft(roomId, reconnectToken)
  await sdk.characters.save(
    roomId,
    draft.characterId,
    {
      ...legalCharacterPayload(LEGAL_ATTRIBUTES),
      skills: {
        'credit-rating': 30,
        'library-use': 90,
        'spot-hidden': 90,
      },
    },
    reconnectToken,
  )
  await sdk.characters.complete(roomId, draft.characterId, reconnectToken)
}

interface CanonCase {
  name: string
  utterance: string
  destinationSceneId: string
  destinationEntityId: string
  destinationCheckpointId: string
  assertFinal(view: AgentPlayerView): void
}

const CANON_CASES: CanonCase[] = [
  {
    name: '书房搜索',
    utterance: '去书房用侦查搜索线索',
    destinationSceneId: 'kimball_study',
    destinationEntityId: 'study_window',
    destinationCheckpointId: 'search_kimball_study',
    assertFinal(view) {
      assert.ok(
        view.scene.visible_entities.some((entity) => entity.id === 'douglas_diary'),
        '成功搜索后应在最终 PlayerView 中看到已找到的日记',
      )
    },
  },
  {
    name: '图书馆旧报',
    utterance: '去图书馆查旧报纸',
    destinationSceneId: 'library',
    destinationEntityId: 'newspaper_archive',
    destinationCheckpointId: 'research_library_archive',
    assertFinal(view) {
      assert.ok(
        view.known_information.some((item) => item.id === 'cemetery_dance_report'),
        '成功查阅后应公开墓地旧报信息',
      )
    },
  },
  {
    name: '墓地询问',
    utterance: '到墓地用信用评级给守墓人留下好印象并询问线索',
    destinationSceneId: 'cemetery',
    destinationEntityId: 'melodias',
    destinationCheckpointId: 'impress_caretaker',
    assertFinal(view) {
      const caretaker = view.scene.visible_entities.find((entity) => entity.id === 'melodias')
      assert.ok(caretaker, '最终 PlayerView 应保留目的地可见守墓人')
    },
  },
]

function assertPersistedPlan(roomId: string, actionId: string): void {
  const database = new DatabaseSync(DB_FILE, { readOnly: true })
  database.exec('PRAGMA busy_timeout = 5000')
  const persistedRoomId = roomId.replaceAll('-', '')
  try {
    const row = database.prepare(
      `SELECT status, current_step_index, run_json
       FROM action_plan_runs
       WHERE room_id = ? AND parent_action_id = ?`
    ).get(persistedRoomId, actionId) as {
      status: string
      current_step_index: number
      run_json: string
    } | undefined
    assert.ok(row, 'SQL ActionPlanRun 必须存在')
    assert.equal(row.status, 'completed')
    assert.equal(row.current_step_index, 2)
    const run = JSON.parse(row.run_json) as { steps?: unknown[] }
    assert.equal(run.steps?.length, 2)

    const commands = database.prepare(
      `SELECT COUNT(*) AS count
       FROM adjudication_command_executions
       WHERE room_id = ? AND action_request_id IN (
         SELECT json_extract(value, '$.step_request_id')
         FROM action_plan_runs, json_each(action_plan_runs.run_json, '$.steps')
         WHERE room_id = ? AND parent_action_id = ?
       )`
    ).get(persistedRoomId, persistedRoomId, actionId) as { count: number }
    assert.equal(
      commands.count,
      4,
      '两次 step submit、一次技能选择和一次结果接受应各持久化一次',
    )
  } finally {
    database.close()
  }
}

function assertPersistedCancellation(roomId: string, actionId: string): void {
  const database = new DatabaseSync(DB_FILE, { readOnly: true })
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const row = database.prepare(
      `SELECT status, current_step_index
       FROM action_plan_runs
       WHERE room_id = ? AND parent_action_id = ?`
    ).get(roomId.replaceAll('-', ''), actionId) as {
      status: string
      current_step_index: number
    } | undefined
    assert.ok(row)
    assert.equal(row.status, 'cancelled')
    assert.equal(row.current_step_index, 1)
  } finally {
    database.close()
  }
}

for (const canon of CANON_CASES) {
  test(`Issue #246 Canon：${canon.name}由一次 action.plan.submit 完成`, { timeout: TEST_TIMEOUT_MS }, async () => {
    const room = await createRoomWithModule(`canon-${canon.destinationSceneId}`)
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

      const openingViewPromise = waitForEvent(
        room.host.sdk,
        (event) => event.type === 'view.updated',
      )
      const openingNarration = waitForEvent(
        room.host.sdk,
        (event) => event.type === 'narration.push',
      )
      room.host.sdk.roomSocket.startGame(room.hostPlayerId)
      const [openingViewEvent] = await Promise.all([openingViewPromise, openingNarration])
      assert.equal(openingViewEvent.type, 'view.updated')
      const initialView = openingViewEvent.payload.playerView
      assert.equal(initialView.scene.id, 'thomas_office')
      assert.equal(
        initialView.scene.visible_entities.some(
          (entity) => entity.id === canon.destinationEntityId,
        ),
        false,
        '目的地实体不得提前进入第一步 PlayerView',
      )
      assert.equal(
        initialView.checkpoint_options.some(
          (checkpoint) => checkpoint.id === canon.destinationCheckpointId,
        ),
        false,
        '目的地 Checkpoint 不得提前进入第一步 PlayerView',
      )

      const actionId = `canon-${canon.destinationSceneId}-${Date.now()}`
      const pendingPromise = waitForEvent(
        room.host.sdk,
        (event) =>
          event.type === 'adjudication.pending' &&
          event.payload.correlationId === actionId,
      )
      const turnPromise = room.host.sdk.roomSocket.submitPlannedAction(
        room.hostPlayerId,
        { clientActionId: actionId, utterance: canon.utterance, recipient: EXPLICIT_KEEPER },
      )
      const pendingEvent = await pendingPromise
      assert.equal(pendingEvent.type, 'adjudication.pending')
      const pending = pendingEvent.payload
      assert.equal(pending.status, 'awaiting_skill_choice')
      assert.ok(pending.planId, '复合行动 pending 必须归属于持久化 PlanRun')
      assert.notEqual(
        pending.sourceRevision,
        initialView.revision,
        '目的地裁决必须绑定 travel 提交后的新 revision',
      )
      assert.ok(pending.pendingDecision)
      const decision = pending.pendingDecision
      assert.equal(decision.summary.includes(canon.utterance), false)
      assert.equal(decision.options.length, 1)

      const rolled = await selectPendingSkill(
        room.host.sdk,
        room.hostPlayerId,
        pendingEvent,
        `${actionId}:select`,
      )
      const completedProgress = waitForEvent(
        room.host.sdk,
        (event) =>
          event.type === 'plan.completed' &&
          event.payload.correlationId === actionId,
      )
      acceptPostRoll(room.host.sdk, room.hostPlayerId, rolled, `${actionId}:accept`)
      const [turn, terminal] = await Promise.all([turnPromise, completedProgress])
      assert.equal(terminal.type, 'plan.completed')
      assert.equal(terminal.payload.completedSteps, 2)
      assert.equal(turn.player_view.scene.id, canon.destinationSceneId)
      assert.equal(
        room.host.sdk.roomSocket.getPlayerView()?.revision,
        turn.player_view.revision,
      )
      canon.assertFinal(turn.player_view)
      assert.match(turn.narration.text, /依次完成/)

      const actionEchoes = observed.filter(
        (event) =>
          event.type === 'action.broadcast' &&
          event.payload.clientActionId === actionId,
      )
      assert.equal(actionEchoes.length, 1, '玩家原话必须作为一个父行动持久化和广播')
      const actionEcho = actionEchoes[0]
      assert.equal(actionEcho?.type, 'action.broadcast')
      if (actionEcho?.type !== 'action.broadcast') {
        assert.fail('缺少 action.broadcast')
      }
      assert.equal(actionEcho.payload.utterance, canon.utterance)
      const started = observed.find(
        (event) =>
          event.type === 'plan.started' && event.payload.correlationId === actionId,
      )
      assert.equal(started?.type, 'plan.started')
      assert.equal(started.payload.totalSteps, 2)

      const publicProgress = observed.filter(
        (event) =>
          event.type.startsWith('plan.') || event.type === 'adjudication.pending',
      )
      const serializedProgress = JSON.stringify(publicProgress)
      for (const forbidden of [
        'success_effects',
        'failure_effects',
        'raw_adjudication',
        'tool_arguments',
        '公墓地下有神秘生物',
      ]) {
        assert.equal(serializedProgress.includes(forbidden), false)
      }

      const conversation = await room.host.sdk.rooms.listConversation(
        room.roomId,
        room.reconnectToken,
      )
      assert.equal(
        conversation.filter(
          (event) =>
            event.type === 'action.broadcast' &&
            event.payload.clientActionId === actionId,
        ).length,
        1,
      )
      assert.equal(
        conversation.filter(
          (event) =>
            event.type === 'narration.push' && event.payload.messageId === actionId,
        ).length,
        1,
      )
      assertPersistedPlan(room.roomId, actionId)
    } finally {
      off()
      room.host.sdk.roomSocket.disconnect()
    }
  })
}

test('Issue #246 恢复：断线重连后用原 parent 恢复 pending，重复选择不重掷', { timeout: TEST_TIMEOUT_MS }, async () => {
  const room = await createRoomWithModule('reconnect-pending')
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  let socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  const observed: ServerToClientEvent[] = []
  const off = room.host.sdk.roomSocket.onMessage((event) => observed.push(event))
  const actionId = `reconnect-pending-${Date.now()}`
  try {
    await room.host.sdk.roomSocket.waitForOpen(socket)
    const bound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await bound
    const firstView = waitForEvent(room.host.sdk, (event) => event.type === 'view.updated')
    const firstOpening = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([firstView, firstOpening])

    const firstPending = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' && event.payload.correlationId === actionId,
    )
    const lostTurn = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: actionId,
      utterance: '去图书馆查旧报纸',
      recipient: EXPLICIT_KEEPER,
    })
    const pending = await firstPending
    assert.equal(pending.type, 'adjudication.pending')
    assert.ok(pending.payload.pendingDecision)
    const firstDecision = pending.payload.pendingDecision
    socket.close()
    room.host.sdk.roomSocket.disconnect()
    await assert.rejects(lostTurn)

    socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
    await room.host.sdk.roomSocket.waitForOpen(socket)
    const rebound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    const openingReplay = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await Promise.all([rebound, openingReplay])

    const resumedPending = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' && event.payload.correlationId === actionId,
    )
    const recoveredTurn = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: actionId,
      utterance: '去图书馆查旧报纸',
      recipient: EXPLICIT_KEEPER,
    })
    const resumed = await resumedPending
    assert.equal(resumed.type, 'adjudication.pending')
    assert.equal(resumed.payload.sourceRevision, pending.payload.sourceRevision)
    assert.deepEqual(resumed.payload.pendingDecision, firstDecision)
    assert.ok(resumed.payload.planId)

    const rolled = await selectPendingSkill(
      room.host.sdk,
      room.hostPlayerId,
      resumed,
      `${actionId}:select`,
    )
    const planCompleted = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'plan.completed' && event.payload.correlationId === actionId,
    )
    const decision = resumed.payload.pendingDecision
    assert.ok(decision)
    acceptPostRoll(room.host.sdk, room.hostPlayerId, rolled, `${actionId}:accept`)
    const [turn] = await Promise.all([recoveredTurn, planCompleted])
    assert.equal(turn.player_view.scene.id, 'library')

    // 模拟“选择请求已被 Engine 提交但客户端没收到响应”的重试：复用同一个
    // requestId/clientActionId，SQL 幂等记录应直接重放，不产生第二次骰点/效果。
    room.host.sdk.roomSocket.selectAdjudication(room.hostPlayerId, {
      clientActionId: actionId,
      requestId: `${actionId}:select`,
      sourceRevision: resumed.payload.sourceRevision,
      decisionId: decision.decision_id,
      decisionVersion: decision.decision_version,
      candidateId: decision.options[0].candidate_id,
    })
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
    const conversation = await room.host.sdk.rooms.listConversation(
      room.roomId,
      room.reconnectToken,
    )
    assert.equal(
      conversation.filter(
        (event) => event.type === 'narration.push' && event.payload.messageId === actionId,
      ).length,
      1,
    )
    assertPersistedPlan(room.roomId, actionId)
    assert.equal(
      observed.some(
        (event) =>
          event.type === 'turn.failed' && event.payload.correlationId === actionId,
      ),
      false,
    )
  } finally {
    off()
    room.host.sdk.roomSocket.disconnect()
  }
})

test('Issue #246 恢复：取消保留已提交 travel 且停止剩余步骤', { timeout: TEST_TIMEOUT_MS }, async () => {
  const room = await createRoomWithModule('cancel-plan')
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)
  const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  const off = room.host.sdk.roomSocket.onMessage(() => undefined)
  const actionId = `cancel-plan-${Date.now()}`
  try {
    await room.host.sdk.roomSocket.waitForOpen(socket)
    const bound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
    room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
      reconnectToken: room.reconnectToken,
    })
    await bound
    const firstView = waitForEvent(room.host.sdk, (event) => event.type === 'view.updated')
    const firstOpening = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'narration.push' && event.payload.messageId === 'game-opening',
    )
    room.host.sdk.roomSocket.startGame(room.hostPlayerId)
    await Promise.all([firstView, firstOpening])
    const pending = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'adjudication.pending' && event.payload.correlationId === actionId,
    )
    const turnPromise = room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
      clientActionId: actionId,
      utterance: '去书房用侦查搜索线索',
      recipient: EXPLICIT_KEEPER,
    })
    await pending
    const completedEvent = waitForEvent(
      room.host.sdk,
      (event) => event.type === 'view.updated' && event.payload.playerId === room.hostPlayerId,
    )
    room.host.sdk.roomSocket.cancelActionPlan(room.hostPlayerId, {
      clientActionId: actionId,
      requestId: `${actionId}:cancel`,
    })
    const [turn] = await Promise.all([turnPromise, completedEvent])
    assert.equal(turn.player_view.scene.id, 'kimball_study')
    assert.equal(
      turn.player_view.scene.visible_entities.some((entity) => entity.id === 'douglas_diary'),
      false,
      '取消后不得执行剩余搜索步骤',
    )
    assert.match(turn.narration.text, /后续行动已停止/)
    assertPersistedCancellation(room.roomId, actionId)
  } finally {
    off()
    room.host.sdk.roomSocket.disconnect()
  }
})
