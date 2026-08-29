/**
 * Stateful WebSocket client: validates server events, tracks the latest
 * player-safe view/progress state, and resolves action promises by correlation ID.
 */
import type {
  ActionSubmitPayload,
  ActionPlanCancelPayload,
  AdjudicationChoicePayload,
  AdjudicationPostRollPayload,
  ChatSendPayload,
  AgentPlayerView,
  AgentTurnPayload,
  CheckRollPayload,
  PlayerReadyPayload,
  RoomJoinPayload,
  RoomRejoinPayload,
  SanCheckRollPayload,
  SceneTransitionRespondPayload,
  ServerToClientEvent,
  TimeAdvanceRespondPayload,
  TurnCompletedEvent,
} from '../types';

export type RoomSocketHandler = (event: ServerToClientEvent) => void;

/**
 * 连接状态（issue #505）。`reconnecting` 是"已经断了、正在自动重连"，与
 * `disconnected`（调用方主动断开，不会再自动恢复）必须分开——界面在前者要
 * 提示"正在重连"，在后者应该安静。
 */
export type RoomSocketConnectionState = 'connecting' | 'open' | 'reconnecting' | 'disconnected';

export type RoomSocketConnectionHandler = (state: RoomSocketConnectionState) => void;

/**
 * 心跳间隔。取值要短于链路上最激进的一跳的空闲超时——预览环境的
 * PortForward 网关实测会在无流量时静默切断（服务端 6 小时内 20 次
 * `connection open`、0 次 `connection closed`），且一次开场叙事就能制造
 * 30 秒静默窗口。20 秒是常见网关超时（30/60 秒）的安全分母。
 */
const HEARTBEAT_INTERVAL_MS = 20_000;

/** 发出 ping 后等 pong 的上限；超时即判定链路已死，不再等 TCP 自己发现。 */
const HEARTBEAT_TIMEOUT_MS = 10_000;

/** 重连退避：指数增长但封顶，避免服务端重启期间客户端把它打垮。 */
const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 15_000;

/** 连续重连失败的上限；到顶后停在 disconnected，等调用方决定是否重新连接。 */
const RECONNECT_MAX_ATTEMPTS = 8;

interface PendingAction {
  promise: Promise<AgentTurnPayload>;
  resolve: (payload: AgentTurnPayload) => void;
  reject: (error: Error) => void;
}

export class TurnFailedError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable: boolean,
    readonly correlationId: string,
  ) {
    super(message);
    this.name = 'TurnFailedError';
  }
}

export class RoomSocketServerError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly correlationId: string | null,
  ) {
    super(message);
    this.name = 'RoomSocketServerError';
  }
}

export class RoomSocketTransportError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = 'RoomSocketTransportError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isJsonValue(value: unknown): boolean {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isActorValue(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.value === 'number' &&
    Number.isFinite(value.value)
  );
}

function isValidSelfActor(value: unknown, actorId: string): boolean {
  if (!isRecord(value)) return false;
  return (
    value.id === actorId &&
    typeof value.name === 'string' &&
    (value.occupation === null || typeof value.occupation === 'string') &&
    Array.isArray(value.attributes) &&
    value.attributes.every(isActorValue) &&
    Array.isArray(value.skills) &&
    value.skills.every(isActorValue) &&
    Array.isArray(value.resources) &&
    value.resources.every(isActorValue) &&
    isStringArray(value.conditions) &&
    isStringArray(value.equipment) &&
    typeof value.background_summary === 'string' &&
    (value.public_status_summary === undefined ||
      typeof value.public_status_summary === 'string')
  );
}

function isValidScene(value: unknown, sceneId: string): boolean {
  if (!isRecord(value)) return false;
  return (
    value.id === sceneId &&
    typeof value.name === 'string' &&
    typeof value.description === 'string' &&
    (value.time === null || typeof value.time === 'string') &&
    Array.isArray(value.visible_entities) &&
    value.visible_entities.every(
      (entity) =>
        isRecord(entity) &&
        typeof entity.id === 'string' &&
        (entity.kind === 'npc' || entity.kind === 'object' || entity.kind === 'location') &&
        typeof entity.name === 'string' &&
        isStringArray(entity.aliases) &&
        typeof entity.description === 'string' &&
        Array.isArray(entity.observable_state) &&
        entity.observable_state.every(
          (field) =>
            isRecord(field) &&
            typeof field.key === 'string' &&
            typeof field.label === 'string' &&
            isJsonValue(field.value)
        )
    ) &&
    Array.isArray(value.visible_actors) &&
    value.visible_actors.every(
      (actor) =>
        isRecord(actor) &&
        typeof actor.id === 'string' &&
        typeof actor.name === 'string' &&
        (actor.occupation === undefined ||
          actor.occupation === null ||
          typeof actor.occupation === 'string') &&
        typeof actor.status_summary === 'string'
    ) &&
    Array.isArray(value.available_exits) &&
    value.available_exits.every(
      (exit) =>
        isRecord(exit) &&
        typeof exit.id === 'string' &&
        typeof exit.name === 'string' &&
        isStringArray(exit.aliases) &&
        typeof exit.description === 'string' &&
        (exit.destination === null ||
          (isRecord(exit.destination) &&
            typeof exit.destination.scene_id === 'string' &&
            typeof exit.destination.name === 'string'))
    )
  );
}

