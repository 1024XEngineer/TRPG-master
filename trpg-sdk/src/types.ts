// ──────────────────────────────────────────────
// 与后端 DTO 一一对应的类型：全部 re-export 自 generated/dto.ts
// （issue #75 —— 由 `npm run codegen` 从 trpg-backend/app/dto/*.py 的 pydantic
// 模型生成，不再手写，也不再需要手动跟后端保持同步）。
//
// re-export 时按原有的公开类型名做了别名（比如后端类名 RoomCreate 对应这里的
// CreateRoomInput）：一是保持 trpg-sdk 现有的公开 API 不变，
// resources/*.ts、trpg-frontend 都不需要跟着改名；二是后端类名和 SDK 里
// 已经用惯的名字本来就不总是一样（后端偏"动词+Body/Read/Result"，SDK 偏
// "动词+Input/Result"），生成产物忠实反映后端类名，这一层负责做名字翻译。
// ──────────────────────────────────────────────

import type {
  AdjudicationPendingPayload,
  ErrorDetail,
  HostSpeechSettingsUpdatedPayload,
  MyRoomSummary as GeneratedMyRoomSummary,
  PlanProgressPayload,
  RoomActionStatePayload,
  SceneTransitionPendingPayload,
  SceneTransitionResolvedPayload,
  TimeAdvancePendingPayload,
  TimeAdvanceResolvedPayload,
} from './generated/dto';

export type {
  ErrorDetail,
  // 认证（Auth）模块 —— 对应后端 dto/auth.py
  RegisterBody as RegisterInput,
  LoginBody as LoginInput,
  UpdateNicknameBody as UpdateNicknameInput,
  AuthResult,
  MeRead as Me,
  // 房间（Room）模块 —— 对应后端 dto/room.py
  RoomCreate as CreateRoomInput,
  RoomCreateResult as CreateRoomResult,
  ModuleRead as ModuleSummary,
  SelectModuleBody as SelectModuleInput,
  JoinRoomBody as JoinRoomInput,
  RoomPlayerRead as RoomPlayerSummary,
  RoomPreview,
  // 角色建卡（Character）模块 —— 对应后端 dto/character.py
  EquipmentItem as CharacterEquipmentItem,
  CharacterUpdateBody as UpdateCharacterInput,
  CharacterDraftResult,
  QuickGenerateRequest as QuickGenerateInput,
  QuickGenerateResult,
  RollAttributesResult,
  RollLuckResult,
  // 我的卡库（issue #77 决策 5）—— 对应后端 dto/character.py
  CharacterTemplateCreateBody as SaveCharacterTemplateInput,
  CharacterTemplateRead as CharacterTemplate,
  CharacterTemplateUpdateBody as UpdateCharacterTemplateInput,
  SystemQuickGenerateResult as SystemQuickGenerateOutput,
  // 建卡计算/校验预览（issue #84 S2）—— 对应后端 dto/character.py
  CharacterPreviewRequest as PreviewCharacterInput,
  CharacterComputeResult,
  SkillPointsBudgetView,
  SkillComputeView,
  ValidationIssueView,
  // 建卡完成后的可选角色生图（issue #199）
  PortraitGenerationRequest as GeneratePortraitInput,
  PortraitGenerationTaskRead,
  // 游戏目录 / 规则数据（issue #77）—— 对应后端 dto/game.py
  GameRead as Game,
  GameSystemRead as GameSystem,
  CharacterRead as Character,
  RulesetRead as Ruleset,
  // 模组详情 / 导入（issue #77）—— 对应后端 dto/module.py
  ModuleDetailRead as ModuleDetail,
  ModuleImportRequestBody as ImportModuleInput,
  ModuleImportJobRead as ModuleImportJob,
  // 复盘 / 回放（issue #77）—— 对应后端 dto/replay.py
  RoomSummaryRead as RoomSummary,
  ReplayEventRead as ReplayEvent,
  RoomConversationEventRead as RoomConversationEvent,
  // WebSocket 现有 6 个事件（issue #60）—— 对应后端 dto/ws.py
  RoomJoinPayload,
  PlayerReadyPayload,
  ActionSubmitPayload,
  ActionPlanCancelPayload,
  AdjudicationChoicePayload,
  AdjudicationPendingPayload,
  AdjudicationPostRollPayload,
  ActionBroadcastPayload,
  DialoguePlayerPayload,
  DialogueNpcPayload,
  GameStartPayload,
  SessionBoundPayload,
  NarrationPushPayload,
  NarrationChunkPayload,
  OpeningStartedPayload,
  PlanProgressPayload,
  RoomActionStatePayload,
  TimeAdvanceRespondPayload,
  TimeAdvancePendingPayload,
  TimeAdvanceResolvedPayload,
  SceneTransitionRespondPayload,
  SceneTransitionPendingPayload,
  SceneTransitionResolvedPayload,
  // WebSocket 新增 14 个事件（issue #77）
  CheckRollPayload,
  SanCheckRollPayload,
  RoomRejoinPayload,
  RoomStatePayload,
  PlayerJoinedPayload,
  TurnBeginPayload,
  GameEndedPayload,
  ViewPrivatePayload,
  CheckRequestPayload,
  CheckResultPayload,
  ChatMessagePayload,
  ChatMessageRead as ChatMessage,
  ChatSendPayload,
  SanCheckRequestPayload,
  SanCheckResultPayload,
  ClueGrantedPayload,
  ErrorPayload,
  HostSpeechVoiceRead,
  HostSpeechSettingsRead as HostSpeechSettings,
  HostSpeechSettingsUpdate,
  HostSpeechSentenceRead,
  HostSpeechManifestRead as HostSpeechManifest,
  HostSpeechSettingsUpdatedPayload,
  CreateInventoryImportDraftRequest,
  InventoryImportDraft,
  ConfirmInventoryImportDraftRequest,
  ConfirmInventoryImportResult,
  ChangeItemCustodyRequest,
  ChangeItemCustodyResult,
  InventoryView,
  CreateEndingDraftRequest,
  EndingDraft,
  ConfirmEndingDraftRequest,
  ConfirmEndingDraftResult,
} from './generated/dto';

