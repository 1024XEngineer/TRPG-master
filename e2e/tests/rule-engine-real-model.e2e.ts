/**
 * #398 的两条场景在**真实模型**下的行为验证。
 *
 * 只在 `E2E_REAL_MODEL=1` 下运行，理由与 `action-plan-acceptance.e2e.ts` 里那
 * 段相同：这两条断言的前半截是 A 侧模型行为——「玩家说睡到早晨，模型会不会真的
 * 授权四次时间推进」「模型会不会选中那条规则」——Fake planner 结构上就产不出来
 * （它一次只授权一个 `advance_world_time`，也只按字面提示词匹配规则候选）。
 *
 * 后半截才是本 Issue 修的东西，而它恰恰只在前半截成立时才显形：
 *
 * 1. 一次动作提交多跳时间推进，`enable_night_surveillance` 必须按**进入 18:00
 *    那一刻**的世界匹配，而不是被 06:00 的终态判否（#398 §阶段二）；
 * 2. 规则要求的被动理智检定必须真的走到玩家面前（#398 §阶段三）。
 *
 * CI 用的确定性覆盖在 `passive-rule-check.e2e.ts`（被动检定）与
 * `trpg-backend/tests/test_issue398_event_barrier.py`（多跳时间推进）。
 */
import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import { test } from 'node:test'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { ServerToClientEvent } from 'trpg-sdk'

import { createRoomWithModule, legalCharacterPayload, registerPlayer } from './helpers.ts'

const DB_FILE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../trpg-backend/e2e.db'
)
const LEGAL_ATTRIBUTES = {
  STR: 50, CON: 50, POW: 50, DEX: 50,
  APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
}
// #413 之后行动提交必须带结构化接收者；与其余 e2e 用例保持一致。
const EXPLICIT_KEEPER = { kind: 'keeper', entityId: null, explicit: true } as const
const REAL_MODEL = process.env.E2E_REAL_MODEL === '1'
const EVENT_TIMEOUT_MS = 240_000
const TEST_TIMEOUT_MS = 900_000

type TestSdk = Awaited<ReturnType<typeof registerPlayer>>['sdk']
type PendingAdjudicationEvent = Extract<
  ServerToClientEvent,
  { type: 'adjudication.pending' }
>

function waitForEvent(
  sdk: TestSdk,
  predicate: (event: ServerToClientEvent) => boolean,
  timeoutMs = EVENT_TIMEOUT_MS,
): Promise<ServerToClientEvent> {
  return new Promise((resolvePromise, rejectPromise) => {
    const observed: string[] = []
    const timer = setTimeout(() => {
      off()
      rejectPromise(new Error(`等待事件超时（${timeoutMs}ms）；期间收到：${observed.join(', ')}`))
    }, timeoutMs)
    const off = sdk.roomSocket.onMessage((event) => {
      observed.push(event.type)
      if (!predicate(event)) return
      clearTimeout(timer)
      off()
      resolvePromise(event)
    })
  })
}

function patchState(
  roomId: string,
  mutate: (state: Record<string, any>) => void,
): void {
  const database = new DatabaseSync(DB_FILE)
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const key = roomId.replaceAll('-', '')
    const row = database
      .prepare('SELECT state_json FROM game_sessions WHERE room_id = ?')
      .get(key) as { state_json: string } | undefined
    assert.ok(row, '房间必须已经有 GameSession')
    const state = JSON.parse(row.state_json) as Record<string, any>
    mutate(state)
    database
      .prepare('UPDATE game_sessions SET state_json = ? WHERE room_id = ?')
      .run(JSON.stringify(state), key)
  } finally {
    database.close()
  }
}

function readState(roomId: string): Record<string, any> {
  const database = new DatabaseSync(DB_FILE, { readOnly: true })
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const row = database
      .prepare('SELECT state_json FROM game_sessions WHERE room_id = ?')
      .get(roomId.replaceAll('-', '')) as { state_json: string } | undefined
    assert.ok(row)
    return JSON.parse(row.state_json) as Record<string, any>
  } finally {
    database.close()
  }
}

/** 按 rule.triggered 事件数出某条规则被触发了几次，以及触发它的源事件。 */
function ruleTriggers(roomId: string, ruleId: string) {
  const database = new DatabaseSync(DB_FILE, { readOnly: true })
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const key = roomId.replaceAll('-', '')
    const rows = database
      .prepare('SELECT event_id, type, payload FROM game_events WHERE room_id = ?')
      .all(key) as { event_id: string; type: string; payload: string }[]
    const byId = new Map(rows.map((row) => [row.event_id, row]))
    return rows
      .filter((row) => row.type === 'rule.triggered')
      .map((row) => ({ ...row, parsed: JSON.parse(row.payload) }))
      .filter((row) => row.parsed.rule_id === ruleId)
      .map((row) => {
        const source = byId.get(row.parsed.source_event_id)
        return {
          sourceType: source?.type,
          sourcePayload: source ? JSON.parse(source.payload) : null,
        }
      })
  } finally {
    database.close()
  }
}

