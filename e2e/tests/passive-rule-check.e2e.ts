/**
 * 规则要求的被动检定必须真的走到玩家面前（#398 §阶段三）。
 *
 * `awaiting_passive_check` 此前在 `trpg-backend/app` 与
 * `collaboration_framework/host` 下 grep 零命中：Agenda 挂上去之后无人推进，
 * 表现是规则在检定前的效果照常提交、**检定本身静默丢失**——世界推进了，骰子
 * 没出现。整条链上没有任何一层会报错，所以只有端到端才看得见它。
 *
 * 这里走的是完整实链：真实后端 + WebSocket + SDK。用《追书人》的地穴终局
 * （`enter_crypt/proceed`）作触发点，因为它是 `agent_match` 规则，Fake planner
 * 能确定性地匹配到，不需要真实模型。它的第三个效果把
 * `cemetery_figure.true_form_seen` 翻成 true，`first_sight_of_douglas` 随即
 * 要求一次被动理智检定。
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
const EVENT_TIMEOUT_MS = 20_000
const TEST_TIMEOUT_MS = 60_000

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

/**
 * 把房间直接摆到地穴口。
 *
 * 从办公室一路玩到地穴要经过搬石板等多次检定，每一步都依赖 planner 的语义判断；
 * 本用例要验的是规则引擎的挂起与恢复，不是那条路怎么走，所以直接改权威状态。
 */
function seedCemeteryStench(roomId: string): void {
  const database = new DatabaseSync(DB_FILE)
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const key = roomId.replaceAll('-', '')
    const row = database
      .prepare('SELECT state_json FROM game_sessions WHERE room_id = ?')
      .get(key) as { state_json: string } | undefined
    assert.ok(row, '房间必须已经有 GameSession')
    const state = JSON.parse(row.state_json) as {
      scene_id: string
      entities: Record<string, Record<string, unknown>>
    }
    state.scene_id = 'cemetery'
    // 地穴入口要先被发现过才进 PlayerView；Fake planner 得先看得见它，才谈得上
    // 把玩家那句话匹配到 `crypt_stench_on_entry`。
    state.entities.crypt_entrance = {
      ...state.entities.crypt_entrance,
      discovered: true,
      slab_moved: true,
      entered: false,
    }
    // 食尸鬼群已经露面、那次理智检定还没结算——这正是 `ghoul_crowd_sanity`
    // 等着的条件，任何一条 `entity.state_changed` 都会唤醒它。
    state.entities.ghoul_crowd = { ...state.entities.ghoul_crowd, revealed: true }
    state.entities.case_tracker = {
      ...state.entities.case_tracker,
      crowd_sight_resolved: false,
    }
    database
      .prepare('UPDATE game_sessions SET state_json = ? WHERE room_id = ?')
      .run(JSON.stringify(state), key)
  } finally {
    database.close()
  }
}

interface WorldProbe {
  entered: unknown
  crowdResolved: unknown
  agendas: number
}

function probeWorld(roomId: string): WorldProbe {
  const database = new DatabaseSync(DB_FILE, { readOnly: true })
  database.exec('PRAGMA busy_timeout = 5000')
  try {
    const row = database
      .prepare('SELECT state_json FROM game_sessions WHERE room_id = ?')
      .get(roomId.replaceAll('-', '')) as { state_json: string } | undefined
    assert.ok(row)
    const state = JSON.parse(row.state_json) as {
      entities: Record<string, Record<string, unknown>>
      rule_agendas: Record<string, unknown>
    }
    return {
      entered: state.entities.crypt_entrance?.entered,
      crowdResolved: state.entities.case_tracker?.crowd_sight_resolved,
      agendas: Object.keys(state.rule_agendas).length,
    }
  } finally {
    database.close()
  }
}

async function buildCharacter(
  sdk: TestSdk,
  roomId: string,
  reconnectToken: string,
): Promise<void> {
  const draft = await sdk.characters.createDraft(roomId, reconnectToken)
  await sdk.characters.save(
    roomId,
    draft.characterId,
    {
      ...legalCharacterPayload(LEGAL_ATTRIBUTES),
      skills: { 'credit-rating': 30, 'library-use': 60, 'spot-hidden': 60 },
    },
    reconnectToken,
  )
  await sdk.characters.complete(roomId, draft.characterId, reconnectToken)
}

