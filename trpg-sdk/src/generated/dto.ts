/**
 * 本文件由 `npm run codegen` 从后端 pydantic 模型自动生成，请勿手改。
 *
 * 源头：trpg-backend/app/dto/ 下由 export_schema.py 登记的 DTO（含 host_speech.py）
 * 重新生成：
 *   1. cd trpg-backend && uv run python scripts/export_schema.py
 *   2. cd trpg-sdk && npm run codegen
 * 生成后把这个文件的改动一并提交——CI 会重新跑一遍上面两步，用 git diff
 * 校验有没有人改了后端 DTO 却忘记重新生成（issue #75 决策 3）。
 */

export interface AcceptResultOption {
  option_id: string;
  kind?: "accept_result";
}

/**
 * action.plan.submit 原话及服务端确认的公开互动参与者。
 */
export interface ActionBroadcastPayload {
  playerId: string;
  clientActionId: string;
  nickname: string;
  characterName?: string | null;
  utterance: string;
  speakerId?: string | null;
  listenerIds?: string[];
  participantIds?: string[];
}

/**
 * Player-safe declaration id and semantic cues supplied by one checkpoint.
 */
export interface ActionDeclarationOption {
  id: string;
  /**
   * @minItems 1
   */
  semantic_hints: [string, ...string[]];
}

export interface ActionPlanCancelPayload {
  clientActionId: string;
  requestId: string;
}

/**
 * 玩家输入的结构化接收者；自然语言 mention 只允许在客户端解析一次。
 */
export interface ActionRecipientPayload {
  kind: "keeper" | "npc";
  entityId?: string | null;
  explicit: boolean;
}

/**
 * action.plan.submit 事件 payload。
 *
 * `client_action_id` 是客户端为一次逻辑动作生成的稳定幂等键；网络重试必须
 * 复用原值。两个字段都在契约层拒绝空白文本。
 */
export interface ActionSubmitPayload {
  clientActionId: string;
  utterance: string;
  recipient: ActionRecipientPayload;
  summarizedFrom?: string[] | null;
  visibility?: ("public" | "private") | null;
}

export interface ActorResourceView {
  id: string;
  name: string;
  value: number;
}

export interface ActorValueView {
  id: string;
  name: string;
  value: number;
}

/**
 * Choose or cancel a v3 Engine-owned pending skill decision.
 */
export interface AdjudicationChoicePayload {
  clientActionId: string;
  requestId: string;
  sourceRevision: string;
  decisionId: string;
  decisionVersion: number;
  candidateId?: string | null;
  cancel?: boolean;
}

export interface AdjudicationPendingPayload {
  correlationId: string;
  planId?: string | null;
  sourceRevision: string;
  status: "awaiting_skill_choice" | "awaiting_post_roll_decision";
  pendingDecision?: PendingCheckDecisionView | null;
  checkRun?: CheckRunView | null;
}

/**
 * Resolve a v3 Engine-owned post-roll decision.
 */
export interface AdjudicationPostRollPayload {
  clientActionId: string;
  requestId: string;
  sourceRevision: string;
  checkId: string;
  checkVersion: number;
  optionId: string;
  revisedMethod?: string | null;
}

/**
 * 调查员年龄的合法区间（issue #96）。
 *
 * COC7 的年龄档从 15-19 起、到 80-89 止，所以合法区间是 [15, 89]。此前前端
 * 的输入框写死成 [10, 100]，两头都不符合规则。
 *
 * 注意本期只做区间约束，**不做年龄修正**（15-19 岁扣 STR/SIZ/EDU 各若干、
 * 20-39 岁一次教育增强检定、40 岁起每十年 MOV -1 等）——那是一整套生成期
 * 规则，要单独做。
 */
export interface AgeRangeSpec {
  minValue: number;
  maxValue: number;
}

/**
 * 点数购买法的约束（issue #96）。
 *
 * 这些数字此前只存在于前端代码里、后端既不校验也不暴露，导致 ①任何 SDK
 * 使用者都能提交 UI 永远不允许的角色卡 ②重写前端时必须把规则再实现一遍。
 * 放进 ruleset 是为了「一份定义、两方消费」：后端拿它裁决，客户端拿它渲染
 * 「还剩多少点」「这项最多加到多少」。
 *
 * 只约束 `point_buy=True` 的属性；幸运不在其列。
 */
export interface AttributePointBuyRules {
  budget: number;
  minValue: number;
  maxValue: number;
  defaultValue: number;
}

/**
 * 一项基础属性：键名、显示名、COC7 生成公式。
 *
 * `point_buy` 表示这一项是否参与点数购买法的分配。COC7 里幸运只能掷
 * （`3d6*5`）、不能用属性点买，所以它是 `False`——客户端据此决定哪些属性
 * 渲染成可加点、哪些只读展示，不需要自己维护一份"哪 8 项能加点"的名单
 * （issue #96：这份名单此前在前端硬编码了三处，加幸运时漏改一处导致
 * 角色卡看不到幸运值）。
 */
export interface AttributeSpec {
  key: string;
  label: string;
  generation: string;
  pointBuy?: boolean;
}

/**
 * 注册 / 登录成功后的返回：登录凭证 + 用户信息。
 */
export interface AuthResult {
  token: string;
  userId: string;
  nickname: string;
}

export interface AvailableExitView {
  id: string;
  name: string;
  target_id?: string | null;
  aliases?: string[];
  description?: string;
  destination?: ExitDestinationView | null;
}

export interface ChangeItemCustodyRequest {
  request_id: string;
  source_revision: string;
  actor_id: string;
  expected_version: number;
  reason: "pickup" | "drop" | "throw" | "place" | "transfer";
  to_custody: ItemCustody;
}

export interface ChangeItemCustodyResult {
  request_id: string;
  item: ItemInstance;
  revision: string;
  event_id: string;
}

/**
 * `compute_preview` 的响应结构：衍生值 + 两个技能点预算 + 全部技能的
 * base/cap/当前值 + 校验报告。
 */
export interface CharacterComputeResult {
  derivedStats: {
    [k: string]: number | string;
  };
  occupationSkillPoints: SkillPointsBudgetView;
  interestSkillPoints: SkillPointsBudgetView;
  skillView: SkillComputeView[];
  resolvedOccupationChoiceSkillIds?: string[];
  validation: ValidationIssueView[];
}