function isValidWorldState(value: unknown): boolean {
  // Optional so a server that predates the `world` block still yields a usable
  // view; the frontend treats a missing block as "no world facts yet".
  if (value === undefined) return true;
  if (!isRecord(value)) return false;
  return (
    // 玩家侧拿到措辞与天数；精确小时不再过网（#415 §阶段一）。
    typeof value.time_label === 'string' &&
    typeof value.day_index === 'number' &&
    typeof value.can_advance_time === 'boolean' &&
    typeof value.core_resolved === 'boolean' &&
    typeof value.ending_available === 'boolean' &&
    (value.ending_id === null || typeof value.ending_id === 'string')
  );
}

function isValidPlayerView(value: unknown): value is AgentPlayerView {
  if (!isRecord(value)) return false;
  const {
    room_id,
    player_id,
    actor_id,
    scene_id,
    phase,
    revision,
    self_actor,
    scene,
    world,
    known_information,
    checkpoint_options,
  } = value;
  return (
    typeof room_id === 'string' &&
    typeof player_id === 'string' &&
    typeof actor_id === 'string' &&
    typeof scene_id === 'string' &&
    (phase === 'playing' || phase === 'ended') &&
    typeof revision === 'string' &&
    isValidSelfActor(self_actor, actor_id) &&
    isValidScene(scene, scene_id) &&
    isValidWorldState(world) &&
    Array.isArray(known_information) &&
    known_information.every(
      (information) =>
        isRecord(information) &&
        typeof information.id === 'string' &&
        typeof information.title === 'string' &&
        typeof information.summary === 'string' &&
        typeof information.content === 'string' &&
        isStringArray(information.related_entities) &&
        isStringArray(information.related_scenes) &&
        (information.scope === 'actor' || information.scope === 'party')
    ) &&
    Array.isArray(checkpoint_options) &&
    checkpoint_options.every(
      (option) =>
        isRecord(option) &&
        typeof option.id === 'string' &&
        typeof option.target_id === 'string' &&
        typeof option.action_hint === 'string' &&
        isStringArray(option.skills) &&
        (option.difficulty === null ||
          option.difficulty === 'regular' ||
          option.difficulty === 'hard' ||
          option.difficulty === 'extreme')
    )
  );
}

export function isValidTurnCompleted(value: unknown): value is TurnCompletedEvent {
  if (!isRecord(value)) return false;
  const { protocol_version, message_type, correlation_id, payload } = value;
  if (
    protocol_version !== '1' ||
    message_type !== 'turn.completed' ||
    typeof correlation_id !== 'string' ||
    !correlation_id ||
    !isRecord(payload)
  ) {
    return false;
  }
  const { room_id, player_id, actor_id, narration, player_view } = payload;
  return (
    typeof room_id === 'string' &&
    typeof player_id === 'string' &&
    typeof actor_id === 'string' &&
    isRecord(narration) &&
    (narration.kind === 'narration' || narration.kind === 'clarification') &&
    typeof narration.text === 'string' &&
    isStringArray(narration.claimed_fact_ids) &&
    isStringArray(narration.suggested_actions) &&
    isValidPlayerView(player_view) &&
    player_view.room_id === room_id &&
    player_view.player_id === player_id &&
    player_view.actor_id === actor_id
  );
}

function isValidPlanProgress(p: Record<string, unknown>): boolean {
  return (
    typeof p.correlationId === 'string' &&
    typeof p.currentStep === 'number' &&
    Number.isInteger(p.currentStep) &&
    typeof p.completedSteps === 'number' &&
    Number.isInteger(p.completedSteps) &&
    typeof p.totalSteps === 'number' &&
    Number.isInteger(p.totalSteps) &&
    (p.phase === 'understanding' ||
      p.phase === 'executing' ||
      p.phase === 'waiting_for_player' ||
      p.phase === 'stopped' ||
      p.phase === 'completed')
  );
}

