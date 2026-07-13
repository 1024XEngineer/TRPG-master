import { apiRequest } from './api-client'
import type { CreateRoomRequest, JoinRoomRequest, RoomResponse, ApiResponse } from './types'

// 创建房间
export async function createGameRoom(data: CreateRoomRequest): Promise<RoomResponse> {
  const res = await apiRequest<ApiResponse<RoomResponse>>('/room/create', {
    method: 'POST',
    body: data,
  })
  return res.data
}

// 加入房间
export async function joinRoom(data: JoinRoomRequest): Promise<RoomResponse> {
  const res = await apiRequest<ApiResponse<RoomResponse>>('/room/join', {
    method: 'POST',
    body: data,
  })
  return res.data
}

// 获取房间信息
export async function getRoomInfo(roomCode: string): Promise<RoomResponse> {
  const res = await apiRequest<ApiResponse<RoomResponse>>(`/room/${roomCode}`)
  return res.data
}

// 设置准备状态
export async function setPlayerReady(roomCode: string, ready: boolean): Promise<void> {
  await apiRequest(`/room/${roomCode}/ready`, {
    method: 'POST',
    body: { ready },
  })
}

// 离开房间
export async function leaveRoom(roomCode: string): Promise<void> {
  await apiRequest(`/room/${roomCode}/leave`, { method: 'POST' })
}

// 开始游戏（房主）
export async function startGame(roomCode: string): Promise<void> {
  await apiRequest(`/room/${roomCode}/start`, { method: 'POST' })
}