/**
 * POST /api/v1/rooms/{roomId}/characters 返回
 */
export interface CharacterDraftResult {
  characterId: string;
  status: string;
}

/**
 * POST /api/v1/systems/{systemId}/character/preview 请求体。
 */
export interface CharacterPreviewRequest {
  attributes: {
    [k: string]: number;
  };
  occupationId?: number | null;
  skills?: {
    [k: string]: number;
  };
  occupationChoiceSkillIds?: string[] | null;
  generationMethod?: "pointbuy" | "roll";
}

/**
 * GET /api/v1/rooms/{roomId}/characters/{characterId} 返回（issue #96）。
 *
 * 补这个端点是为了让**后端成为角色卡的唯一事实来源**。此前只有
 * 创建/保存/完成/掷属性四个写操作、没有任何读接口，前端因此只能把角色卡
 * 存进 localStorage 当权威源——而那份副本的结构会随后端 schema 演进而过期
 * （PR #88 加幸运后，旧的 8 键角色卡就再也编辑不了了）。
 *
 * `generation_method` 一并返回：客户端要据此知道这张卡该按点数购买法还是
 * 掷骰法来渲染与校验。
 */
export interface CharacterRead {
  id: string;
  status: string;
  basedOnTemplateId?: string | null;
  generationMethod: string;
  name?: string | null;
  age?: number | null;
  gender?: string | null;
  residence?: string;
  birthplace?: string;
  attributes?: {
    [k: string]: number;
  };
  derivedStats?: {
    [k: string]: number | string;
  };
  skills?: {
    [k: string]: number;
  };
  occupationChoiceSkillIds?: string[] | null;
  equipment?: string[];
  occupation?: string | null;
  background?: string;
  notes?: string;
}

/**
 * POST /api/v1/me/character-templates 请求体。
 *
 * `data.generation_method` 由服务端决定，这里传什么都会被覆盖成点数购买法：
 * 「属性是掷出来的」是一条**服务端背书**，只有服务端自己掷的那一次才能给出
 * （见 `POST /me/character-templates/{id}/roll-attributes`）。让客户端自己声明
 * 的话，它只要写上 roll 就能跳过 `complete` 的点数预算校验，8 项全 90 也能过。
 */
export interface CharacterTemplateCreateBody {
  name: string;
  systemId: string;
  data?: {
    [k: string]: unknown;
  };
}

/**
 * `我的常用角色卡` 列表/详情返回项。
 */
export interface CharacterTemplateRead {
  templateId: string;
  name: string;
  systemId: string;
  data: {
    [k: string]: unknown;
  };
  hasPortrait?: boolean;
  portraitVersion?: string | null;
  createdAt: string;
  updatedAt: string;
}

/**
 * PATCH /api/v1/me/character-templates/{templateId} 请求体（#337）。
 *
 * 卡库现在也是建卡的宿主，建卡向导的每一次保存都落到这里，所以要能只改名、
 * 只改数据、或两个都改——两个字段都可选，`None` 表示这一次不动它。
 *
 * `data` 命中时是**整体覆盖**而不是合并：合并语义下前端删掉一项技能永远删不掉。
 *
 * `data.generation_method` 同样不由客户端决定：只有「这次 PATCH 没有改动属性」
 * 时服务端背书的 roll 才会保留，其余一律退回点数购买法。这跟房间版
 * `update_character` 对 `roll` 的处理是同一道闸。
 */
export interface CharacterTemplateUpdateBody {
  name?: string | null;
  data?: {
    [k: string]: unknown;
  } | null;
}

/**
 * PATCH /api/v1/rooms/{roomId}/characters/{characterId} 请求体
 */
export interface CharacterUpdateBody {
  name: string;
  age?: number | null;
  gender?: string | null;
  residence?: string;
  birthplace?: string;
  attributes: {
    [k: string]: number;
  };
  derivedStats: {
    [k: string]: number;
  };
  skills: {
    [k: string]: number;
  };
  occupationChoiceSkillIds?: string[] | null;
  equipment?: EquipmentItem[];
  occupation?: string | null;
  background?: string;
  notes?: string;
}

/**
 * chat.message 广播 payload；channel 区分玩家讨论和角色扮演。
 */
export interface ChatMessagePayload {
  messageId: string;
  playerId: string;
  nickname: string;
  channel: "discussion" | "roleplay";
  actorId?: string | null;
  actorName?: string | null;
  text: string;
  sentAt: string;
  clientMessageId: string;
}

/**
 * 讨论区分页接口的一条消息。`sent_at` 用 UtcDatetime（对外时间字段的统一约定，
 * 见 app/dto/common.py）。
 */
export interface ChatMessageRead {
  messageId: string;
  playerId: string;
  nickname: string;
  channel: "discussion" | "roleplay";
  actorId?: string | null;
  actorName?: string | null;
  text: string;
  sentAt: string;
  clientMessageId: string;
}

/**
 * chat.send 讨论区消息；该通道不会进入 Host Agent 上下文。
 */
export interface ChatSendPayload {
  text: string;
  clientMessageId: string;
}

/**
 * 向动作发起者推送经 Actor 技能值过滤后的可用检定项。
 */
export interface CheckRequestPayload {
  playerId: string;
  clientActionId: string;
  summary: string;
  difficulty: "regular" | "hard" | "extreme";
  skills: CheckSkillOptionPayload[];
}

/**
 * check.result 推送最终权威结果。
 *
 * 保留原始骰点，并通过 resolution_kind / luck_spent 说明幸运等 post-roll
 * 结算，避免把未达标骰点直接展示成普通成功（issue #327）。
 */
export interface CheckResultPayload {
  playerId: string;
  clientActionId: string;
  skill: string;
  skillName: string;
  characterName?: string | null;
  rollValue: number;
  targetValue: number;
  difficulty: "regular" | "hard" | "extreme";
  successLevel: "critical" | "extreme" | "hard" | "regular" | "failure" | "fumble";
  passed: boolean;
  result: string;
  resolutionKind?: "initial_roll" | "accept_result" | "spend_luck" | "push";
  luckSpent?: number | null;
}

export interface CheckRoll {
  value: number;
  degree: "critical_success" | "extreme_success" | "hard_success" | "regular_success" | "failure" | "fumble";
  passed: boolean;
}

