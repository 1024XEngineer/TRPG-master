/**
 * 本文件由 `npm run codegen` 从后端 pydantic 模型自动生成，请勿手改。
 *
 * 源头：trpg-backend/app/dto/{auth,room,character,common,ws}.py
 * 重新生成：
 *   1. cd trpg-backend && uv run python scripts/export_schema.py
 *   2. cd trpg-sdk && npm run codegen
 * 生成后把这个文件的改动一并提交——CI 会重新跑一遍上面两步，用 git diff
 * 校验有没有人改了后端 DTO 却忘记重新生成（issue #75 决策 3）。
 */

/**
 * action.submit 事件 payload。
 *
 * `utterance` 必填，理由同 PlayerReadyPayload.ready：一条不带行动内容的
 * action.submit 是畸形消息。给默认空串会让 SDK 侧变成 `utterance?: string`，
 * 于是 `submitAction(playerId, {})` 类型检查通过、运行时静默无操作。
 *
 * 注意「必填」只管字段存在，空白内容（`""` / `"   "`）仍由下游的
 * `strip()` + 空值判断拦掉，两者不冲突。
 */
export interface ActionSubmitPayload {
  utterance: string;
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
  equipment?: string[];
  occupation?: string | null;
  background?: string;
  notes?: string;
}

/**
 * POST /api/v1/me/character-templates 请求体（issue 决策 5，本期不实现）。
 */
export interface CharacterTemplateCreateBody {
  name: string;
  systemId: string;
  data?: {
    [k: string]: unknown;
  };
}

/**
 * `我的常用角色卡` 列表/详情返回项（issue 决策 5，本期不实现）。
 */
export interface CharacterTemplateRead {
  templateId: string;
  name: string;
  systemId: string;
  data: {
    [k: string]: unknown;
  };
  createdAt: string;
  updatedAt: string;
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
  equipment?: EquipmentItem[];
  occupation?: string | null;
  background?: string;
  notes?: string;
}

/**
 * check.request 推送 payload（issue #77 新增，本期不会真的发出）。
 */
export interface CheckRequestPayload {
  playerId: string;
  skill: string;
  targetValue?: number | null;
}

/**
 * check.result 推送 payload（issue #77 新增）。
 *
 * 直接返回终值，不做两段式初步结果（issue 决策 4：幸运消耗机制推迟，
 * 协议一并简化）。本期不会真的发出。
 */
export interface CheckResultPayload {
  playerId: string;
  skill: string;
  rollValue: number;
  targetValue?: number | null;
  result: string;
}

/**
 * check.roll 事件 payload（issue #77 新增）——玩家请求做一次技能检定。
 *
 * `skill` 必填：说清楚要检定哪个技能是这个动作本身的意义所在。这条链路
 * 本期是 NOT_IMPLEMENTED 桩（见 issue"三处原型取舍"表格——真正的服务端
 * 权威掷骰依赖规则引擎裁决，归 #48/#68），handler 校验完这个 payload 就
 * 直接回 `error` 事件，不会真的掷骰或读写 `check_results` 表。
 */
export interface CheckRollPayload {
  skill: string;
}

/**
 * clue.granted 推送 payload（issue #77 新增，线索发现，本期不会真的发出）。
 */
export interface ClueGrantedPayload {
  playerId: string;
  clueName: string;
  description?: string | null;
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
  | "INTERNAL_ERROR"
  | "ROOM_NOT_FOUND"
  | "ROOM_FULL"
  | "MODULE_VALIDATION_FAILED"
  | "NOT_YOUR_TURN"
  | "CHARACTER_INCOMPLETE"
  | "MODULE_NOT_SELECTED"
  | "RECONNECT_TOKEN_EXPIRED"
  | "RATE_LIMITED"
  | "NOT_IMPLEMENTED"
  | "CHARACTER_INVALID";

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
  name: string;
  version?: string | null;
}

/**
 * POST /api/v1/rooms/{roomCode}/join 请求体
 */
export interface JoinRoomBody {
  nickname?: string | null;
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
 * GET /api/v1/modules/{moduleId} 返回——在 ModuleRead 基础上补充简介。
 */
export interface ModuleDetailRead {
  id: string;
  title: string;
  version: string;
  authors: string[];
  playersMin: number;
  playersMax: number;
  difficulty: number;
  estimatedDuration?: string | null;
  synopsis?: string | null;
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
  title: string;
  version: string;
  authors: string[];
  playersMin: number;
  playersMax: number;
  difficulty: number;
  estimatedDuration?: string | null;
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
 * narration.push 推送 payload。
 */
export interface NarrationPushPayload {
  text: string;
}

/**
 * 一个职业：信用评级区间、职业技能点公式、职业技能清单。
 */
export interface OccupationSpec {
  id: number;
  name: string;
  creditMin: number;
  creditMax: number;
  skillPointsFormula: string;
  skillIds: string[];
  description: string;
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
  isHost: boolean;
  ready: boolean;
  hasCharacter: boolean;
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
 * POST /api/v1/rooms/{roomId}/module 请求体
 */
export interface SelectModuleBody {
  moduleId: string;
  attributeGenMethod?: string;
}

/**
 * session.bound 推送 payload。
 */
export interface SessionBoundPayload {
  roomId: string;
  playerId: string;
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

/**
 * turn.begin 推送 payload（issue #77 新增，回合制约束，本期不会真的发出）。
 */
export interface TurnBeginPayload {
  playerId: string;
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
