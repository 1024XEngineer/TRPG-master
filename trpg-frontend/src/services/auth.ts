import { getAuthToken, sdk, setAuthToken } from './api-client';

export interface AuthResult {
  userId: string;
  token: string;
}

// 注册（account+password，见 ADR-16：登录是玩游戏的硬性前提，不再是可选层）
export async function register(
  account: string,
  password: string,
  nickname: string
): Promise<AuthResult> {
  const res = await sdk.auth.register({ account, password, nickname });
  setAuthToken(res.token);
  return { userId: res.userId, token: res.token };
}

// 登录
export async function login(account: string, password: string): Promise<AuthResult> {
  const res = await sdk.auth.login({ account, password });
  setAuthToken(res.token);
  return { userId: res.userId, token: res.token };
}

// 登出
export async function logout() {
  const token = getAuthToken();
  try {
    if (token) await sdk.auth.logout(token);
  } finally {
    setAuthToken(null);
  }
}

export interface MeResult {
  userId: string;
  account: string;
  nickname: string;
}

// 检查登录状态
export async function fetchMe(): Promise<MeResult | null> {
  const token = getAuthToken();
  if (!token) return null;
  try {
    return await sdk.auth.getMe(token);
  } catch {
    return null;
  }
}

// 修改个人信息（目前只支持改昵称）
export async function updateProfile(nickname: string): Promise<MeResult> {
  const token = getAuthToken();
  if (!token) throw new Error('未登录');
  return sdk.auth.updateNickname({ nickname }, token);
}
