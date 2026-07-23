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

import type { ErrorDetail, MyRoomSummary as GeneratedMyRoomSummary } from './generated/dto';

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
  RollAttributesResult,
  // 我的卡库（issue #77 决策 5）—— 对应后端 dto/character.py
  CharacterTemplateCreateBody as SaveCharacterTemplateInput,
  CharacterTemplateRead as CharacterTemplate,
  // 建卡计算/校验预览（issue #84 S2）—— 对应后端 dto/character.py
  CharacterPreviewRequest as PreviewCharacterInput,
  CharacterComputeResult,
  SkillPointsBudgetView,
  SkillComputeView,
  ValidationIssueView,
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
  // WebSocket 现有 6 个事件（issue #60）—— 对应后端 dto/ws.py
  RoomJoinPayload,
  PlayerReadyPayload,
  ActionSubmitPayload,
  GameStartPayload,
  SessionBoundPayload,
  NarrationPushPayload,
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
  SanCheckRequestPayload,
  SanCheckResultPayload,
  ClueGrantedPayload,
  ErrorPayload,
  // 讨论区 + 行动广播（issue #107）—— 对应后端 dto/ws.py 与 dto/chat.py
  ChatSendPayload,
  ChatMessagePayload,
  ActionBroadcastPayload,
  ChatMessageRead as ChatMessage,
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
  ErrorPayload,
  GameEndedPayload,
  NarrationPushPayload,
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
  // issue #107：讨论区消息广播 + 玩家对 AI 说的原话广播（后端真实发出）
  | { type: 'chat.message'; payload: ChatMessagePayload }
  | { type: 'action.broadcast'; payload: ActionBroadcastPayload }
  | { type: 'room.state'; payload: RoomStatePayload }
  | { type: 'player.joined'; payload: PlayerJoinedPayload }
  | { type: 'turn.begin'; payload: TurnBeginPayload }
  | { type: 'game.ended'; payload: GameEndedPayload }
  | { type: 'view.private'; payload: ViewPrivatePayload }
  | { type: 'check.request'; payload: CheckRequestPayload }
  | { type: 'check.result'; payload: CheckResultPayload }
  | { type: 'san.check.request'; payload: SanCheckRequestPayload }
  | { type: 'san.check.result'; payload: SanCheckResultPayload }
  | { type: 'clue.granted'; payload: ClueGrantedPayload }
  | { type: 'error'; payload: ErrorPayload };