/** GET /api/v1/me/rooms 返回项。 */
export type MyRoomSummary = GeneratedMyRoomSummary;

// ──────────────────────────────────────────────
// SDK 自有类型 —— 不对应任何单一后端 DTO，继续手写（issue #75 决策 2）
// ──────────────────────────────────────────────

/**
 * 对应后端 ApiResponse[T]：全项目统一的响应信封形状。
 *
 * 没有生成：`T` 是 pydantic 的泛型类型参数，JSON Schema 没有办法忠实表达
 * TS 泛型——导出出来的只会是某个具体 T 实例化后的样子，没法当成一个可复用
 * 的泛型包装类型。这跟 TrpgSdkOptions/ApiError 一样，属于 SDK 自己的基础
 * 设施类型，不是"后端 DTO 的镜像"。
 */
export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ErrorDetail | null;
}

// ──────────────────────────────────────────────
// WebSocket（issue #60）—— 与后端 app/controller/ws.py 保持一致
// 连接地址 `{wsBaseUrl}/ws/{roomId}?token=`，不走 ApiResponse 信封。
// ──────────────────────────────────────────────

import type {
  ActionBroadcastPayload,
  ChatMessagePayload,
  CheckRequestPayload,
  CheckResultPayload,
  ClueGrantedPayload,
  DialogueNpcPayload,
  DialoguePlayerPayload,
  ErrorPayload,
  GameEndedPayload,
  NarrationChunkPayload,
  NarrationPushPayload,
  OpeningStartedPayload,
  PlayerJoinedPayload,
  RoomStatePayload,
  SanCheckRequestPayload,
  SanCheckResultPayload,
  SessionBoundPayload,
  TurnBeginPayload,
  ViewPrivatePayload,
} from './generated/dto';

/**
 * 服务端推送的事件信封：`{type, payload}`。
 *
 * 没有生成：后端 dto/ws.py 只对 payload 建模，没有给"信封 + type 判别字段"
 * 建对应的 pydantic 模型（type 是纯字符串字面量，一个信封模型没法表达
 * "payload 形状取决于 type"这种判别关系，见 dto/ws.py 顶部说明）。这个
 * 联合类型手写组合生成出来的 payload 类型，`type` 判别字段的字面量值需要跟
 * ws.py 里实际发送的字符串手动保持一致；新增 S→C 事件时，这里、room-socket.ts
 * 的 PAYLOAD_VALIDATORS、后端 ws.py 三处要一起加（PAYLOAD_VALIDATORS 那张
 * 映射表漏加会编译期报错，见 room-socket.ts）。
 *
 * issue #77 新增的 11 个 S→C 事件里，除 error 外本期都不会真的被后端发出
 * （协议槽位预留，见 issue"三处原型取舍"），但类型/校验器先铺好。
 */