async function openRoom(prefix: string) {
  const room = await createRoomWithModule(prefix)
  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
  const draft = await room.host.sdk.characters.createDraft(room.roomId, room.reconnectToken)
  await room.host.sdk.characters.save(
    room.roomId,
    draft.characterId,
    {
      ...legalCharacterPayload(LEGAL_ATTRIBUTES),
      skills: { 'credit-rating': 30, 'library-use': 60, 'spot-hidden': 60 },
    },
    room.reconnectToken,
  )
  await room.host.sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken)

  const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
  await room.host.sdk.roomSocket.waitForOpen(socket)
  const bound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
  room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
    reconnectToken: room.reconnectToken,
  })
  await bound
  const opening = waitForEvent(room.host.sdk, (event) => event.type === 'narration.push')
  room.host.sdk.roomSocket.startGame(room.hostPlayerId)
  await opening
  return room
}

/**
 * 真实模型不是确定性的：同一句话它有时直接授权四次时间推进，有时先反问一句。
 * 反问不是缺陷，是 A 侧的正常行为——但它也意味着这一轮没有构成 #398 的复现
 * 场景。所以这里换几种说法重试，只要有一轮真的跨过了夜里，就用那一轮断言引擎。
 */
const SLEEP_UTTERANCES = [
  '就在这里睡下，一直睡到第二天早晨再起来',
  '我在办公室里睡觉休息，一直睡到第二天早上六点',
  '在这里过夜，睡到明天清晨',
]

test(
  '#398 真实模型：一次「睡到第二天早晨」跨过夜里，夜间监视点按 18:00 的世界开出',
  { timeout: TEST_TIMEOUT_MS, skip: REAL_MODEL ? false : '需要 E2E_REAL_MODEL=1' },
  async () => {
    const room = await openRoom('issue398-real-sleep')
    try {
      let advanced = false
      for (const [index, utterance] of SLEEP_UTTERANCES.entries()) {
        patchState(room.roomId, (state) => {
          state.world_time = {
            current_point_id: 'hour_12',
            current: { day_index: 0, hour_of_day: 12 },
          }
          state.entities.case_tracker = {
            ...state.entities.case_tracker,
            surveillance_available: false,
          }
        })

        const actionId = `issue398-real-sleep-${index}-${Date.now()}`
        const settled = waitForEvent(
          room.host.sdk,
          (event) => event.type === 'narration.push',
        )
        room.host.sdk.roomSocket
          .submitPlannedAction(room.hostPlayerId, {
            clientActionId: actionId,
            utterance,
            recipient: EXPLICIT_KEEPER,
          })
          .catch(() => {})
        await settled

        const now = readState(room.roomId).world_time?.current
        console.log(
          `[#398 真实模型] 第 ${index + 1} 次「${utterance}」→`,
          JSON.stringify(now),
        )
        if (now && (now.day_index > 0 || now.hour_of_day >= 18)) {
          advanced = true
          break
        }
      }

      const state = readState(room.roomId)
      const triggers = ruleTriggers(room.roomId, 'enable_night_surveillance')
      console.log(
        '[#398 真实模型] 最终时间:',
        JSON.stringify(state.world_time),
        '| surveillance_available =',
        state.entities.case_tracker?.surveillance_available,
        '| enable_night_surveillance 触发:',
        JSON.stringify(triggers),
      )

      // 前半截是模型行为：它得真的授权跨过夜里的多跳推进。三次说法都没推进，就
      // 说明这一轮没有构成 #398 的复现场景，问题在 A 侧而不是引擎。
      assert.ok(
        advanced,
        '三次尝试模型都没有把时间推进到夜里或次日；这一轮不构成 #398 的复现场景',
      )
      // 后半截才是 #398 修的东西：只要跨过了 18:00，夜间监视点就必须开出来。
      // 修复前这里会是 false——18:00 那条事件被 06:00 的终态判否。
      assert.equal(
        state.entities.case_tracker?.surveillance_available,
        true,
        '跨过夜间时间点后 enable_night_surveillance 必须触发',
      )
      assert.ok(triggers.length >= 1)
      assert.equal(triggers[0].sourceType, 'time.point_entered')
      assert.equal(triggers[0].sourcePayload?.time_of_day, 'night')
    } finally {
      room.host.sdk.roomSocket.disconnect()
    }
  },
)

