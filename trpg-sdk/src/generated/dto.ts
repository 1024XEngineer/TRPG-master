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
 * 注册 / 登录成功后的返回：登录凭证 + 用户信息。
 */
export interface AuthResult {
  token: string;
  userId: string;
  nickname: string;
}

/**
 * POST /api/v1/rooms/{roomId}/characters 返回
 */
export interface CharacterDraftResult {
  characterId: string;
  status: string;
}

/**
 * PATCH /api/v1/rooms/{roomId}/characters/{characterId} 请求体
 */
export interface CharacterUpdateBody {
  name: string;
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
  "VALIDATION_ERROR" | "BAD_REQUEST" | "UNAUTHORIZED" | "FORBIDDEN" | "NOT_FOUND" | "CONFLICT" | "INTERNAL_ERROR";

/**
 * 错误信息的具体内容，只在 success=false 时出现在 error 字段里。
 */
export interface ErrorDetail {
  code: ErrorCode;
  message: string;
}

/**
 * game.start 事件 payload——目前不带任何字段。
 *
 * 定义一个空模型（而不是完全跳过校验）是为了让 game.start 也走跟其它事件
 * 一致的"接收端过一次模型校验"路径，行为对齐、不搞特例。
 */
export interface GameStartPayload {}

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
 * 模组信息
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
}

/**
 * room.join 事件 payload。
 *
 * handler 目前不读取这里的任何字段——房间 ID 来自 URL 路径，玩家身份来自
 * 信封的 playerId，roomCode/nickname 是前端沿用 trpg-app 原型习惯发送的
 * 冗余字段。两个字段都设默认值，是因为现有测试/部分调用路径会发送空
 * payload（见 tests/test_ws.py），模型必须能校验通过。
 */
export interface RoomJoinPayload {
  roomCode?: string | null;
  nickname?: string | null;
}

/**
 * 房间内玩家摘要
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
 * PATCH /api/v1/auth/me 请求体
 */
export interface UpdateNicknameBody {
  nickname: string;
}