export type ServerToClientEvent =
  | { type: 'session.bound'; payload: SessionBoundPayload }
  | { type: 'narration.push'; payload: NarrationPushPayload }
  | { type: 'narration.chunk'; payload: NarrationChunkPayload }
  | { type: 'opening.started'; payload: OpeningStartedPayload }
  | { type: 'turn.started'; payload: TurnStartedPayload }
  | { type: 'turn.phase_changed'; payload: TurnPhaseChangedPayload }
  | { type: 'tool.started'; payload: ToolStartedPayload }
  | { type: 'tool.completed'; payload: ToolCompletedPayload }
  | { type: 'turn.failed'; payload: TurnFailedPayload }
  | { type: 'plan.started'; payload: PlanProgressPayload }
  | { type: 'plan.step_changed'; payload: PlanProgressPayload }
  | { type: 'plan.stopped'; payload: PlanProgressPayload }
  | { type: 'plan.completed'; payload: PlanProgressPayload }
  | { type: 'adjudication.pending'; payload: AdjudicationPendingPayload }
  | { type: 'room.action.state'; payload: RoomActionStatePayload }
  | { type: 'time.advance.pending'; payload: TimeAdvancePendingPayload }
  | { type: 'time.advance.resolved'; payload: TimeAdvanceResolvedPayload }
  | { type: 'scene.transition.pending'; payload: SceneTransitionPendingPayload }
  | { type: 'scene.transition.resolved'; payload: SceneTransitionResolvedPayload }
  | { type: 'view.updated'; payload: ViewUpdatedPayload }
  | { type: 'room.state'; payload: RoomStatePayload }
  | { type: 'player.joined'; payload: PlayerJoinedPayload }
  | { type: 'turn.begin'; payload: TurnBeginPayload }
  | { type: 'game.ended'; payload: GameEndedPayload }
  | { type: 'view.private'; payload: ViewPrivatePayload }
  | { type: 'check.request'; payload: CheckRequestPayload }
  | { type: 'check.result'; payload: CheckResultPayload }
  | { type: 'chat.message'; payload: ChatMessagePayload }
  | { type: 'action.broadcast'; payload: ActionBroadcastPayload }
  | { type: 'dialogue.player'; payload: DialoguePlayerPayload }
  | { type: 'dialogue.npc'; payload: DialogueNpcPayload }
  | { type: 'host_speech.settings_updated'; payload: HostSpeechSettingsUpdatedPayload }
  | { type: 'san.check.request'; payload: SanCheckRequestPayload }
  | { type: 'san.check.result'; payload: SanCheckResultPayload }
  | { type: 'clue.granted'; payload: ClueGrantedPayload }
  | { type: 'error'; payload: ErrorPayload };

export type AgentTurnPhase =
  | 'reading_player_view'
  | 'understanding_action'
  | 'waiting_for_check'
  | 'executing_action'
  | 'refreshing_player_view'
  | 'generating_narration';

export interface TurnStartedPayload {
  correlationId: string;
}

export interface TurnPhaseChangedPayload {
  correlationId: string;
  phase: AgentTurnPhase;
}

export interface ToolStartedPayload {
  correlationId: string;
  toolName: string;
  publicProgressLabel: string;
}

export interface ToolCompletedPayload {
  correlationId: string;
  toolName: string;
  status: 'success' | 'error';
}

export interface TurnFailedPayload {
  correlationId: string;
  code: string;
  publicMessage: string;
  retryable: boolean;
}

export interface ViewUpdatedPayload {
  playerId: string;
  playerView: AgentPlayerView;
}

// Agent framework 的回合结果使用独立信封，不套 `{type, payload}`。字段名按
// framework 的稳定 JSON Schema 保持 snake_case，避免 SDK 私自改写协议。
export type AgentJsonValue =
  | null
  | boolean
  | number
  | string
  | AgentJsonValue[]
  | { [key: string]: AgentJsonValue };

