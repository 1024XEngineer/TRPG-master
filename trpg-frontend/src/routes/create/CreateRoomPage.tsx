import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, Plus, Minus } from 'lucide-react'
import { GAME_REGISTRY, SYSTEM_COLORS, getScenarioById } from '@/config/games'
import { useGameStore } from '@/stores/game-store'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { createGameRoom, listModules, selectModule } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'

const MIN_PLAYERS = 1
// 后端 RoomCreate.max_players 的校验是 le=20（trpg-backend/app/dto/room.py），
// 这里的加减号/输入框都要跟着限制到 20，否则提交时只会收到一个 422（见
// PR #67 review）。
const MAX_PLAYERS = 20

export default function CreateRoomPage() {
  const navigate = useNavigate()
  const store = useGameStore()
  const nickname = useAuthStore((s) => s.nickname)
  const setRoomIdentity = useRoomStore((s) => s.setRoomIdentity)
  const setStoreModuleId = useRoomStore((s) => s.setModuleId)
  const setCreateForm = useRoomStore((s) => s.setCreateForm)
  const setHost = useRoomStore((s) => s.setHost)
  const savedRoomName = useRoomStore((s) => s.createFormRoomName)
  const savedMaxPlayers = useRoomStore((s) => s.createFormMaxPlayers)
  const [roomName, setRoomName] = useState(savedRoomName || '')
  const [maxPlayers, setMaxPlayers] = useState(savedMaxPlayers || 4)
  const [maxPlayersInput, setMaxPlayersInput] = useState(String(savedMaxPlayers || 4))
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const selectedGame = store.gameId ? GAME_REGISTRY.find(g => g.id === store.gameId) : null
  const sysColors = store.systemId ? SYSTEM_COLORS[store.systemId] : null
  const selectedScenario = store.sceneId ? getScenarioById(store.sceneId) : null
  const hasSelection = !!(store.gameId && store.systemId && store.sceneId)

  const handleCreate = async () => {
    if (!roomName.trim() || !hasSelection) return
    setCreating(true)
    setCreateError('')
    try {
      const room = await createGameRoom(nickname || undefined, roomName.trim(), maxPlayers)
      // 必须先把房间身份（含 reconnectToken）写进 store，selectModule 等
      // 需要重连凭证的接口才能读到它——见 issue #66，真机联调时发现的顺序 bug。
      setRoomIdentity(room)
      const modules = await listModules()
      if (modules.length === 0) throw new Error('暂无可用模组')
      // 目前只有一款内置模拟模组，不管前端选的是哪张模组卡都用它
      await selectModule(room.roomId, modules[0].id)
      setStoreModuleId(modules[0].id)
      setHost(true)
      navigate('/room/lobby')
    } catch (err) {
      setCreateError(friendlyErrorMessage(err, '创建房间失败'))
    } finally {
      setCreating(false)
    }
  }

  const canCreate = roomName.trim().length > 0 && hasSelection && !creating

  const handleSelectGame = () => {
    setCreateForm({ roomName, maxPlayers })
    store.reset()
    store.setReturnFromGameSelect(true)
    navigate('/home/create/games')
  }

  const handleChangeGame = () => {
    setCreateForm({ roomName, maxPlayers })
    store.reset()
    store.setReturnFromGameSelect(true)
    navigate('/home/create/games')
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-24">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => { store.reset(); setCreateForm({ roomName: '', maxPlayers: 4 }); navigate('/home') }} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">创建房间</h2>
      </div>

      <div className="px-5 space-y-3.5">
        {/* ── Room Settings ── */}
        <div className="bg-card border border-border-light rounded-md p-[18px]">
          <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3.5">房间设置</h4>
          <div className="space-y-3">
            <div>
              <label className="text-[11px] font-medium text-text-muted mb-1 block">房间名称</label>
              <input value={roomName} onChange={e => setRoomName(e.target.value)}
                placeholder="例如：阿卡姆调查团" className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
            </div>
            <div>
              <label className="text-[11px] font-medium text-text-muted mb-1 block">最大人数</label>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => {
                    const next = Math.max(MIN_PLAYERS, maxPlayers - 1)
                    setMaxPlayers(next)
                    setMaxPlayersInput(String(next))
                  }}
                  disabled={maxPlayers <= MIN_PLAYERS}
                  className="w-10 h-10 rounded-[6px] bg-input border border-border-light text-text-muted flex items-center justify-center active:bg-panel disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                  <Minus className="w-[16px] h-[16px]" />
                </button>
                <div className="flex-1 flex items-center justify-center gap-1">
                  <input
                    type="number"
                    inputMode="numeric"
                    min={MIN_PLAYERS}
                    max={MAX_PLAYERS}
                    value={maxPlayersInput}
                    onChange={e => setMaxPlayersInput(e.target.value)}
                    onBlur={() => {
                      const v = parseInt(maxPlayersInput, 10)
                      const clamped = Number.isNaN(v)
                        ? maxPlayers
                        : Math.min(MAX_PLAYERS, Math.max(MIN_PLAYERS, v))
                      setMaxPlayers(clamped)
                      setMaxPlayersInput(String(clamped))
                    }}
                    className="w-16 text-center text-lg font-semibold font-mono text-text-primary bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <span className="text-sm text-text-muted">人</span>
                </div>
                <button
                  onClick={() => {
                    const next = Math.min(MAX_PLAYERS, maxPlayers + 1)
                    setMaxPlayers(next)
                    setMaxPlayersInput(String(next))
                  }}
                  disabled={maxPlayers >= MAX_PLAYERS}
                  className="w-10 h-10 rounded-[6px] bg-input border border-border-light text-text-muted flex items-center justify-center active:bg-panel disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                  <Plus className="w-[16px] h-[16px]" />
                </button>
              </div>
              <p className="text-[10px] text-text-dim mt-1.5">最多 {MAX_PLAYERS} 人</p>
            </div>
          </div>
        </div>

        {/* ── Select Game ── */}
        <div className="bg-card border border-border-light rounded-md p-[18px]">
          <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3.5">选择游戏</h4>

          {hasSelection ? (
            <div>
              <div className="flex items-center gap-3 px-3.5 py-3 rounded-[6px] bg-[#fdfaf4] border border-brass mb-2">
                <div className="w-10 h-10 rounded-[10px] bg-[#eef3f8] flex items-center justify-center text-lg">
                  {selectedScenario?.nameEn?.charAt(0) || '🎮'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-text-primary">{selectedGame?.name} · {sysColors?.name}</div>
                  <div className="text-xs text-text-muted mt-0.5">模组：{selectedScenario?.name}</div>
                </div>
                <button onClick={handleChangeGame}
                  className="text-[11px] text-text-dim underline whitespace-nowrap">更换</button>
              </div>
            </div>
          ) : (
            <div className="text-center">
              <p className="text-xs text-text-muted mb-3">选择一个游戏、规则和模组</p>
              <button onClick={handleSelectGame}
                className="w-full py-3 rounded-[6px] border-2 border-dashed border-border-mid text-text-muted text-sm font-medium bg-transparent active:bg-panel transition-all flex items-center justify-center gap-2">
                <Plus className="w-[18px] h-[18px]" />
                选择游戏
              </button>
            </div>
          )}

        </div>

        {/* ── Room Summary ── */}
        <div className="bg-card border border-border-light rounded-md p-[18px]">
          <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">房间概览</h4>
          <div className="space-y-2 text-sm text-text-body">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">房间名</span>
              <span className="font-semibold text-text-primary">{roomName || '未设置'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-muted">游戏</span>
              <span className="text-text-primary">{selectedGame?.name || (store.gameId || '未选择')}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-muted">规则</span>
              <span className="text-text-primary">{sysColors?.name || (store.systemId || '未选择')}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-muted">模组</span>
              <span className="text-text-primary">{selectedScenario?.name || '未选择'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-text-muted">人数上限</span>
              <span className="text-text-primary">{maxPlayers} 人</span>
            </div>
          </div>
        </div>
      </div>

      <div className="fixed bottom-0 left-0 right-0 bg-page border-t border-border-light px-5 py-3 max-w-[430px] mx-auto z-20">
        {createError && <p className="text-[11px] text-[#c04040] text-center mb-2">{createError}</p>}
        <button onClick={handleCreate} disabled={!canCreate}
          className={`w-full py-3.5 rounded-sm text-sm font-semibold transition-all flex items-center justify-center gap-2 ${
            canCreate ? 'bg-brass text-white active:bg-brass-dark active:scale-[0.97]' : 'bg-border-light text-text-dim cursor-not-allowed'
          }`}>
          <Plus className="w-[18px] h-[18px]" /> {creating ? '创建中…' : '创建房间'}
        </button>
      </div>
    </div>
  )
}
