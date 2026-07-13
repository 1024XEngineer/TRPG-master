import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, Plus, Hash } from 'lucide-react'
import { GAME_REGISTRY, SYSTEM_COLORS, getScenarioById } from '@/config/games'
import { useGameStore } from '@/stores/game-store'

const MAX_PLAYERS = [2, 3, 4, 5, 6, 7, 8]

export default function CreateRoomPage() {
  const navigate = useNavigate()
  const store = useGameStore()
  const [roomName, setRoomName] = useState('')
  const [roomCode, setRoomCode] = useState('')
  const [maxPlayers, setMaxPlayers] = useState(4)

  const selectedGame = store.gameId ? GAME_REGISTRY.find(g => g.id === store.gameId) : null
  const sysColors = store.systemId ? SYSTEM_COLORS[store.systemId] : null
  const selectedScenario = store.sceneId ? getScenarioById(store.sceneId) : null
  const hasSelection = !!(store.gameId && store.systemId && store.sceneId)

  const handleCreate = () => {
    if (!roomName.trim() || !roomCode.trim()) return
    navigate('/lobby')
  }

  const canCreate = roomName.trim().length > 0 && roomCode.trim().length >= 1

  const handleSelectGame = () => {
    store.setReturnFromGameSelect(true)
    store.reset()
    navigate('/games')
  }

  const handleChangeGame = () => {
    store.setReturnFromGameSelect(true)
    store.reset()
    navigate('/games')
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-24">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/login')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
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
              <label className="text-[11px] font-medium text-text-muted mb-1 block">房间号（1-4 位数字）</label>
              <div className="relative">
                <Hash className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
                <input value={roomCode}
                  onChange={e => setRoomCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
                  placeholder="例如：1234"
                  inputMode="numeric"
                  maxLength={4}
                  className="w-full pl-8 pr-3 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] font-mono font-bold tracking-[0.1em] outline-none focus:border-brass" />
              </div>
            </div>
            <div>
              <label className="text-[11px] font-medium text-text-muted mb-1 block">最大人数</label>
              <div className="flex gap-1.5">
                {MAX_PLAYERS.map(n => (
                  <button key={n} onClick={() => setMaxPlayers(n)}
                    className={`flex-1 py-2.5 rounded-[6px] text-sm font-semibold font-mono transition-all ${
                      maxPlayers === n ? 'bg-brass text-white' : 'bg-input border border-border-light text-text-muted'
                    }`}>{n}</button>
                ))}
              </div>
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
              <span className="text-text-muted">房间号</span>
              <span className="font-mono font-bold tracking-wider text-text-primary">{roomCode || '未设置'}</span>
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
        <button onClick={handleCreate} disabled={!canCreate}
          className={`w-full py-3.5 rounded-sm text-sm font-semibold transition-all flex items-center justify-center gap-2 ${
            canCreate ? 'bg-brass text-white active:bg-brass-dark active:scale-[0.97]' : 'bg-border-light text-text-dim cursor-not-allowed'
          }`}>
          <Plus className="w-[18px] h-[18px]" /> 创建房间
        </button>
      </div>
    </div>
  )
}