test(
  'Issue #398：规则要求的被动理智检定经既有检定 UI 弹出、不可取消，并结算到 Agenda 稳定',
  { timeout: TEST_TIMEOUT_MS },
  async () => {
    const room = await createRoomWithModule('issue398-passive')
    await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)
    await buildCharacter(room.host.sdk, room.roomId, room.reconnectToken)

    const socket = room.host.sdk.roomSocket.connect(room.roomId, room.host.token)
    try {
      await room.host.sdk.roomSocket.waitForOpen(socket)
      const bound = waitForEvent(room.host.sdk, (event) => event.type === 'session.bound')
      room.host.sdk.roomSocket.joinRoom(room.hostPlayerId, {
        reconnectToken: room.reconnectToken,
      })
      await bound

      const opening = waitForEvent(room.host.sdk, (event) => event.type === 'narration.push')
      room.host.sdk.roomSocket.startGame(room.hostPlayerId)
      await opening

      seedCemeteryStench(room.roomId)

      const actionId = `issue398-crypt-stench-${Date.now()}`
      const pendingPromise = waitForEvent(
        room.host.sdk,
        (event) =>
          event.type === 'adjudication.pending' && event.payload.correlationId === actionId,
      )
      void room.host.sdk.roomSocket.submitPlannedAction(room.hostPlayerId, {
        clientActionId: actionId,
        utterance: '屏住呼吸钻进石板下的地穴入口',
      })
      const pendingEvent = (await pendingPromise) as PendingAdjudicationEvent

      // 骰子真的出现了——#398 之前这里什么都不会来，规则前面的效果照常提交，
      // 检定静默丢失。
      assert.equal(pendingEvent.payload.status, 'awaiting_skill_choice')
      const decision = pendingEvent.payload.pendingDecision
      assert.ok(decision)
      // 规则自己指定技能，菜单只有一条；规则强制的检定没有取消路由。
      assert.equal(decision.options.length, 1)
      assert.equal(decision.options[0].display_name, '理智')
      assert.equal(decision.allow_cancel, false)

      // 触发检定的效果、以及规则在检定前的那个效果，都已经提交。
      const midway = probeWorld(room.roomId)
      assert.equal(midway.entered, true, '触发检定的那个效果必须已经提交')
      assert.equal(midway.crowdResolved, true, '规则在检定前的效果同样已经提交')
      assert.equal(midway.agendas, 1, '挂起的 Agenda 必须落库，否则无从恢复')

      const rolledPromise = waitForEvent(
        room.host.sdk,
        (event) =>
          event.type === 'adjudication.pending' &&
          event.payload.correlationId === actionId &&
          event.payload.status === 'awaiting_post_roll_decision',
      )
      room.host.sdk.roomSocket.selectAdjudication(room.hostPlayerId, {
        clientActionId: actionId,
        requestId: `${actionId}-select`,
        sourceRevision: pendingEvent.payload.sourceRevision,
        decisionId: decision.decision_id,
        decisionVersion: decision.decision_version,
        candidateId: decision.options[0].candidate_id,
      })
      const rolledEvent = (await rolledPromise) as PendingAdjudicationEvent
      const checkRun = rolledEvent.payload.checkRun
      assert.ok(checkRun)
      assert.equal(checkRun.selected_skill_name, '理智')

      const settled = waitForEvent(room.host.sdk, (event) => event.type === 'narration.push')
      const accept = (checkRun.post_roll_options ?? []).find(
        (option) => option.kind === 'accept_result',
      )
      assert.ok(accept)
      room.host.sdk.roomSocket.decidePostRoll(room.hostPlayerId, {
        clientActionId: actionId,
        requestId: `${actionId}-accept`,
        sourceRevision: rolledEvent.payload.sourceRevision,
        checkId: checkRun.check_id,
        checkVersion: checkRun.version,
        optionId: accept.option_id,
      })
      await settled

      // 结算之后 Agenda 稳定，游标本身不留痕（#398 §阶段一）。
      const final = probeWorld(room.roomId)
      assert.equal(final.agendas, 0, '跑完的 Agenda 不该留在 state 里')
    } finally {
      room.host.sdk.roomSocket.disconnect()
    }
  },
)