/**
 * 每个 S→C 事件各自的 payload 校验器。
 *
 * 写成以 `ServerToClientEvent['type']` 为键的映射类型（而不是一个事件名数组
 * 加一段公共校验），是为了让 TypeScript 强制约束这张表的完整性：往
 * ServerToClientEvent 联合里加一个新事件却忘了在这里加校验器，编译期就会报错。
 * 这张表同时也是"已知事件类型"的唯一来源，不需要另外维护一份事件名清单。
 *
 * 注意这里刻意只做逐字段的类型检查，不做取值范围/格式校验——目的是让下面的
 * 类型守卫名副其实，而不是复刻一套完整的 schema 校验。SDK 是零运行时依赖的，
 * 不会为此引入 ajv 之类的校验库（issue #75 决策 5）。事件数量涨上去之后
 * （骨架那期要加 13 个 S→C 事件），这张表更适合改成从 JSON Schema 生成。
 */
const PAYLOAD_VALIDATORS: {
  [K in ServerToClientEvent['type']]: (payload: Record<string, unknown>) => boolean;
} = {
  'session.bound': (p) => typeof p.roomId === 'string' && typeof p.playerId === 'string',
  'narration.push': (p) =>
    typeof p.text === 'string' &&
    (p.messageId === undefined ||
      p.messageId === null ||
      (typeof p.messageId === 'string' && p.messageId.length > 0)),
  'host_speech.settings_updated': (p) =>
    p.voiceType === null || typeof p.voiceType === 'string',
  // 片段只是 narration.push 的渐进展示形式，不是权威消息（issue #203）：
  // messageId 用来归组、sequence 用来排序去重，拼接结果必须等于最终 push 的
  // text。下游不得把拼接内容当成权威历史。
  'narration.chunk': (p) =>
    typeof p.messageId === 'string' &&
    p.messageId.length > 0 &&
    typeof p.sequence === 'number' &&
    Number.isInteger(p.sequence) &&
    p.sequence >= 0 &&
    typeof p.text === 'string',
  'opening.started': (p) =>
    typeof p.messageId === 'string' && p.messageId.length > 0,
  'turn.started': (p) => typeof p.correlationId === 'string',
  'turn.phase_changed': (p) =>
    typeof p.correlationId === 'string' &&
    (p.phase === 'reading_player_view' ||
      p.phase === 'understanding_action' ||
      p.phase === 'waiting_for_check' ||
      p.phase === 'executing_action' ||
      p.phase === 'refreshing_player_view' ||
      p.phase === 'generating_narration'),
  'tool.started': (p) =>
    typeof p.correlationId === 'string' &&
    typeof p.toolName === 'string' &&
    typeof p.publicProgressLabel === 'string',
  'tool.completed': (p) =>
    typeof p.correlationId === 'string' &&
    typeof p.toolName === 'string' &&
    (p.status === 'success' || p.status === 'error'),
  'turn.failed': (p) =>
    typeof p.correlationId === 'string' &&
    typeof p.code === 'string' &&
    typeof p.publicMessage === 'string' &&
    typeof p.retryable === 'boolean',
  'plan.started': isValidPlanProgress,
  'plan.step_changed': isValidPlanProgress,
  'plan.stopped': isValidPlanProgress,
  'plan.completed': isValidPlanProgress,
  'adjudication.pending': (p) =>
    typeof p.correlationId === 'string' &&
    (p.planId === undefined || p.planId === null || typeof p.planId === 'string') &&
    (p.status === 'awaiting_skill_choice' ||
      p.status === 'awaiting_post_roll_decision') &&
    (p.status !== 'awaiting_skill_choice' || isRecord(p.pendingDecision)) &&
    (p.status !== 'awaiting_post_roll_decision' || isRecord(p.checkRun)),
  'room.action.state': (p) => {
    if (
      (p.status !== 'idle' && p.status !== 'processing' && p.status !== 'awaiting_player') ||
      typeof p.revision !== 'string'
    ) return false;
    if (p.queued !== undefined) {
      if (!Array.isArray(p.queued)) return false;
      for (const item of p.queued) {
        if (
          !isRecord(item) ||
          typeof item.playerId !== 'string' ||
          typeof item.actorId !== 'string' ||
          typeof item.clientActionId !== 'string' ||
          !isRecord(item.recipient) ||
          (item.recipient.kind !== 'keeper' && item.recipient.kind !== 'npc') ||
          (item.recipient.kind === 'keeper' && item.recipient.entityId !== null) ||
          (item.recipient.kind === 'npc' &&
            (typeof item.recipient.entityId !== 'string' ||
              !item.recipient.entityId ||
              item.recipient.explicit !== true)) ||
          typeof item.recipient.explicit !== 'boolean' ||
          typeof item.position !== 'number' ||
          typeof item.utterance !== 'string' ||
          typeof item.acceptedAt !== 'string'
        ) return false;
      }
    }
    const owner = [p.playerId, p.actorId, p.clientActionId, p.startedAt];
    return p.status === 'idle'
      ? owner.every((value) => value === null || value === undefined)
      : owner.every((value) => typeof value === 'string' && value.length > 0);
  },
  'time.advance.pending': (p) =>
    typeof p.proposalId === 'string' &&
    typeof p.proposalVersion === 'number' &&
    Number.isInteger(p.proposalVersion) &&
    typeof p.sourceRevision === 'string' &&
    typeof p.targetLabel === 'string' &&
    typeof p.targetDayIndex === 'number' &&
    typeof p.requesterPlayerId === 'string' &&
    isStringArray(p.requiredPlayerIds) &&
    isStringArray(p.acceptedPlayerIds) &&
    typeof p.expiresAt === 'string',
  'time.advance.resolved': (p) =>
    typeof p.proposalId === 'string' &&
    (p.status === 'approved' ||
      p.status === 'rejected' ||
      p.status === 'expired' ||
      p.status === 'stale') &&
    typeof p.targetLabel === 'string' &&
    typeof p.targetDayIndex === 'number' &&
    (p.committedRevision === null ||
      p.committedRevision === undefined ||
      typeof p.committedRevision === 'string'),
  'scene.transition.pending': (p) =>
    typeof p.proposalId === 'string' &&
    typeof p.proposalVersion === 'number' &&
    Number.isInteger(p.proposalVersion) &&
    typeof p.sourceRevision === 'string' &&
    typeof p.sourceSceneId === 'string' &&
    typeof p.targetSceneId === 'string' &&
    typeof p.requesterPlayerId === 'string' &&
    isStringArray(p.requiredPlayerIds) &&
    isStringArray(p.acceptedPlayerIds) &&
    typeof p.expiresAt === 'string',
  'scene.transition.resolved': (p) =>
    typeof p.proposalId === 'string' &&
    (p.status === 'approved' ||
      p.status === 'rejected' ||
      p.status === 'expired' ||
      p.status === 'stale') &&
    typeof p.sourceSceneId === 'string' &&
    typeof p.targetSceneId === 'string' &&
    (p.committedRevision === null ||
      p.committedRevision === undefined ||
      typeof p.committedRevision === 'string'),
  'view.updated': (p) =>
    typeof p.playerId === 'string' &&
    isValidPlayerView(p.playerView) &&
    p.playerView.player_id === p.playerId,
  // issue #77 新增的 11 个 S→C 事件。只校验必填字段的类型（可空字段不校验）；
  // 嵌套对象（players/player）只做「是不是对象/数组」的浅检查，不深入逐字段。
  'room.state': (p) =>
    typeof p.roomId === 'string' && typeof p.phase === 'string' && Array.isArray(p.players),
  'player.joined': (p) => typeof p.player === 'object' && p.player !== null,
  'turn.begin': (p) => typeof p.playerId === 'string',
  'game.ended': () => true, // reason 可空，没有必填字段
  'view.private': (p) => typeof p.playerId === 'string' && typeof p.text === 'string',
  'check.request': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.clientActionId === 'string' &&
    typeof p.summary === 'string' &&
    typeof p.difficulty === 'string' &&
    Array.isArray(p.skills) &&
    p.skills.every(
      (skill) =>
        typeof skill === 'object' &&
        skill !== null &&
        typeof skill.id === 'string' &&
        typeof skill.name === 'string' &&
        typeof skill.targetValue === 'number',
    ),
  'check.result': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.clientActionId === 'string' &&
    typeof p.skill === 'string' &&
    typeof p.skillName === 'string' &&
    (typeof p.characterName === 'string' ||
      p.characterName === null ||
      p.characterName === undefined) &&
    typeof p.rollValue === 'number' &&
    typeof p.targetValue === 'number' &&
    typeof p.difficulty === 'string' &&
    typeof p.successLevel === 'string' &&
    typeof p.passed === 'boolean' &&
    typeof p.result === 'string',
  'chat.message': (p) =>
    typeof p.messageId === 'string' &&
    typeof p.playerId === 'string' &&
    typeof p.nickname === 'string' &&
    (p.channel === 'discussion' || p.channel === 'roleplay') &&
    (p.channel === 'discussion'
      ? (p.actorId === null || p.actorId === undefined) &&
        (p.actorName === null || p.actorName === undefined)
      : typeof p.actorId === 'string' &&
        p.actorId.length > 0 &&
        typeof p.actorName === 'string' &&
        p.actorName.length > 0) &&
    typeof p.text === 'string' &&
    typeof p.sentAt === 'string' &&
    typeof p.clientMessageId === 'string',
  'action.broadcast': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.clientActionId === 'string' &&
    typeof p.nickname === 'string' &&
    (typeof p.characterName === 'string' ||
      p.characterName === null ||
      p.characterName === undefined) &&
    typeof p.utterance === 'string',
  'dialogue.player': (p) =>
    typeof p.messageId === 'string' &&
    typeof p.playerId === 'string' &&
    typeof p.clientActionId === 'string' &&
    typeof p.speakerId === 'string' &&
    typeof p.interlocutorId === 'string' &&
    typeof p.interlocutorName === 'string' &&
    typeof p.utterance === 'string' &&
    typeof p.sceneId === 'string' &&
    isStringArray(p.audiencePlayerIds),
  'dialogue.npc': (p) =>
    typeof p.messageId === 'string' &&
    typeof p.speakerId === 'string' &&
    typeof p.speakerName === 'string' &&
    typeof p.text === 'string' &&
    typeof p.sceneId === 'string' &&
    typeof p.sourceDialogueId === 'string' &&
    typeof p.sourceActionId === 'string' &&
    typeof p.ordinal === 'number' &&
    Number.isInteger(p.ordinal) &&
    isStringArray(p.audiencePlayerIds),
  'san.check.request': (p) => typeof p.playerId === 'string',
  'san.check.result': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.rollValue === 'number' &&
    typeof p.sanLoss === 'number' &&
    typeof p.result === 'string',
  'clue.granted': (p) => typeof p.playerId === 'string' && typeof p.clueName === 'string',
  error: (p) => typeof p.code === 'string' && typeof p.message === 'string',
};