/**
 * 为待处理动作提交玩家选择的技能与 D100 结果。
 */
export interface CheckRollPayload {
  clientActionId: string;
  skill: string;
  rollValue: number;
}

export interface CheckRunView {
  check_id: string;
  action_request_id: string;
  selected_candidate_id: string;
  selected_skill_id: string;
  selected_skill_name: string;
  difficulty: "regular" | "hard" | "extreme";
  target_value: number;
  status: "awaiting_post_roll_decision" | "resolved";
  version: number;
  roll_count: number;
  roll: CheckRoll;
  post_roll_options?: (AcceptResultOption | SpendResourceOption | PushOption)[];
  final_result?: CheckRoll | null;
  resolution_kind?: "initial_roll" | "accept_result" | "spend_luck" | "push";
  luck_spent?: number | null;
}

/**
 * A player-owned skill that may be selected for the pending check.
 */
export interface CheckSkillOptionPayload {
  id: string;
  name: string;
  targetValue: number;
}

/**
 * Trusted candidate menu exposed to the host semantic matcher.
 */
export interface CheckpointOption {
  id: string;
  target_id: string;
  action_hint: string;
  skills?: string[];
  difficulty?: ("regular" | "hard" | "extreme") | null;
  declaration_options?: ActionDeclarationOption[];
}

/**
 * clue.granted 推送 payload（issue #77 新增，线索发现，本期不会真的发出）。
 */
export interface ClueGrantedPayload {
  playerId: string;
  clueName: string;
  description?: string | null;
}

export interface ConfirmEndingDraftRequest {
  request_id: string;
  source_revision: string;
  draft_version: number;
}

export interface ConfirmEndingDraftResult {
  request_id: string;
  resolution: EndingResolution;
  revision: string;
}

export interface ConfirmInventoryImportDraftRequest {
  request_id: string;
  source_revision: string;
  draft_version: number;
}

export interface ConfirmInventoryImportResult {
  request_id: string;
  draft_id: string;
  created_item_ids: string[];
  revision: string;
}

export interface CreateEndingDraftRequest {
  request_id: string;
  source_revision: string;
  mode?: "ending_and_epilogue";
  player_intent: string;
}

export interface CreateInventoryImportDraftRequest {
  request_id: string;
  source_revision: string;
  character_revision: string;
  claims: ItemClaim[];
}

/**
 * Host 以 NPC 身份生成的单条回复；头像 URL 仅为展示派生字段。
 */
export interface DialogueNpcPayload {
  messageId: string;
  speakerId: string;
  speakerName: string;
  avatarUrl?: string | null;
  listenerIds?: string[];
  participantIds?: string[];
  text: string;
  sceneId: string;
  sourceDialogueId: string;
  sourceActionId: string;
  ordinal: number;
  sourceRevision: string;
  sentAt: string;
  audiencePlayerIds?: string[];
}

/**
 * 玩家对场景 NPC 的结构化发言；受众在对话开始时冻结。
 */
export interface DialoguePlayerPayload {
  messageId: string;
  playerId: string;
  clientActionId: string;
  nickname: string;
  characterName: string;
  speakerId: string;
  interlocutorId: string;
  interlocutorName: string;
  listenerIds?: string[];
  participantIds?: string[];
  allowedResponderIds?: string[];
  utterance: string;
  sceneId: string;
  sourceRevision: string;
  sentAt: string;
  audiencePlayerIds?: string[];
}

export interface EndingDraft {
  draft_id: string;
  request_id: string;
  source_revision: string;
  mode?: "ending_and_epilogue";
  player_intent: string;
  title: string;
  summary: string;
  epilogue: string;
  facets?: {
    [k: string]: JsonValue;
  };
  /**
   * @minItems 1
   */
  evidence_refs: [string, ...string[]];
  version?: number;
  status?: "active" | "confirmed" | "expired";
}

export interface EndingResolution {
  draft_id: string;
  source_revision: string;
  anchor_id: string;
  /**
   * @minItems 1
   */
  fact_refs: [string, ...string[]];
  facets?: {
    [k: string]: JsonValue;
  };
  confirmed_by: string;
  confirmed_event_id: string;
}

export interface EquipmentItem {
  name: string;
}

/**
 * 统一错误码枚举。
 *
 * 用 StrEnum（Python 3.11+）而不是普通字符串常量或 int 枚举，好处是：
 * - 序列化成 JSON 时直接是字符串值（比如 "NOT_FOUND"），前端/SDK 拿到的就是可读的码；
 * - 类型检查器（ty/mypy）能校验到哪些地方在用错误码，重命名/新增时不会漏改；
 * - 每个成员名本身就是 UPPER_SNAKE_CASE，跟成员值保持一致，一眼能看出对应关系。
 *
 * 新增错误码时，在这里加一行即可；用哪个 HTTP 状态码由抛出方（业务代码里的
 * AppException(...) 调用）决定，这个枚举本身不绑定状态码。
 */
export type ErrorCode =
  | "VALIDATION_ERROR"
  | "BAD_REQUEST"
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "CONFLICT"
  | "CHARACTER_TEMPLATE_DUPLICATE"
  | "INTERNAL_ERROR"
  | "ROOM_NOT_FOUND"
  | "ROOM_FULL"
  | "MODULE_VALIDATION_FAILED"
  | "NOT_YOUR_TURN"
  | "ACTION_IN_PROGRESS"
  | "ACTION_QUEUE_FULL"
  | "CHARACTER_INCOMPLETE"
  | "MODULE_NOT_SELECTED"
  | "MODULE_PLAYER_COUNT_MISMATCH"
  | "RECONNECT_TOKEN_EXPIRED"
  | "RATE_LIMITED"
  | "NOT_IMPLEMENTED"
  | "CHARACTER_INVALID"
  | "RULESET_NOT_CONFIGURED"
  | "PORTRAIT_GENERATION_DISABLED"
  | "PORTRAIT_GENERATION_IN_PROGRESS"
  | "PORTRAIT_CONTENT_REJECTED"
  | "PORTRAIT_GENERATION_FAILED"
  | "PORTRAIT_GENERATION_TIMEOUT"
  | "HOST_SPEECH_UNAVAILABLE"
  | "HOST_SPEECH_FAILED"
  | "HOST_SPEECH_TIMEOUT"
  | "REVISION_CONFLICT"
  | "ITEM_VERSION_CONFLICT"
  | "ITEM_ALREADY_TAKEN"
  | "ENDING_UNAVAILABLE"
  | "ENDING_DRAFT_STALE";

