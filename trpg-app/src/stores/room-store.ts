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
  roomId: string | null
  roomCode: string | null
  playerId: string | null
  reconnectToken: string | null
  moduleId: string | null
  characterId: string | null
  players: Player[]
  isConnected: boolean
  setRoom: (code: string, players: Player[]) => void
  setRoomIdentity: (info: { roomId: string; roomCode: string; playerId: string; reconnectToken: string }) => void
  setModuleId: (moduleId: string) => void
  setCharacterId: (characterId: string) => void
  addPlayer: (player: Player) => void
  removePlayer: (playerId: string) => void
  setPlayerReady: (playerId: string, ready: boolean) => void
  setConnected: (connected: boolean) => void
  reset: () => void
}

export const useRoomStore = create<RoomState>((set) => ({
  roomId: null,
  roomCode: null,
  playerId: null,
  reconnectToken: null,
  moduleId: null,
  characterId: null,
  players: [],
  isConnected: false,
  setRoom: (code, players) => set({ roomCode: code, players }),
  setRoomIdentity: ({ roomId, roomCode, playerId, reconnectToken }) =>
    set({ roomId, roomCode, playerId, reconnectToken }),
  setModuleId: (moduleId) => set({ moduleId }),
  setCharacterId: (characterId) => set({ characterId }),
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
  reset: () =>
    set({
      roomId: null,
      roomCode: null,
      playerId: null,
      reconnectToken: null,
      moduleId: null,
      characterId: null,
      players: [],
      isConnected: false,
    }),
}))
