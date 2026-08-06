import { create } from 'zustand'

export type GamePhase = 'lobby' | 'playing' | 'paused' | 'ended'

interface GameState {
  sceneId: string | null
  phase: GamePhase
  setScene: (sceneId: string) => void
  setPhase: (phase: GamePhase) => void
  reset: () => void
}

export const useGameStore = create<GameState>((set) => ({
  sceneId: null,
  phase: 'lobby',
  setScene: (sceneId) => set({ sceneId }),
  setPhase: (phase) => set({ phase }),
  reset: () =>
    set({
      sceneId: null,
      phase: 'lobby',
    }),
}))