/**
 * 错误信息的具体内容，只在 success=false 时出现在 error 字段里。
 *
 * `details` 是 issue #84 S2 新增的可选字段：装结构化的校验报告（比如建卡
 * 校验失败时的一条条 {code, field, message}），大多数错误不需要它，默认
 * None，不影响原有只有 code/message 的错误响应形状。
 */
export interface ErrorDetail {
  code: ErrorCode;
  message: string;
  details?:
    | {
        [k: string]: string;
      }[]
    | null;
}

/**
 * error 推送 payload（issue #77 新增）——本期唯一会被真的发出的新增
 * S→C 事件：`check.roll`/`san.check.roll`/`room.rejoin` 这三个 NOT_IMPLEMENTED
 * 桩、以及原来 game.start 失败时被静默丢弃（`continue`，见 ws.py 旧逻辑）
 * 的错误，都改成通过这个事件明确告知发起者，而不是让客户端干等。
 */
export interface ErrorPayload {
  code: string;
  message: string;
  correlationId?: string | null;
}

export interface ExitDestinationView {
  scene_id: string;
  name: string;
}

/**
 * game.ended 推送 payload（issue #77 新增，触发复盘，本期不会真的发出）。
 */
export interface GameEndedPayload {
  reason?: string | null;
}

/**
 * 游戏大类。
 */
export interface GameRead {
  id: string;
  name: string;
  description?: string | null;
  tags?: string[];
}

/**
 * game.start 事件 payload——目前不带任何字段。
 *
 * 定义一个空模型（而不是完全跳过校验）是为了让 game.start 也走跟其它事件
 * 一致的"接收端过一次模型校验"路径，行为对齐、不搞特例。
 */
export interface GameStartPayload {}

/**
 * 大类下的规则系统。
 */
export interface GameSystemRead {
  id: string;
  gameId: string;
  worldRef: string;
  name: string;
  version?: string | null;
  worldName?: string | null;
  worldDescription?: string | null;
  gameDescription?: string | null;
}

export interface HostSpeechManifestRead {
  messageId: string;
  sentences: HostSpeechSentenceRead[];
}

export interface HostSpeechSentenceRead {
  index: number;
  text: string;
}

export interface HostSpeechSettingsRead {
  available: boolean;
  provider: string;
  voiceType: string | null;
  voices: HostSpeechVoiceRead[];
  autoEmotion?: boolean;
}

export interface HostSpeechSettingsUpdate {
  voiceType: string;
}

export interface HostSpeechSettingsUpdatedPayload {
  voiceType: string | null;
}

export interface HostSpeechVoiceRead {
  voiceType: string;
  label: string;
}

export interface InventoryImportDraft {
  draft_id: string;
  request_id: string;
  room_id: string;
  player_id: string;
  actor_id: string;
  source_revision: string;
  character_revision: string;
  version?: number;
  entries: InventoryImportEntry[];
  confirmed?: boolean;
}

export interface InventoryImportEntry {
  claim_id: string;
  decision: "accepted" | "normalized" | "rejected";
  reason_code?:
    | (
        | "anachronistic"
        | "profession_mismatch"
        | "wealth_exceeded"
        | "restricted_by_setting"
        | "reserved_canon_identity"
        | "invalid_quantity"
        | "unsupported_item"
      )
    | null;
  normalized_definition?: ItemDefinition | null;
  narrative_policy: "brought" | "adjusted" | "not_brought";
}

export interface InventoryItemView {
  id: string;
  name: string;
  source_label?: string;
  quantity: number;
  condition: string;
  version: number;
}

export interface InventoryView {
  inventory?: InventoryItemView[];
  loose_items?: InventoryItemView[];
}

export interface ItemAcquisition {
  source_type: "character_import" | "location" | "entity" | "runtime";
  source_id: string;
  player_safe_label: string;
  event_id: string;
  revision: string;
}

export interface ItemCapability {
  id: string;
  type: string;
  target_selector?: ItemTargetSelector;
  consumes?: boolean;
}

export interface ItemClaim {
  claim_id: string;
  raw_name: string;
  declared_quantity?: number;
  declared_properties?: string[];
  source?: "character_sheet";
}

export interface ItemComponent {
  portable?: boolean;
  unique?: boolean;
  quantity?: number;
  capabilities?: ItemCapability[];
}

export interface ItemCustody {
  kind: "actor_inventory" | "location" | "entity" | "retired";
  ref_id: string;
  form: "carried" | "loose" | "placed" | "thrown" | "contained";
}

export interface ItemDefinition {
  definition_id: string;
  display: ItemDisplay;
  item_component: ItemComponent;
}

export interface ItemDisplay {
  name: string;
  description?: string;
}

export interface ItemInstance {
  id: string;
  room_id: string;
  kind?: "item";
  origin: "canon" | "runtime";
  definition_id: string;
  display: ItemDisplay;
  item_component: ItemComponent;
  custody: ItemCustody;
  state?: ItemState;
  acquisition?: ItemAcquisition | null;
  keeper_notes?: string;
  hidden_information_refs?: string[];
  version?: number;
  created_event_id: string;
  last_event_id: string;
  updated_revision: string;
}

export interface ItemState {
  condition?: string;
  status?: "active" | "retired";
  values?: {
    [k: string]: JsonValue;
  };
}

export interface ItemTargetSelector {
  entity_ids?: string[];
  location_ids?: string[];
}

/**
 * POST /api/v1/rooms/{roomCode}/join 请求体
 */
export interface JoinRoomBody {
  nickname?: string | null;
}

export interface JsonValue {
  [k: string]: unknown;
}

export interface KnownInformationView {
  id: string;
  title: string;
  summary: string;
  content: string;
  related_entities?: string[];
  related_scenes?: string[];
  scope: "actor" | "party";
}

