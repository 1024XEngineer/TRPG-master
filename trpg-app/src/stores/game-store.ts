import { create } from 'zustand'

export type GamePhase = 'lobby' | 'playing' | 'paused' | 'ended'

interface GameState {
  gameId: string | null
  systemId: string | null
  sceneId: string | null
  phase: GamePhase
  returnFromGameSelect: boolean
  setGame: (gameId: string, systemId: string) => void
  setScene: (sceneId: string) => void
  setPhase: (phase: GamePhase) => void
  setReturnFromGameSelect: (v: boolean) => void
  reset: () => void
}

export const useGameStore = create<GameState>((set) => ({
  gameId: null,
  systemId: null,
  sceneId: null,
  phase: 'lobby',
  returnFromGameSelect: false,
  setGame: (gameId, systemId) => set({ gameId, systemId }),
  setScene: (sceneId) => set({ sceneId }),
  setPhase: (phase) => set({ phase }),
  setReturnFromGameSelect: (v) => set({ returnFromGameSelect: v }),
  reset: () =>
    set({
      gameId: null,
      systemId: null,
      sceneId: null,
      phase: 'lobby',
      returnFromGameSelect: false,
    }),
}))