/**
 * 运行时校验服务端推来的消息是不是一个合法的 `ServerToClientEvent`。
 *
 * 校验三层：信封形状（是对象、有 `type`/`payload`）→ `type` 是已知判别值 →
 * 该判别值对应的 payload 字段类型正确。第三层是必须的：这个函数向 TypeScript
 * 断言了 `value is ServerToClientEvent`，如果只校验信封就返回 true，
 * `{ type: 'narration.push', payload: {} }` 会被当成合法事件下发，下游
 * 读到的 `payload.text` 是 `undefined`，而类型系统还以为它是 string——
 * 等于用类型守卫的形式对编译器撒谎（PR #76 review 指出）。
 *
 * 导出（而不是模块私有）是为了能在 room-socket.test.ts 里直接单元测试，
 * 不用为了测这段校验逻辑真的起一个 WebSocket 连接。
 */
export function isValidServerEvent(value: unknown): value is ServerToClientEvent {
  if (typeof value !== 'object' || value === null) return false;
  const { type, payload } = value as { type?: unknown; payload?: unknown };
  if (typeof type !== 'string' || !(type in PAYLOAD_VALIDATORS)) return false;
  if (typeof payload !== 'object' || payload === null) return false;
  const validate = PAYLOAD_VALIDATORS[type as ServerToClientEvent['type']];
  return validate(payload as Record<string, unknown>);
}