export interface AgentActorValue {
  id: string;
  name: string;
  value: number;
}

export interface AgentActorResource {
  id: string;
  name: string;
  value: number;
}

export interface AgentSelfActor {
  id: string;
  name: string;
  occupation: string | null;
  attributes: AgentActorValue[];
  skills: AgentActorValue[];
  resources: AgentActorResource[];
  conditions: string[];
  equipment: string[];
  background_summary: string;
  public_status_summary?: string;
}

export interface AgentObservableState {
  key: string;
  label: string;
  value: AgentJsonValue;
}

export interface AgentVisibleEntity {
  id: string;
  kind: 'npc' | 'object' | 'location';
  name: string;
  aliases: string[];
  description: string;
  observable_state: AgentObservableState[];
}

export interface AgentVisibleActor {
  id: string;
  name: string;
  occupation?: string | null;
  status_summary: string;
}

export interface AgentExitDestination {
  scene_id: string;
  name: string;
}

export interface AgentAvailableExit {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  destination: AgentExitDestination | null;
}

export interface AgentSceneView {
  id: string;
  name: string;
  description: string;
  time: string | null;
  visible_entities: AgentVisibleEntity[];
  visible_actors: AgentVisibleActor[];
  available_exits: AgentAvailableExit[];
  loose_items?: AgentInventoryItem[];
}

export interface AgentInventoryItem {
  id: string;
  name: string;
  source_label: string;
  quantity: number;
  condition: string;
  version: number;
}

export interface AgentKnownInformation {
  id: string;
  title: string;
  summary: string;
  content: string;
  related_entities: string[];
  related_scenes: string[];
  scope: 'actor' | 'party';
}

export interface AgentWorldState {
  /** 离散世界时间（#245）：时间只在授权的时间点之间跳转，不按分钟流逝。 */
  day_index: number;
  hour_of_day: number;
  time_of_day: 'day' | 'night';
  core_resolved: boolean;
  ending_available: boolean;
  ending_id: string | null;
}

export interface AgentKnownLocation {
  id: string;
  kind: 'region' | 'site' | 'room' | 'connector';
  name: string;
  description: string;
  parent_location_id: string | null;
  region_id: string | null;
  existence: 'rumored' | 'known';
  localization: 'unknown' | 'approximate' | 'located';
  access: 'unknown' | 'reachable' | 'blocked';
  visited: boolean;
}

export interface AgentLocationContext {
  current_location_id: string;
  breadcrumbs: Array<{ id: string; name: string }>;
  position_context: {
    kind: 'access_boundary';
    id: string;
    label: string;
    state: 'locked' | 'blocked' | 'interaction_required';
    destination_id: string;
  } | null;
}

export interface AgentCheckpointOption {
  id: string;
  target_id: string;
  action_hint: string;
  skills: string[];
  difficulty: 'regular' | 'hard' | 'extreme' | null;
}

export interface AgentPlayerView {
  room_id: string;
  player_id: string;
  actor_id: string;
  scene_id: string;
  phase: 'playing' | 'ended';
  revision: string;
  self_actor: AgentSelfActor;
  scene: AgentSceneView;
  /** v3-only safe hierarchy and boundary context; absent on historical payloads. */
  location_context?: AgentLocationContext | null;
  /** All player-known locations, not merely the current node's one-hop exits. */
  known_locations?: AgentKnownLocation[];
  /** Runtime ItemInstances currently held by this actor. */
  inventory?: AgentInventoryItem[];
  world: AgentWorldState;
  known_information: AgentKnownInformation[];
  checkpoint_options: AgentCheckpointOption[];
}

export interface AgentNarration {
  kind: 'narration' | 'clarification';
  text: string;
  claimed_fact_ids: string[];
  suggested_actions: string[];
}

export interface AgentTurnPayload {
  room_id: string;
  player_id: string;
  actor_id: string;
  narration: AgentNarration;
  player_view: AgentPlayerView;
}

export interface TurnCompletedEvent {
  protocol_version: '1';
  message_type: 'turn.completed';
  correlation_id: string;
  payload: AgentTurnPayload;
}
