// API 请求/响应类型定义
// 后续由后端实现后替换为真实接口

export interface ApiResponse<T> {
  ok: boolean
  data: T
  error?: string
}

export interface LoginRequest {
  roomCode?: string
  nickname?: string
}

export interface LoginResponse {
  token: string
  userId: string
  nickname: string
}

export interface CreateRoomRequest {
  gameId: string
  systemId: string
  scenarioId?: string
  maxPlayers: number
}

export interface RoomResponse {
  roomCode: string
  players: Array<{
    id: string
    nickname: string
    characterName: string | null
    isReady: boolean
    isHost: boolean
    isAi: boolean
  }>
}

export interface JoinRoomRequest {
  roomCode: string
  nickname: string
}

export interface GameActionRequest {
  type: 'move' | 'search' | 'talk' | 'use' | 'attack' | 'observe'
  target: string
  method?: string
}

export interface GameActionResponse {
  narration: string
  checkRequired?: {
    skill: string
    difficulty: 'normal' | 'hard' | 'extreme'
    target: number
  }
  sceneTransition?: string
}

export interface CheckResultRequest {
  skill: string
  roll: number
}

export interface CheckResultResponse {
  success: boolean
  grade: 'critical' | 'hard' | 'normal' | 'fail' | 'fumble'
  narration: string
}

// WebSocket 事件类型
export type WsEventType =
  | 'message'
  | 'player_joined'
  | 'player_left'
  | 'player_ready'
  | 'game_state'
  | 'check_request'
  | 'check_result'
  | 'scene_change'

export interface WsEvent {
  type: WsEventType
  payload: unknown
  timestamp: string
}