export interface KnownLocationView {
  id: string;
  kind: "region" | "site" | "room" | "connector";
  name: string;
  description?: string;
  parent_location_id?: string | null;
  region_id?: string | null;
  existence: "rumored" | "known";
  localization: "unknown" | "approximate" | "located";
  access: "unknown" | "reachable" | "blocked";
  visited?: boolean;
}

export interface LocationBreadcrumbView {
  id: string;
  name: string;
}

export interface LocationContextView {
  current_location_id: string;
  breadcrumbs?: LocationBreadcrumbView[];
  position_context?: PositionContextView | null;
}

/**
 * POST /api/v1/auth/login 请求体
 */
export interface LoginBody {
  account: string;
  password: string;
}

/**
 * GET /PATCH /api/v1/auth/me 返回
 */
export interface MeRead {
  userId: string;
  account: string;
  nickname: string;
}

/**
 * GET /api/v1/modules/{moduleId} 返回——增加故事页展示信息。
 */
export interface ModuleDetailRead {
  id: string;
  gameSystemId: string;
  gameSystemName?: string | null;
  title: string;
  nameEn?: string | null;
  version: string;
  status: string;
  authors: string[];
  playersMin: number;
  playersMax: number;
  difficulty: number;
  estimatedDuration?: string | null;
  synopsis?: string | null;
  storyLabel?: string | null;
  subtitle?: string | null;
  storyPages: ModuleStoryPage[];
}

/**
 * POST /api/v1/modules/import 与 GET /api/v1/modules/import/{jobId} 返回。
 *
 * 不用 `from_attributes` 直接从 ORM 对象转换——ORM 主键列叫 `id`，这里
 * 对外字段叫 `job_id`（避免跟其它 DTO 的 `xxxId` 命名约定不一致），两者
 * 对不上，构造时由 service 层显式传关键字参数更直接。
 */
export interface ModuleImportJobRead {
  jobId: string;
  status: string;
  sourceFilename?: string | null;
  resultScenarioId?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
}

/**
 * POST /api/v1/modules/import 请求体。
 *
 * 真实实现（#57）会接收模组原始文档做 LLM 解析，本期这个接口固定返回
 * NOT_IMPLEMENTED，请求体只占位描述"以后大概会传什么"，不做内容校验。
 */
export interface ModuleImportRequestBody {
  sourceFilename: string;
}

/**
 * 模组信息（对应内容库 `Scenario` 表，`from_attributes=True` 支持直接从
 * ORM 对象构造）。
 */
export interface ModuleRead {
  id: string;
  gameSystemId: string;
  gameSystemName?: string | null;
  title: string;
  nameEn?: string | null;
  version: string;
  status: string;
  authors: string[];
  playersMin: number;
  playersMax: number;
  difficulty: number;
  estimatedDuration?: string | null;
  synopsis?: string | null;
}

/**
 * 玩家开局前可见的一页故事介绍。
 */
export interface ModuleStoryPage {
  title: string;
  content: string;
}

/**
 * GET /api/v1/me/rooms 返回项
 */
export interface MyRoomSummary {
  roomId: string;
  roomCode: string;
  roomName: string;
  phase: string;
  moduleTitle?: string | null;
  playerCount: number;
  maxPlayers: number;
  updatedAt: string;
}

/**
 * narration.chunk 推送 payload（issue #203）。
 *
 * 片段只是同一条 `narration.push` 的渐进展示形式，不是权威消息：服务端先
 * 生成并校验完整叙事、落库去重成功，才按句切片下发，最后再发权威的
 * `narration.push`。客户端按 `messageId` 归组、按 `sequence` 排序去重，
 * 拼接结果必须与最终 `narration.push` 的 `text` 完全一致；历史恢复和持久化
 * 始终只认 `narration.push`，临时拼接内容不得写入权威历史。
 */
export interface NarrationChunkPayload {
  messageId: string;
  sequence: number;
  text: string;
}

/**
 * narration.push 推送 payload。
 */
export interface NarrationPushPayload {
  messageId?: string | null;
  text: string;
}

export interface NarrativeDetailView {
  id: string;
  kind: "description" | "sensory" | "atmosphere" | "pacing" | "foreshadowing";
  text: string;
}

export interface ObservableStateView {
  key: string;
  label: string;
  value: JsonValue;
}

/**
 * 职业选择器里的展示分类。规则目录决定分类与顺序，前端只负责渲染。
 */
export interface OccupationCategorySpec {
  label: string;
  icon: string;
}

/**
 * 一个职业：信用评级区间、职业技能点公式、职业技能清单与展示元数据。
 *
 * 职业技能 = `skill_ids`（固定）+ `choice_slots`（自选，见 `SkillChoiceSlot`）。
 * 两者都吃职业技能点；其余技能吃兴趣点。
 */
export interface OccupationSpec {
  id: number;
  name: string;
  creditMin: number;
  creditMax: number;
  skillPointsFormula: string;
  skillIds: string[];
  choiceSlots?: SkillChoiceSlot[];
  description: string;
  icon?: string | null;
  categories?: string[];
}

/**
 * 权威开场正在由 Host 模型生成；模板模式不会发送。
 */
export interface OpeningStartedPayload {
  messageId: string;
}

export interface PendingCheckDecisionView {
  decision_id: string;
  status?: "awaiting_skill_choice";
  action_request_id: string;
  source_revision: string;
  decision_version: number;
  actor_id: string;
  summary: string;
  /**
   * @minItems 1
   */
  options: [PendingCheckOption, ...PendingCheckOption[]];
  allow_cancel?: boolean;
}

export interface PendingCheckOption {
  candidate_id: string;
  skill_id: string;
  display_name: string;
  target_value: number;
  difficulty: "regular" | "hard" | "extreme";
  method_summary: string;
  player_safe_reason: string;
}

export interface PlanProgressPayload {
  correlationId: string;
  currentStep: number;
  completedSteps: number;
  totalSteps: number;
  phase: "understanding" | "executing" | "waiting_for_player" | "stopped" | "completed";
  publicProgressLabel?: string | null;
  safeReason?: string | null;
}

/**
 * player.joined 推送 payload（issue #77 新增，同上，本期不会真的发出）。
 */
export interface PlayerJoinedPayload {
  player: RoomPlayerRead;
}

