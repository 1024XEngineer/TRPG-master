import { apiRequest, setAuthToken } from './api-client'
import type { LoginRequest, LoginResponse, ApiResponse } from './types'

// 登录 / 扫码加入
export async function loginWithQR(data: LoginRequest): Promise<LoginResponse> {
  const res = await apiRequest<ApiResponse<LoginResponse>>('/auth/qr-login', {
    method: 'POST',
    body: data,
  })
  if (res.data?.token) {
    setAuthToken(res.data.token)
  }
  return res.data
}

// 创建房间（同时登录）
export async function createRoom(nickname: string): Promise<LoginResponse> {
  const res = await apiRequest<ApiResponse<LoginResponse>>('/auth/create-room', {
    method: 'POST',
    body: { nickname },
  })
  if (res.data?.token) {
    setAuthToken(res.data.token)
  }
  return res.data
}

// 登出
export function logout() {
  setAuthToken(null)
}

// 检查登录状态
export async function checkSession(): Promise<boolean> {
  try {
    await apiRequest('/auth/session')
    return true
  } catch {
    return false
  }
}
