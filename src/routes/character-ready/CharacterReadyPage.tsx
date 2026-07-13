import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, UserPlus, Swords, Eye } from 'lucide-react'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { getSkillById, calculateBaseValue } from '@/data/skills'
import { ATTRIBUTE_LABELS } from '@/data/character-model'
import { disconnectWebSocket } from '@/services/api-client'


const ATTR_KEY_LIST = ['str', 'con', 'pow', 'dex', 'app', 'siz', 'int', 'edu'] as const

function CharacterSheetModal({ character, onClose }: { character: NonNullable<ReturnType<typeof useCharacterStore.getState>['character']>; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-30 animate-fade-in" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 z-40 bg-card rounded-t-2xl animate-slide-up max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h3 className="text-base font-bold text-text-primary">调查员 · {character.info.name}</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center">
            <svg className="w-4 h-4 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-5 pb-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-14 rounded-sm flex items-center justify-center text-2xl"
              style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}>
              🕵️
            </div>
            <div>
              <div className="font-bold text-text-primary text-[17px]">{character.info.name}</div>
              <div className="text-xs text-text-muted">{character.info.age}岁 · {character.info.gender}</div>
            </div>
          </div>
          <div className="flex gap-2">
            {[
              { label: 'HP', value: `${character.derived.hp}`, color: 'text-mold' },
              { label: 'SAN', value: `${character.derived.san}`, color: 'text-[#7050a0]' },
              { label: 'MP', value: `${character.derived.mp}`, color: 'text-[#4a7098]' },
              { label: 'DB', value: character.derived.db, color: 'text-text-muted' },
              { label: 'MOV', value: `${character.derived.move}`, color: 'text-text-muted' },
            ].map(pill => (
              <div key={pill.label} className="flex-1 bg-panel rounded-md px-2.5 py-2 text-center">
                <div className="text-[10px] text-text-muted font-semibold">{pill.label}</div>
                <div className={`text-[16px] font-bold font-mono ${pill.color}`}>{pill.value}</div>
              </div>
            ))}
          </div>
          <div>
            <h4 className="text-[11px] font-semibold text-brass-dark mb-2">基础属性</h4>
            <div className="grid grid-cols-2 gap-1.5">
              {ATTR_KEY_LIST.map(key => (
                <div key={key} className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                  <span className="font-mono text-[11px] font-bold text-text-muted">{ATTRIBUTE_LABELS[key].short}</span>
                  <span className="font-mono text-sm font-bold text-text-primary">{character.attr[key]}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h4 className="text-[11px] font-semibold text-brass-dark mb-2">已分配技能</h4>
            <div className="flex flex-wrap gap-x-3 gap-y-1.5">
              {Object.entries(character.skillAlloc).filter(([, v]) => v > 0).map(([id, pts]) => {
                const skill = getSkillById(id)
                if (!skill) return null
                const base = calculateBaseValue(skill, character.attr)
                return (
                  <span key={id} className="text-[11px] font-mono bg-panel px-2.5 py-1 rounded-full text-text-muted border border-border-light">
                    {skill.name} <span className="font-bold text-text-primary">{base + pts}%</span>
                  </span>
                )
              })}
              {Object.keys(character.skillAlloc).filter(k => (character.skillAlloc[k] || 0) > 0).length === 0 && (
                <span className="text-[11px] text-text-dim">暂无技能分配</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default function CharacterReadyPage() {
  const navigate = useNavigate()
  const [showSelfSheet, setShowSelfSheet] = useState(false)
  const [starting, setStarting] = useState(false)
  const { character } = useCharacterStore()
  const roomCode = useRoomStore((s) => s.roomCode)
  const nickname = useAuthStore((s) => s.nickname)
  const hasCharacter = character !== null

  const handleStartGame = () => {
    setStarting(true)
    navigate('/room')
  }

  const handleEditCharacter = () => {
    navigate('/character', { state: { fromCharacterReady: true } })
  }

  const handleGoBack = () => {
    disconnectWebSocket()
    navigate('/login')
  }

  return (
    <div className="animate-screen-in px-5 pt-6">
      {/* Header */}
      <button
        onClick={handleGoBack}
        className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150 mb-3"
      >
        <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
      </button>

      <div className="flex items-center justify-center gap-2 mb-1">
        <span className="font-mono text-2xl font-bold text-text-primary tracking-[0.15em] bg-card border border-dashed border-border-mid px-4 py-1.5 rounded-sm">
          {roomCode || '------'}
        </span>
      </div>
      <p className="text-center text-xs text-text-muted mb-5">
        人物卡准备 · 等待所有玩家创建角色
      </p>

      {/* Player List */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md">
          <div className={`w-10 h-10 rounded-full bg-panel border border-border-mid flex items-center justify-center text-lg flex-shrink-0 ${hasCharacter ? 'border-brass' : 'border-dashed border-border-light'}`}>
            {hasCharacter ? '🔍' : '○'}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-text-primary">{nickname || '你'}</div>
            <div className="text-xs text-text-muted">
              {hasCharacter ? (
                <span className="text-mold">人物卡：{character!.info.name}</span>
              ) : (
                <span className="text-text-dim">尚未创建人物卡</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {hasCharacter ? (
              <>
                <button onClick={() => setShowSelfSheet(true)}
                  className="text-[11px] font-semibold px-2 py-1 rounded-[99px] bg-brass/10 text-brass-dark flex items-center gap-1 active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap cursor-pointer">
                  <Eye className="w-3 h-3" /> 查看
                </button>
                <button onClick={handleEditCharacter}
                  className="text-[11px] font-semibold px-2 py-1 rounded-[99px] bg-panel text-text-muted active:scale-[0.95] transition-all border border-border-light font-sans whitespace-nowrap cursor-pointer">
                  编辑
                </button>
              </>
            ) : (
              <button onClick={handleEditCharacter}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-[99px] bg-brass text-white flex items-center gap-1 active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap cursor-pointer">
                <UserPlus className="w-3 h-3" /> 创建人物卡
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Waiting message */}
      <p className="text-center text-xs text-text-muted mt-6 mb-4">
        将房间号分享给好友，让他们加入游戏并创建角色
      </p>

      {/* Start Game Button (host only) */}
      <button
        onClick={handleStartGame}
        disabled={!hasCharacter || starting}
        className="w-full mt-2 px-6 py-3.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all disabled:opacity-50 flex items-center justify-center gap-2"
      >
        <Swords className="w-4 h-4" />
        {starting ? '进入中…' : '开始游戏'}
      </button>

      {/* Character Sheet Modal */}
      {showSelfSheet && character && (
        <CharacterSheetModal character={character} onClose={() => setShowSelfSheet(false)} />
      )}
    </div>
  )
}