/**
 * player.ready 事件 payload。
 *
 * `ready` 必填、不给默认值：协议上「设置准备状态」这个动作必须说清楚要设成
 * 什么，缺字段是一条畸形消息，应该被丢弃，而不是被悄悄当成 `False` 处理。
 * 这里给默认值的代价不只在后端——它会顺着 codegen 变成 SDK 的
 * `ready?: boolean`，让 `setReady(playerId, {})` 也能通过类型检查并静默地把
 * 玩家设成未准备（见 PR #76 review）。改动前的手写 SDK 类型本来就是必填的。
 */
export interface PlayerReadyPayload {
  ready: boolean;
}

/**
 * Complete player-safe world snapshot used by one model/Agent run.
 */
export interface PlayerView {
  room_id: string;
  player_id: string;
  actor_id: string;
  background: string;
  scene_id: string;
  phase: "playing" | "ended";
  revision: string;
  self_actor: SelfActorView;
  scene: SceneView;
  location_context?: LocationContextView | null;
  known_locations?: KnownLocationView[];
  inventory?: InventoryItemView[];
  world?: WorldStateView;
  known_information?: KnownInformationView[];
  checkpoint_options?: CheckpointOption[];
}

export interface PortraitGenerationRequest {
  style?: "realistic";
  size?: "1024x1024";
}

/**
 * 可安全返回给玩家的生图任务快照。
 */
export interface PortraitGenerationTaskRead {
  generationId: string;
  status: "queued" | "generating" | "cancelling" | "completed" | "failed" | "cancelled";
  cancelRequested: boolean;
  failureCode?:
    ("content_rejected" | "timeout" | "provider_failed" | "materialization_failed" | "process_restarted") | null;
  portraitVersion?: string | null;
  promptSummary?: string | null;
  promptSource?: ("deepseek" | "deterministic" | "deterministic_fallback") | null;
  style: "realistic";
  size: "1024x1024";
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  updatedAt: string;
}

export interface PositionContextView {
  kind?: "access_boundary";
  id: string;
  label: string;
  state: "locked" | "blocked" | "interaction_required";
  destination_id: string;
}

export interface PushOption {
  option_id: string;
  kind?: "push";
  requires_revised_method?: true;
  player_safe_risk_summary: string;
}

/**
 * 可选的玩家身份信息；旧客户端不传时仍使用确定性默认资料。
 */
export interface QuickGenerateRequest {
  name?: string | null;
  age?: number | null;
  gender?: string | null;
  residence?: string;
  birthplace?: string;
}

/**
 * 一键生成后返回的房间角色草稿和权威计算结果。
 */
export interface QuickGenerateResult {
  character: CharacterRead;
  occupationId: number;
  compute: CharacterComputeResult;
}

/**
 * POST /api/v1/auth/register 请求体
 */
export interface RegisterBody {
  account: string;
  password: string;
  nickname: string;
}

/**
 * GET /api/v1/rooms/{roomId}/replay 返回项——对应 `events` 表的一行。
 */
export interface ReplayEventRead {
  id: string;
  playerId?: string | null;
  eventType: string;
  payload: {
    [k: string]: unknown;
  };
  createdAt: string;
}

/**
 * POST /api/v1/rooms/{roomId}/characters/{characterId}/roll-attributes 返回。
 *
 * 服务端权威掷骰（COC7 标准法）：STR/CON/DEX/APP/POW = 3d6*5，
 * SIZ/INT/EDU = (2d6+6)*5；衍生值按标准公式算出 HP/MP/SAN，写回
 * `characters.attributes`/`derived_stats` 后原样返回给客户端展示。
 */
export interface RollAttributesResult {
  attributes: {
    [k: string]: number;
  };
  derivedStats: {
    [k: string]: number;
  };
}

/**
 * 已接受、尚未开始的主持行动。
 */
export interface RoomActionQueueItemPayload {
  playerId: string;
  actorId: string;
  clientActionId: string;
  recipient: ActionRecipientPayload;
  position: number;
  utterance: string;
  acceptedAt: string;
}

/**
 * 房间当前行动所有权的可重放快照，不包含模型计划或私密裁决。
 */
export interface RoomActionStatePayload {
  status: "idle" | "processing" | "awaiting_player";
  playerId?: string | null;
  actorId?: string | null;
  clientActionId?: string | null;
  startedAt?: string | null;
  revision: string;
  queued?: RoomActionQueueItemPayload[];
}

/**
 * GET /api/v1/rooms/{roomId}/conversation 返回项。
 *
 * 它面向房间页恢复当前对话 UI：讨论区消息继续来自 `chat_messages`，行动频道
 * 的玩家原话、主持叙事和检定结果来自 `events`。这不是 replay 的替代品；
 * 讨论区仍然不进入 replay，也仍然会在结束游戏时按既有语义清理。
 */
export interface RoomConversationEventRead {
  id: string;
  type: "chat.message" | "action.broadcast" | "narration.push" | "check.result" | "dialogue.player" | "dialogue.npc";
  channel: "discussion" | "action";
  payload: {
    [k: string]: unknown;
  };
  createdAt: string;
}

/**
 * POST /api/v1/rooms 请求体
 */
export interface RoomCreate {
  nickname?: string | null;
  roomName: string;
  maxPlayers?: number;
}

/**
 * POST /api/v1/rooms 返回
 */
export interface RoomCreateResult {
  roomId: string;
  roomCode: string;
  reconnectToken: string;
  playerId: string;
  characterId?: string | null;
}

/**
 * room.join 事件 payload。
 *
 * `reconnect_token` 必填：它是玩家在这个房间里的身份密钥（`players.reconnect_token`，
 * 建房/加入时下发给本人）。WS 连接握手只校验了「你是某个登录账号」，但连接
 * 时带的 playerId 是任意的、而且被公开房间预览暴露——只认 playerId 会让任何
 * 登录用户绑定成别人（冒充房主 game.start / 提交行动，PR #78 review 指出）。
 * 绑定时要求出示该玩家的 reconnect_token，才能证明「你就是这个玩家本人」。
 *
 * roomCode/nickname 是前端沿用原型习惯发送的冗余字段，服务端不读，保留可选
 * 以免影响现有调用方。
 */
export interface RoomJoinPayload {
  reconnectToken: string;
  roomCode?: string | null;
  nickname?: string | null;
}