/**
 * `/ws/{roomId}` 的类型化封装（issue #60）。这条通道是独立于 REST API
 * 版本号的实时通道，不走 ApiClient 的 HTTP/`{success,data,error}` 信封，
 * 客户端发送 `{type, playerId, payload}`；常规服务端事件使用
 * `{type, payload}`，动作完成使用 Agent framework 的 `WebSocketOutput`。
 *
 * 单例连接：同一个 roomId 重复调用 connect() 会复用已有（或正在建立中的）
 * 连接，页面切换时不需要关心是否已经连过——跟原型里"房间级单例连接"的
 * 设计保持一致。
 */
export class RoomSocket {
  private ws: WebSocket | null = null;
  private roomId: string | null = null;
  private readonly handlers = new Set<RoomSocketHandler>();
  private readonly pendingActions = new Map<string, PendingAction>();
  private playerView: AgentPlayerView | null = null;
  private openingMessageId: string | null = null;

  // --- 断线恢复所需的状态（issue #505）---
  /** 最近一次 connect() 的参数，重连时原样复用。 */
  private connectArgs: { roomId: string; token: string } | null = null;
  /** 最近一次 room.join 的参数：重连后必须重新绑定，否则服务端不认这条连接。 */
  private lastJoin: { playerId: string; payload: RoomJoinPayload } | null = null;
  /** 本次连接是重连产生的，onopen 后需要自动补一次 room.join。 */
  private pendingRejoin = false;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private connectionState: RoomSocketConnectionState = 'disconnected';
  private readonly connectionHandlers = new Set<RoomSocketConnectionHandler>();

  constructor(private readonly wsBaseUrl: string) {}

