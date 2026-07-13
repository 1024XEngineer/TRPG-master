import { apiRequest } from './api-client'
import type {
  GameActionRequest,
  GameActionResponse,
  CheckResultRequest,
  CheckResultResponse,
  ApiResponse,
} from './types'

// 玩家行动
export async function performAction(
  roomCode: string,
  action: GameActionRequest
): Promise<GameActionResponse> {
  const res = await apiRequest<ApiResponse<GameActionResponse>>(
    `/game/${roomCode}/action`,
    { method: 'POST', body: action }
  )
  return res.data
}

// 提交检定结果
export async function submitCheckResult(
  roomCode: string,
  result: CheckResultRequest
): Promise<CheckResultResponse> {
  const res = await apiRequest<ApiResponse<CheckResultResponse>>(
    `/game/${roomCode}/check`,
    { method: 'POST', body: result }
  )
  return res.data
}

// 获取游戏状态
export async function getGameState(roomCode: string): Promise<unknown> {
  const res = await apiRequest<ApiResponse<unknown>>(
    `/game/${roomCode}/state`
  )
  return res.data
}

// 获取可用场景
export async function getAvailableActions(
  roomCode: string
): Promise<string[]> {
  const res = await apiRequest<ApiResponse<string[]>>(
    `/game/${roomCode}/actions`
  )
  return res.data
}

// 游戏历史
export async function getGameHistory(
  roomCode: string,
  since?: string
): Promise<unknown[]> {
  const params = since ? `?since=${since}` : ''
  const res = await apiRequest<ApiResponse<unknown[]>>(
    `/game/${roomCode}/history${params}`
  )
  return res.data
}
