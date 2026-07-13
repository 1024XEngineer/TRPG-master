import { create } from 'zustand'

interface AuthState {
  token: string | null
  userId: string | null
  nickname: string | null
  isLoggedIn: boolean
  login: (token: string, userId: string, nickname: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  userId: null,
  nickname: null,
  isLoggedIn: false,
  login: (token, userId, nickname) =>
    set({ token, userId, nickname, isLoggedIn: true }),
  logout: () =>
    set({ token: null, userId: null, nickname: null, isLoggedIn: false }),
}))