  /** 建立（或复用）到 roomId 的连接。token 是账号登录会话（issue #58），
   * 不是房间的 X-Reconnect-Token——两者是独立的身份体系。 */
  connect(roomId: string, token: string): WebSocket {
    if (
      this.ws &&
      this.roomId === roomId &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return this.ws;
    }
    const previousSocket = this.ws;
    this.ws = null;
    this.rejectPendingActions(new RoomSocketTransportError('WebSocket connection replaced'));
    this.clearTimers();
    // 主动替换不会触发重连：下面 onclose 里的 `this.ws !== socket` 守卫会让旧
    // socket 的关闭事件直接返回。disconnect() 同理（它先把 this.ws 置空）。
    previousSocket?.close();

    this.connectArgs = { roomId, token };
    this.reconnectAttempts = 0;
    this.setConnectionState('connecting');
    this.roomId = roomId;
    this.playerView = null;
    this.openingMessageId = null;
    const url = `${this.wsBaseUrl}/ws/${roomId}?token=${encodeURIComponent(token)}`;
    const socket = new WebSocket(url);
    socket.onmessage = (event) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        console.warn('[RoomSocket] received malformed JSON, dropped', event.data);
        return;
      }
      // 心跳应答（issue #505）。放在事件校验之前：pong 不是房间事件，不进
      // ServerToClientEvent 联合类型，也不需要分发给订阅者。
      if (typeof (parsed as { type?: unknown }).type === 'string'
        && (parsed as { type: string }).type === 'pong') {
        this.clearPongTimer();
        return;
      }
      if (isValidTurnCompleted(parsed)) {
        this.playerView = parsed.payload.player_view;
        const pending = this.pendingActions.get(parsed.correlation_id);
        if (!pending) {
          // 这条事件不进 ServerToClientEvent 联合类型，前端也刻意不从它渲染
          // 叙事（叙事只认 narration.push），所以这里没有可分发的下游——保持
          // 丢弃，但它是连接已经断过的可靠信号：断线期间服务端的
          // narration.push / view.updated 同样投递失败了，界面此刻是陈旧的。
          // 真正的恢复由重连后的状态重拉负责（见 scheduleReconnect）。
          console.warn(
            '[RoomSocket] received turn.completed without matching action, dropped',
            parsed,
          );
          return;
        }
        this.pendingActions.delete(parsed.correlation_id);
        pending.resolve(parsed.payload);
        return;
      }
      // 校验不过就丢弃 + warn，不 throw、不断开连接——一条格式不对的消息
      // 不应该让整局游戏的连接挂掉（issue #75 决策 5）。之前这里直接把
      // JSON.parse 的结果断言成 ServerToClientEvent，服务端推来的形状对不上
      // 时会悄无声息地把错误数据当合法事件发给所有订阅者。
      if (!isValidServerEvent(parsed)) {
        console.warn('[RoomSocket] received event with unknown type or invalid shape, dropped', parsed);
        return;
      }
      if (parsed.type === 'error' && parsed.payload.correlationId) {
        const pending = this.pendingActions.get(parsed.payload.correlationId);
        if (pending) {
          this.pendingActions.delete(parsed.payload.correlationId);
          pending.reject(
            new RoomSocketServerError(
              parsed.payload.message,
              parsed.payload.code,
              parsed.payload.correlationId,
            ),
          );
        }
      }
      if (parsed.type === 'turn.failed') {
        const pending = this.pendingActions.get(parsed.payload.correlationId);
        if (pending) {
          this.pendingActions.delete(parsed.payload.correlationId);
          pending.reject(
            new TurnFailedError(
              parsed.payload.publicMessage,
              parsed.payload.code,
              parsed.payload.retryable,
              parsed.payload.correlationId,
            )
          );
        }
      }
      if (parsed.type === 'view.updated') {
        this.playerView = parsed.payload.playerView;
      }
      if (parsed.type === 'opening.started') {
        this.openingMessageId = parsed.payload.messageId;
      } else if (
        parsed.type === 'narration.push' &&
        parsed.payload.messageId === this.openingMessageId
      ) {
        this.openingMessageId = null;
      } else if (parsed.type === 'error') {
        this.openingMessageId = null;
      }
      this.handlers.forEach((handler) => handler(parsed));
    };
    socket.onopen = () => {
      if (this.ws !== socket) return;
      this.reconnectAttempts = 0;
      this.setConnectionState('open');
      this.startHeartbeat();
      // 重连出来的连接要自己补一次 room.join：服务端按连接登记房间成员，不重新
      // 绑定就收不到任何广播。放在 onopen 里而不是挂在 waitForOpen 的 then 上，
      // 是为了不依赖 promise 微任务时序——socket 建立时就已经 OPEN 的实现里，
      // 那个 then 会晚于调用方的后续逻辑执行。
      if (this.pendingRejoin) {
        this.pendingRejoin = false;
        const join = this.lastJoin;
        if (join) this.send('room.join', join.playerId, join.payload);
      }
    };
    socket.onclose = () => {
      if (this.ws !== socket) return;
      this.ws = null;
      this.roomId = null;
      this.openingMessageId = null;
      this.clearTimers();
      this.rejectPendingActions(new RoomSocketTransportError('WebSocket connection closed'));
      // 走到这里说明不是调用方主动断开（那两条路径会先把 this.ws 置空/换掉，
      // 上面的守卫就已经返回了），所以是掉线，需要自动恢复（issue #505）。
      this.scheduleReconnect();
    };
    this.ws = socket;
    return socket;
  }

  /** 等到连接真正 OPEN 再发第一条 room.join——避免在 CONNECTING 状态下调用 send() 报错。 */
  waitForOpen(socket: WebSocket): Promise<void> {
    if (socket.readyState === WebSocket.OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      let settled = false;
      const succeed = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      const fail = (error: RoomSocketTransportError) => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      socket.addEventListener('open', succeed, { once: true });
      // 原来这里直接用 WebSocket 的 Event 对象 reject——不是 Error，下游写
      // `.catch(e => e.message)` 只会拿到 undefined。改成传一个真正的
      // Error，原始 Event 保留在 cause 里给需要排查细节的调用方用。
      socket.addEventListener(
        'error',
        (event) => fail(new RoomSocketTransportError('WebSocket connection failed', event)),
        { once: true }
      );
      socket.addEventListener(
        'close',
        (event) => fail(new RoomSocketTransportError('WebSocket closed before opening', event)),
        { once: true }
      );
    });
  }

  /** 订阅服务端推送事件，返回取消订阅函数。多个页面/组件可以各自订阅、
   * 各自 unsubscribe，不影响底层连接本身（连接跨页面保持，见 connect）。 */
  onMessage(handler: RoomSocketHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  joinRoom(playerId: string, payload: RoomJoinPayload): void {
    // 记下来给重连用：新连接必须重新 room.join 才会被服务端登记进房间，
    // 否则它收不到任何广播（issue #505）。
    this.lastJoin = { playerId, payload };
    this.send('room.join', playerId, payload);
  }

  /**
   * 订阅连接状态变化（issue #505）。断线与重连必须对玩家可见——旧实现连接
   * 断了以后既不重连也不提示，界面停在"处理中"，用户只能猜要不要刷新。
   */
  onConnectionChange(handler: RoomSocketConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    handler(this.connectionState);
    return () => this.connectionHandlers.delete(handler);
  }

  setReady(playerId: string, payload: PlayerReadyPayload): boolean {
    return this.send('player.ready', playerId, payload);
  }

  startGame(playerId: string): void {
    this.send('game.start', playerId, {});
  }

  /** Submit through the finite ActionPlan production path (issue #225). */
  submitPlannedAction(
    playerId: string,
    payload: ActionSubmitPayload,
  ): Promise<AgentTurnPayload> {
    const existing = this.pendingActions.get(payload.clientActionId);
    if (existing) {
      this.send('action.plan.submit', playerId, payload);
      return existing.promise;
    }
    let resolve!: (result: AgentTurnPayload) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<AgentTurnPayload>((resolveAction, rejectAction) => {
      resolve = resolveAction;
      reject = rejectAction;
    });
    this.pendingActions.set(payload.clientActionId, { promise, resolve, reject });
    if (!this.send('action.plan.submit', playerId, payload)) {
      this.pendingActions.delete(payload.clientActionId);
      reject(new RoomSocketTransportError('WebSocket is not connected'));
    }
    return promise;
  }

  /** NPC 对话不产生 Agent turn.completed；回复通过 dialogue.* 事件到达。 */
  submitNpcDialogue(playerId: string, payload: ActionSubmitPayload): boolean {
    if (payload.recipient.kind !== 'npc') return false;
    return this.send('action.plan.submit', playerId, payload);
  }

  selectAdjudication(playerId: string, payload: AdjudicationChoicePayload): void {
    this.send('adjudication.select', playerId, payload);
  }

  decidePostRoll(playerId: string, payload: AdjudicationPostRollPayload): void {
    this.send('adjudication.post_roll', playerId, payload);
  }

  /** 回复多人共享时间提案；重试时必须复用服务端最新版本。 */
  respondToTimeAdvance(playerId: string, payload: TimeAdvanceRespondPayload): void {
    this.send('time.advance.respond', playerId, payload);
  }

  /** 回复多人共享场景切换提案；重试时必须复用服务端最新版本。 */
  respondToSceneTransition(playerId: string, payload: SceneTransitionRespondPayload): void {
    this.send('scene.transition.respond', playerId, payload);
  }

  cancelActionPlan(playerId: string, payload: ActionPlanCancelPayload): void {
    this.send('action.plan.cancel', playerId, payload);
  }

  getPlayerView(): AgentPlayerView | null {
    return this.playerView;
  }

  /** Return a transient opening progress marker even if it arrived before UI subscription. */
  getOpeningMessageId(): string | null {
    return this.openingMessageId;
  }

  /** check.roll —— 为当前 check.request 提交玩家选择的技能和 D100 点数。 */
  rollCheck(playerId: string, payload: CheckRollPayload): void {
    this.send('check.roll', playerId, payload);
  }

  /** chat.send —— 发送讨论区消息；不会进入 Host Agent 上下文。 */
  sendChat(playerId: string, payload: ChatSendPayload): void {
    this.send('chat.send', playerId, payload);
  }

  /** action.chat.send —— 行动区普通消息，广播原话但不进入主持主链。 */
  sendActionChat(playerId: string, payload: ChatSendPayload): void {
    this.send('action.chat.send', playerId, payload);
  }

  /** san.check.roll —— 理智检定摇骰（issue #77 新增，后端本期回 NOT_IMPLEMENTED）。 */
  rollSanCheck(playerId: string, payload: SanCheckRollPayload): void {
    this.send('san.check.roll', playerId, payload);
  }

  /** room.rejoin —— 断线重连（issue #77 仅铺协议，后端本期回 NOT_IMPLEMENTED）。 */
  rejoin(playerId: string, payload: RoomRejoinPayload): void {
    this.send('room.rejoin', playerId, payload);
  }

  disconnect(): void {
    const socket = this.ws;
    this.ws = null;
    this.roomId = null;
    this.openingMessageId = null;
    // 主动断开：清掉重连意图，否则下面的 close 会被 onclose 当成掉线重连回来。
    this.connectArgs = null;
    this.lastJoin = null;
    this.clearTimers();
    this.rejectPendingActions(new RoomSocketTransportError('WebSocket disconnected'));
    socket?.close();
    this.setConnectionState('disconnected');
  }

  /**
   * 心跳（issue #505）。固定间隔发一帧 ping 并等 pong；超时就主动把连接关掉，
   * 交给 onclose 走重连，而不是干等 TCP 自己发现——预览链路上网关是静默切断
   * 的，两端谁都收不到 FIN，不主动探测就永远发现不了。
   */
  private startHeartbeat(): void {
    this.clearHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      const socket = this.ws;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      // 上一轮 ping 还没等到 pong 就不再叠加，等它自己超时。
      if (this.pongTimer !== null) return;
      try {
        socket.send(JSON.stringify({ type: 'ping', payload: {} }));
      } catch {
        // 发不出去本身就说明链路已经不可用，直接按超时处理。
        this.failHeartbeat();
        return;
      }
      this.pongTimer = setTimeout(() => this.failHeartbeat(), HEARTBEAT_TIMEOUT_MS);
    }, HEARTBEAT_INTERVAL_MS);
  }

  /** ping 没等到 pong：判定链路已死，关闭当前连接触发重连。 */
  private failHeartbeat(): void {
    this.clearPongTimer();
    const socket = this.ws;
    if (!socket) return;
    console.warn('[RoomSocket] 心跳超时，判定连接已失效，准备重连');
    // 不置空 this.ws——要让 onclose 的守卫通过，从而走进重连路径。
    socket.close();
  }

  /**
   * 断线重连（issue #505）。指数退避 + 封顶；重连成功后由 onopen 重置计数，
   * 并在这里重新发一次 room.join——服务端按连接登记房间成员，不重新绑定的话
   * 新连接收不到任何广播。
   */
  private scheduleReconnect(): void {
    const args = this.connectArgs;
    if (!args || this.reconnectTimer !== null) return;
    // 没有 room.join 过的连接不重连：它没有任何房间状态需要恢复，重连也只是
    // 建一条谁都不认识的连接。调用方总是 connect() 之后立刻 joinRoom()。
    if (!this.lastJoin) return;
    // 重连不能无限打下去。服务端真的下线时，无节制的重连会一直占着定时器、
    // 反复发起网络请求，而界面其实早就该告诉玩家"连不上了"。到顶之后停在
    // disconnected，由调用方决定要不要再 connect()。
    if (this.reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
      console.warn('[RoomSocket] 重连次数已达上限，停止自动重连');
      this.setConnectionState('disconnected');
      return;
    }
    this.setConnectionState('reconnecting');
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempts,
      RECONNECT_MAX_DELAY_MS,
    );
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      // connect() 会重置 reconnectAttempts，这里先存一份重连计数再调用它，
      // 避免退避被自己的成功路径清零后又立刻从头开始。
      const attempts = this.reconnectAttempts;
      this.pendingRejoin = true;
      this.connect(args.roomId, args.token);
      this.reconnectAttempts = attempts;
    }, delay);
  }

  private setConnectionState(state: RoomSocketConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.connectionHandlers.forEach((handler) => handler(state));
  }

  private clearPongTimer(): void {
    if (this.pongTimer !== null) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearPongTimer();
  }

  private clearTimers(): void {
    this.clearHeartbeat();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private send(type: string, playerId: string, payload: unknown): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn(`[RoomSocket] not connected, dropped: ${type}`, payload);
      return false;
    }
    try {
      this.ws.send(JSON.stringify({ type, playerId, payload }));
    } catch (error) {
      console.warn(`[RoomSocket] send failed, dropped: ${type}`, error);
      return false;
    }
    return true;
  }

  private rejectPendingActions(error: RoomSocketTransportError): void {
    for (const pending of this.pendingActions.values()) {
      pending.reject(error);
    }
    this.pendingActions.clear();
  }
}