/**
 * 一直等到「规则强制的」那次检定。
 *
 * 玩家自己那次行动可能先要一次普通检定（`move_crypt_slab` 掷力量），它是可取消
 * 的、菜单由 Agent 候选生成；规则拥有的那次不可取消、菜单只有一条。沿途把普通
 * 检定照常结算掉，这也顺带验证了同一个 action 上先后挂两次检定——正是迁移
 * b8c9d0e1f2a3 放开的能力。
 */
async function waitForRuleOwnedCheck(
  room: Awaited<ReturnType<typeof openRoom>>,
  actionId: string,
): Promise<PendingAdjudicationEvent> {
  for (let round = 0; round < 4; round += 1) {
    const pendingEvent = (await waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' &&
        event.payload.correlationId === actionId &&
        event.payload.status === 'awaiting_skill_choice',
    )) as PendingAdjudicationEvent
    const decision = pendingEvent.payload.pendingDecision
    assert.ok(decision)
    if (!decision.allow_cancel) return pendingEvent

    console.log(
      '[#398 真实模型] 先结算玩家自己的检定:',
      decision.options.map((option) => option.display_name).join(' / '),
    )
    const rolled = waitForEvent(
      room.host.sdk,
      (event) =>
        event.type === 'adjudication.pending' &&
        event.payload.correlationId === actionId &&
        event.payload.status === 'awaiting_post_roll_decision',
    )
    room.host.sdk.roomSocket.selectAdjudication(room.hostPlayerId, {
      clientActionId: actionId,
      requestId: `${actionId}-select-${round}`,
      sourceRevision: pendingEvent.payload.sourceRevision,
      decisionId: decision.decision_id,
      decisionVersion: decision.decision_version,
      candidateId: decision.options[0].candidate_id,
    })
    const rolledEvent = (await rolled) as PendingAdjudicationEvent
    const checkRun = rolledEvent.payload.checkRun
    assert.ok(checkRun)
    const accept = (checkRun.post_roll_options ?? []).find(
      (option) => option.kind === 'accept_result',
    )
    assert.ok(accept)
    room.host.sdk.roomSocket.decidePostRoll(room.hostPlayerId, {
      clientActionId: actionId,
      requestId: `${actionId}-accept-${round}`,
      sourceRevision: rolledEvent.payload.sourceRevision,
      checkId: checkRun.check_id,
      checkVersion: checkRun.version,
      optionId: accept.option_id,
    })
  }
  throw new Error('连续四轮都没有等到规则强制的检定')
}

test(
  '#398 真实模型：规则要求的被动理智检定弹到玩家面前，且不可取消',
  { timeout: TEST_TIMEOUT_MS, skip: REAL_MODEL ? false : '需要 E2E_REAL_MODEL=1' },
  async () => {
    const room = await openRoom('issue398-real-san')
    try {
      patchState(room.roomId, (state) => {
        state.scene_id = 'cemetery'
        // 石板已经被发现但还没搬开：给模型一个它在 PlayerView 里真看得见、
        // 也真有规则候选可用的目标。
        state.entities.crypt_entrance = {
          ...state.entities.crypt_entrance,
          discovered: true,
          slab_moved: false,
          entered: false,
        }
        // 食尸鬼群已经露面、那次理智检定还没结算——`ghoul_crowd_sanity` 等的就是
        // 这个条件（它是 #398 点名的四处被动检定之一）。
        state.entities.ghoul_crowd = { ...state.entities.ghoul_crowd, revealed: true }
        state.entities.case_tracker = {
          ...state.entities.case_tracker,
          crowd_sight_resolved: false,
        }
      })

      const actionId = `issue398-real-san-${Date.now()}`
      room.host.sdk.roomSocket
        .submitPlannedAction(room.hostPlayerId, {
          clientActionId: actionId,
          utterance: '用力量掀开墓地里那块盖住地穴入口的石板',
          recipient: EXPLICIT_KEEPER,
        })
        .catch(() => {})
      const pendingEvent = await waitForRuleOwnedCheck(room, actionId)
      const decision = pendingEvent.payload.pendingDecision
      assert.ok(decision)
      console.log(
        '[#398 真实模型] 规则强制的检定:',
        JSON.stringify({
          options: decision.options.map((option) => option.display_name),
          allowCancel: decision.allow_cancel,
          target: decision.options[0].target_value,
        }),
      )

      // 规则拥有的被动检定：单条选项、由规则写死、不可取消。
      assert.equal(decision.options.length, 1)
      assert.equal(decision.options[0].display_name, '理智')
      assert.equal(decision.allow_cancel, false)

      const state = readState(room.roomId)
      assert.equal(
        state.entities.case_tracker?.crowd_sight_resolved,
        true,
        '规则在检定前的效果照常提交',
      )
      assert.equal(
        Object.keys(state.rule_agendas ?? {}).length,
        1,
        '挂起的 Agenda 必须落库，否则无从恢复',
      )
    } finally {
      room.host.sdk.roomSocket.disconnect()
    }
  },
)
