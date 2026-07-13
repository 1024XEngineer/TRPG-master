import { apiRequest, setAuthToken } from './api-client'

export interface AuthResult {
  userId: string
  token: string
}

// 注册（account+password，见 ADR-16：登录是玩游戏的硬性前提，不再是可选层）
export async function register(account: string, password: string, nickname: string): Promise<AuthResult> {
  const res = await apiRequest<AuthResult>('/auth/register', {
    method: 'POST',
    body: { account, password, nickname },
  })
  setAuthToken(res.token)
  return res
}

// 登录
export async function login(account: string, password: string): Promise<AuthResult> {
  const res = await apiRequest<AuthResult>('/auth/login', {
    method: 'POST',
    body: { account, password },
  })
  setAuthToken(res.token)
  return res
}

// 登出
export async function logout() {
  try {
    await apiRequest('/auth/logout', { method: 'POST' })
  } finally {
    setAuthToken(null)
  }
}

export interface MeResult {
  userId: string
  account: string
  nickname: string
}

// 检查登录状态
export async function fetchMe(): Promise<MeResult | null> {
  try {
    return await apiRequest<MeResult>('/auth/me')
  } catch {
    return null
  }
}
