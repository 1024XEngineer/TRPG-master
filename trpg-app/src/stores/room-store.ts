import { create } from 'zustand'

export interface Player {
  id: string
  nickname: string
  characterName: string | null
  isReady: boolean
  isHost: boolean
  isAi: boolean
}

interface RoomState {
  roomCode: string | null
  players: Player[]
  isConnected: boolean
  setRoom: (code: string, players: Player[]) => void
  addPlayer: (player: Player) => void
  removePlayer: (playerId: string) => void
  setPlayerReady: (playerId: string, ready: boolean) => void
  setConnected: (connected: boolean) => void
  reset: () => void
}

export const useRoomStore = create<RoomState>((set) => ({
  roomCode: null,
  players: [],
  isConnected: false,
  setRoom: (code, players) => set({ roomCode: code, players }),
  addPlayer: (player) =>
    set((state) => ({ players: [...state.players, player] })),
  removePlayer: (playerId) =>
    set((state) => ({
      players: state.players.filter((p) => p.id !== playerId),
    })),
  setPlayerReady: (playerId, ready) =>
    set((state) => ({
      players: state.players.map((p) =>
        p.id === playerId ? { ...p, isReady: ready } : p
      ),
    })),
  setConnected: (connected) => set({ isConnected: connected }),
  reset: () => set({ roomCode: null, players: [], isConnected: false }),
}))