/**
 * 房间内玩家摘要。
 *
 * 注意 `player_id` 对应 ORM `Player` 的主键属性 `id`（名字不一样），所以不能直接
 * `model_validate(player_orm)`——调用方需要显式映射 `player_id=p.id`（见
 * service/room.py 的 _to_room_preview）。`from_attributes=True` 仍保留，方便
 * 其余名字一致的字段。camelCase 别名生成、populate_by_name 继承自 `CamelModel`——
 * pydantic 的 `model_config` 在子类里是合并而非整体覆盖父类配置，这里不需要
 * 重复声明（issue #77 审计发现 #1，原先这里重写了一份和父类一样的配置，是
 * #75 遗留的死代码）。
 */
export interface RoomPlayerRead {
  playerId: string;
  nickname: string;
  characterName?: string | null;
  isHost: boolean;
  ready: boolean;
  hasCharacter: boolean;
  hasPortrait?: boolean;
  portraitVersion?: string | null;
}

/**
 * GET /api/v1/rooms/{roomCode} 返回
 */
export interface RoomPreview {
  roomId: string;
  roomCode: string;
  roomName: string;
  phase: string;
  storyStarted: boolean;
  moduleId?: string | null;
  moduleTitle?: string | null;
  playerCount: number;
  maxPlayers: number;
  players: RoomPlayerRead[];
}

/**
 * room.rejoin 事件 payload（issue #77 新增，仅铺协议，见决策 6）。
 *
 * `reconnect_token` 是房间身份体系的重连凭证（`players.reconnect_token`，
 * 不是账号登录 token），本期只校验格式、不做真实的断线重连逻辑。
 */
export interface RoomRejoinPayload {
  reconnectToken: string;
}

/**
 * room.state 推送 payload（issue #77 新增，替代 HTTP 轮询伪广播）。
 *
 * 本期协议槽位已留好（信封类型/校验器/SDK 方法齐全），但 ws.py 里没有任何
 * 地方会真的发出这个事件——大厅玩家列表仍然是前端 `GET /rooms/{roomCode}`
 * 轮询获取（issue"三处原型取舍"表格，真正切换依赖前端改动，本期不动
 * trpg-frontend）。
 */
export interface RoomStatePayload {
  roomId: string;
  phase: string;
  players: RoomPlayerRead[];
}

/**
 * GET /api/v1/rooms/{roomId}/summary 返回。
 */
export interface RoomSummaryRead {
  roomId: string;
  summaryText?: string | null;
  highlights?: string[] | null;
}

/**
 * 建卡所需的规则数据：属性/技能/职业目录（`GET /systems/{systemId}/ruleset`）。
 */
export interface RulesetRead {
  attributes: AttributeSpec[];
  attributePointBuy?: AttributePointBuyRules | null;
  ageRange?: AgeRangeSpec | null;
  skills: SkillSpec[];
  occupations: OccupationSpec[];
  occupationCategories?: OccupationCategorySpec[];
}

/**
 * san.check.request 推送 payload（issue #77 新增，本期不会真的发出）。
 */
export interface SanCheckRequestPayload {
  playerId: string;
  currentSan?: number | null;
}

/**
 * san.check.result 推送 payload（issue #77 新增，同 CheckResultPayload
 * 直接返回终值，本期不会真的发出）。
 */
export interface SanCheckResultPayload {
  playerId: string;
  rollValue: number;
  sanLoss: number;
  result: string;
}

/**
 * san.check.roll 事件 payload（issue #77 新增）。
 *
 * 定义一个空模型（而不是完全跳过校验）理由同 GameStartPayload：让它也走
 * 跟其它事件一致的"接收端过一次模型校验"路径。本期同样是 NOT_IMPLEMENTED 桩。
 */
export interface SanCheckRollPayload {}

/**
 * 广播完整待确认场景状态，供所有客户端幂等覆盖本地确认条。
 */
export interface SceneTransitionPendingPayload {
  proposalId: string;
  proposalVersion: number;
  sourceRevision: string;
  sourceSceneId: string;
  targetSceneId: string;
  requesterPlayerId: string;
  requiredPlayerIds: string[];
  acceptedPlayerIds: string[];
  expiresAt: string;
}

/**
 * 广播场景提案终态；批准时附带已经提交的权威 revision。
 */
export interface SceneTransitionResolvedPayload {
  proposalId: string;
  status: "approved" | "rejected" | "expired" | "stale";
  sourceSceneId: string;
  targetSceneId: string;
  committedRevision?: string | null;
}

/**
 * 玩家对一个冻结的共享场景切换提案作出同意或拒绝。
 */
export interface SceneTransitionRespondPayload {
  proposalId: string;
  proposalVersion: number;
  sourceRevision: string;
  accept: boolean;
}

export interface SceneView {
  id: string;
  name: string;
  description: string;
  time?: string | null;
  narrative_details?: NarrativeDetailView[];
  visible_entities?: VisibleEntity[];
  visible_actors?: VisibleActorView[];
  available_exits?: AvailableExitView[];
  loose_items?: InventoryItemView[];
}

/**
 * POST /api/v1/rooms/{roomId}/module 请求体
 */
export interface SelectModuleBody {
  moduleId: string;
  attributeGenMethod?: string;
}

/**
 * The requesting player's actor; only public_status_summary may be shared.
 */
export interface SelfActorView {
  id: string;
  name: string;
  occupation?: string | null;
  attributes?: ActorValueView[];
  skills?: ActorValueView[];
  resources?: ActorResourceView[];
  conditions?: string[];
  equipment?: string[];
  background_summary?: string;
  public_status_summary?: string;
}

/**
 * session.bound 推送 payload。
 */
export interface SessionBoundPayload {
  roomId: string;
  playerId: string;
}

