import { apiRequest } from './api-client'

export interface CreateRoomResult {
  roomId: string
  roomCode: string
  reconnectToken: string
  playerId: string
}

// 创建房间（房主创建即加入，见 §5.2.5）
export async function createGameRoom(nickname?: string): Promise<CreateRoomResult> {
  return apiRequest<CreateRoomResult>('/rooms', {
    method: 'POST',
    body: { nickname },
  })
}

export interface ModuleSummary {
  id: string
  title: string
  version: string
  authors: string[]
  playersMin: number
  playersMax: number
  difficulty: number
  estimatedDuration?: string | null
}

// 拉取可用模组列表（本次没有做模组导入，只有一款内置模拟模组）
export async function listModules(): Promise<ModuleSummary[]> {
  const res = await apiRequest<{ modules: ModuleSummary[] }>('/modules')
  return res.modules
}

// 房主确定模组
export async function selectModule(roomId: string, moduleId: string): Promise<void> {
  await apiRequest(`/rooms/${roomId}/module`, {
    method: 'POST',
    body: { moduleId, attributeGenMethod: 'point_buy' },
  })
}

// 访客用房间码加入（已是本房间玩家则幂等返回已有身份，见 server/rest/lobby.py join_room）
export async function joinRoomByCode(roomCode: string, nickname?: string): Promise<CreateRoomResult> {
  return apiRequest<CreateRoomResult>(`/rooms/${roomCode}/join`, {
    method: 'POST',
    body: { nickname },
  })
}

export interface RoomPlayerSummary {
  playerId: string
  nickname: string
  isHost: boolean
  ready: boolean
  hasCharacter: boolean
}

export interface RoomPreview {
  roomId: string
  roomCode: string
  phase: string
  moduleTitle: string | null
  playerCount: number
  maxPlayers: number
  players: RoomPlayerSummary[]
}

// 获取房间信息（房间码预览）
export async function getRoomInfo(roomCode: string): Promise<RoomPreview> {
  return apiRequest<RoomPreview>(`/rooms/${roomCode}`)
}
