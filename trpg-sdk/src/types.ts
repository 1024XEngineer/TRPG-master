/** 对应后端 ErrorDetail：只在 success=false 时出现。 */
export interface ErrorDetail {
  code: string;
  message: string;
}

/** 对应后端 ApiResponse[T]：全项目统一的响应信封形状。 */
export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ErrorDetail | null;
}

/** 对应后端 dto/example.py 里的 ExampleRead（GET/POST/PUT 的返回形状）。 */
export interface Example {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

/** 对应后端 ExampleCreate：POST 请求体。 */
export interface ExampleCreateInput {
  name: string;
  description?: string | null;
}

/** 对应后端 ExampleUpdate：PUT 请求体。 */
export interface ExampleUpdateInput {
  name: string;
  description?: string | null;
}

// ──────────────────────────────────────────────
// 认证（Auth）模块 — 与后端 dto/auth.py 手动保持同步
// ──────────────────────────────────────────────

/** POST /api/v1/auth/register 请求体 */
export interface RegisterInput {
  account: string;
  password: string;
  nickname: string;
}

/** POST /api/v1/auth/login 请求体 */
export interface LoginInput {
  account: string;
  password: string;
}

/** PATCH /api/v1/auth/me 请求体 */
export interface UpdateNicknameInput {
  nickname: string;
}

/** 注册 / 登录成功后的返回：登录凭证 + 用户信息。 */
export interface AuthResult {
  token: string;
  userId: string;
  nickname: string;
}

/** GET/PATCH /api/v1/auth/me 返回 */
export interface Me {
  userId: string;
  account: string;
  nickname: string;
}

// ──────────────────────────────────────────────
// 房间（Room）模块 — 与后端 dto/room.py 手动保持同步
// ──────────────────────────────────────────────

/** POST /api/v1/rooms 请求体 */
export interface CreateRoomInput {
  nickname?: string;
  roomName: string;
  maxPlayers: number;
}

/** POST /api/v1/rooms 返回（创建者自动获得身份） */
export interface CreateRoomResult {
  roomId: string;
  roomCode: string;
  reconnectToken: string;
  playerId: string;
}

/** GET /api/v1/modules 返回项 */
export interface ModuleSummary {
  id: string;
  title: string;
  version: string;
  authors: string[];
  playersMin: number;
  playersMax: number;
  difficulty: number;
  estimatedDuration: string | null;
}

/** POST /api/v1/rooms/{roomId}/module 请求体 */
export interface SelectModuleInput {
  moduleId: string;
  attributeGenMethod: string;
}

/** POST /api/v1/rooms/{roomCode}/join 请求体 */
export interface JoinRoomInput {
  nickname?: string;
}

/** 房间内的玩家摘要 */
export interface RoomPlayerSummary {
  playerId: string;
  nickname: string;
  isHost: boolean;
  ready: boolean;
  hasCharacter: boolean;
}

/** GET /api/v1/rooms/{roomCode} 返回 */
export interface RoomPreview {
  roomId: string;
  roomCode: string;
  roomName: string;
  phase: string;
  storyStarted: boolean;
  moduleTitle: string | null;
  playerCount: number;
  maxPlayers: number;
  players: RoomPlayerSummary[];
}

/** GET /api/v1/me/rooms 返回项 */
export interface MyRoomSummary {
  roomId: string;
  roomCode: string;
  roomName: string;
  phase: string;
  moduleTitle: string | null;
  playerCount: number;
  maxPlayers: number;
  updatedAt: number;
}

// ──────────────────────────────────────────────
// 角色建卡（Character）模块 — 与后端 dto/character.py 手动保持同步
// ──────────────────────────────────────────────

/** 建卡向导提交的一件装备。 */
export interface CharacterEquipmentItem {
  name: string;
}

/** PATCH /api/v1/rooms/{roomId}/characters/{characterId} 请求体——建卡向导算好的完整角色数据。 */
export interface UpdateCharacterInput {
  name: string;
  /** 属性键位用大写，如 STR/CON/POW/DEX/APP/SIZ/INT/EDU。 */
  attributes: Record<string, number>;
  /** 衍生值键位用大写，如 HP/SAN/MP。 */
  derivedStats: Record<string, number>;
  /** 技能名 -> 最终值。 */
  skills: Record<string, number>;
  equipment: CharacterEquipmentItem[];
  occupation: string | null;
  background: string;
  notes: string;
}

/** POST /api/v1/rooms/{roomId}/characters 返回 */
export interface CharacterDraftResult {
  characterId: string;
  status: string;
}

// ──────────────────────────────────────────────
// WebSocket（issue #60）— 与后端 app/controller/ws.py 手动保持同步
// 连接地址 `{wsBaseUrl}/ws/{roomId}?token=`，不走 ApiResponse 信封。
// ──────────────────────────────────────────────

/** room.join 事件 payload */
export interface RoomJoinPayload {
  roomCode: string;
  nickname?: string;
}

/** player.ready 事件 payload */
export interface PlayerReadyPayload {
  ready: boolean;
}

/** action.submit 事件 payload */
export interface ActionSubmitPayload {
  utterance: string;
}

/** session.bound 推送 payload */
export interface SessionBoundPayload {
  roomId: string;
  playerId: string;
}

/** narration.push 推送 payload */
export interface NarrationPushPayload {
  text: string;
}

/** 服务端推送的事件信封：`{type, payload}`。 */
export type ServerToClientEvent =
  | { type: 'session.bound'; payload: SessionBoundPayload }
  | { type: 'narration.push'; payload: NarrationPushPayload };