/**
 * 职业技能里的一个「自选槽」：从 `candidate_skill_ids` 里选 `count` 项，
 * 选中的技能算**职业技能**（吃职业技能点），而不是兴趣技能（issue #114）。
 *
 * COC7 的职业技能不是一份固定清单，而是「固定技能 + N 个自选槽」，例如
 * 私家侦探是「技艺（摄影），乔装，法律，图书馆，**一项社交技能**（取悦、
 * 话术、恐吓、说服），心理学，侦查，**任意一项**其他个人或时代特长」。
 * 229 个职业里有 221 个（96.5%）至少带一个槽。
 *
 * 此前数据模型只有固定 `skill_ids`，装不下槽，于是"一项社交技能（四选一）"
 * 只能被压平成固定两项——这正是现有 30 个职业技能列表失真的原因（全部被
 * 规整成恰好 8 项，而规则书里实际是 0–15 项），并且会**误杀合法角色卡**：
 * 玩家把点数加在规则书认可、但被压平时丢掉的本职技能上，会被当成兴趣技能
 * 计费而触发 `INTEREST_POINTS_EXCEEDED`。
 *
 * `candidate_skill_ids` 为 `None` 表示**任意技能**（规则书里的"任意 N 项
 * 其他个人或时代特长"）；给出列表则表示限定候选集（如社交技能四选一）。
 */
export interface SkillChoiceSlot {
  count: number;
  candidateSkillIds?: string[] | null;
  label: string;
}

/**
 * 一项技能的计算结果：基础值/已分配点数/当前值/上限。
 */
export interface SkillComputeView {
  id: string;
  base: number;
  allocated: number;
  current: number;
  cap: number;
}

/**
 * 一个技能点池（职业/兴趣）的预算/已用/剩余。
 */
export interface SkillPointsBudgetView {
  budget: number;
  spent: number;
  remaining: number;
}

/**
 * 一项技能：基础值可以是固定数字，也可以是依赖属性的公式字符串
 * （比如闪避 `DEX/2`、母语 `EDU`）。
 */
export interface SkillSpec {
  id: string;
  name: string;
  nameEn?: string | null;
  base: number | string;
  category: string;
  relatedAttr?: string | null;
}

export interface SpendResourceOption {
  option_id: string;
  kind?: "spend_resource";
  resource_id?: "luck";
  cost: number;
  result_degree: "critical_success" | "extreme_success" | "hard_success" | "regular_success" | "failure" | "fumble";
}

/**
 * POST /api/v1/systems/{systemId}/character/quick-generate 返回（#337）。
 *
 * 不依赖房间的一键生成。跟房间版 `QuickGenerateResult` 的区别是它**不落库**：
 * 没有 `characterId`，也没有 `status`，只把生成结果交回客户端，由客户端决定
 * 存进哪张卡库卡（`PATCH /me/character-templates/{id}`）。
 *
 * `data` 与 `CharacterTemplateRead.data` 同形，可以原样 PATCH 回去，中间不用
 * 再拼一次字段。
 */
export interface SystemQuickGenerateResult {
  data: {
    [k: string]: unknown;
  };
  occupationId?: number | null;
  compute?: CharacterComputeResult | null;
}

/**
 * 广播完整待确认状态，供所有客户端幂等覆盖本地确认条。
 *
 * 只投模组允许玩家看到的措辞。精确目标留在提案记录里做校验与恢复——
 * 只删 PlayerView 字段而让确认弹窗照旧显示「第 1 天 22:00」，等于没收窄
 * （#415 §阶段一）。`target_point_id` 一并去掉：`hour_22` 反推得出小时。
 */
export interface TimeAdvancePendingPayload {
  proposalId: string;
  proposalVersion: number;
  sourceRevision: string;
  targetLabel: string;
  requesterPlayerId: string;
  requiredPlayerIds: string[];
  acceptedPlayerIds: string[];
  expiresAt: string;
}

/**
 * 广播提案终态；批准时附带已经提交的 revision 与玩家可见措辞。
 */
export interface TimeAdvanceResolvedPayload {
  proposalId: string;
  status: "approved" | "rejected" | "expired" | "stale";
  targetLabel: string;
  committedRevision?: string | null;
}

/**
 * 玩家对一个冻结的共享时间推进提案作出同意或拒绝。
 */
export interface TimeAdvanceRespondPayload {
  proposalId: string;
  proposalVersion: number;
  sourceRevision: string;
  accept: boolean;
}

export interface ToolCompletedPayload {
  correlationId: string;
  toolName: string;
  status: "success" | "error";
}

export interface ToolStartedPayload {
  correlationId: string;
  toolName: string;
  publicProgressLabel: string;
}

/**
 * turn.begin 推送 payload（issue #77 新增，回合制约束，本期不会真的发出）。
 */
export interface TurnBeginPayload {
  playerId: string;
}

export interface TurnFailedPayload {
  correlationId: string;
  code: string;
  publicMessage: string;
  retryable: boolean;
}

export interface TurnPhaseChangedPayload {
  correlationId: string;
  phase:
    | "reading_player_view"
    | "understanding_action"
    | "waiting_for_check"
    | "executing_action"
    | "refreshing_player_view"
    | "generating_narration";
}

export interface TurnStartedPayload {
  correlationId: string;
}

/**
 * PATCH /api/v1/auth/me 请求体
 */
export interface UpdateNicknameBody {
  nickname: string;
}

/**
 * 一条结构化校验失败信息，空列表代表这张卡合法。
 */
export interface ValidationIssueView {
  code: string;
  field: string;
  message: string;
}

/**
 * view.private 推送 payload（issue #77 新增，私密视角/不泄底的载体）。
 *
 * 本期协议槽位已留好，但 `narration.push` 仍然是全房间广播（issue
 * "三处原型取舍"表格），没有任何地方会真的发出这个事件——真正的信息
 * 不对称需要规则引擎知道"这条叙事该给谁看"，归 #48/#68。
 */
export interface ViewPrivatePayload {
  playerId: string;
  text: string;
}

export interface ViewUpdatedPayload {
  playerId: string;
  playerView: PlayerView;
}

/**
 * Another actor currently visible to this player, with public fields only.
 */
export interface VisibleActorView {
  id: string;
  name: string;
  occupation?: string | null;
  status_summary?: string;
}

export interface VisibleEntity {
  id: string;
  kind: "npc" | "object" | "location";
  name: string;
  aliases?: string[];
  description: string;
  narrative_details?: NarrativeDetailView[];
  observable_state?: ObservableStateView[];
}

/**
 * Player-safe world facts committed outside the current scene.
 *
 * See :class:`ProjectionWorldState`; this is the same data on the model/UI
 * side of the projector.
 */
export interface WorldStateView {
  time_label?: string;
  can_advance_time?: boolean;
  core_resolved?: boolean;
  ending_available?: boolean;
  ending_id?: string | null;
}
