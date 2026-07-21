import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

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
  isHost: boolean
  // 创建房间页的表单草稿（房间名/人数上限），跨导航保留已填内容。
  createFormRoomName: string
  createFormMaxPlayers: number
  setRoom: (code: string, players: Player[]) => void
  setRoomIdentity: (info: { roomId: string; roomCode: string; playerId: string; reconnectToken: string }) => void
  setModuleId: (moduleId: string) => void
  setCharacterId: (characterId: string) => void
  addPlayer: (player: Player) => void
  removePlayer: (playerId: string) => void
  setPlayerReady: (playerId: string, ready: boolean) => void
  setConnected: (connected: boolean) => void
  setHost: (host: boolean) => void
  setCreateForm: (data: { roomName?: string; maxPlayers?: number }) => void
  reset: () => void
}

// ★ 用 sessionStorage 持久化房间身份（roomId/playerId/roomCode/isHost 等）——
// 否则页面一刷新这些全部归零，大厅/建卡向导直接死锁（见 2026-07-13 测试报告 P0）。
// 用 sessionStorage 而不是 localStorage：房间会话只该活在当前标签页/会话内，
// 不应该跨浏览器重启残留一个早就结束的房间身份。
export const useRoomStore = create<RoomState>()(
  persist(
    (set) => ({
      roomId: null,
      roomCode: null,
      playerId: null,
      reconnectToken: null,
      moduleId: null,
      characterId: null,
      players: [],
      isConnected: false,
      isHost: false,
      createFormRoomName: '',
      createFormMaxPlayers: 4,
      setRoom: (code, players) => set({ roomCode: code, players }),
      setRoomIdentity: ({ roomId, roomCode, playerId, reconnectToken }) =>
        set((state) => ({
          roomId,
          roomCode,
          playerId,
          reconnectToken,
          // 换到别的房间就丢掉上一个房间的角色 id：角色卡是按房间隔离的
          // （后端 `_get_own_character` 校验 `character.room_id`），带过去只会
          // 404。创建房间那条路径本来就会先 reset()，但"加入房间"和"我的游戏
          // →继续"不会，同一个标签页里换个房间就会留着上一局的 characterId。
          ...(state.roomId !== roomId ? { characterId: null } : {}),
        })),
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
      setHost: (host) => set({ isHost: host }),
      setCreateForm: (data) =>
        set((state) => ({
          createFormRoomName: data.roomName ?? state.createFormRoomName,
          createFormMaxPlayers: data.maxPlayers ?? state.createFormMaxPlayers,
        })),
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
          isHost: false,
          createFormRoomName: '',
          createFormMaxPlayers: 4,
        }),
    }),
    { name: 'aidm-room', storage: createJSONStorage(() => sessionStorage) }
  )
)
