import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { UserPlus, ArrowLeft, ScrollText, X } from 'lucide-react'
import { useCharacterStore } from '@/stores/character-store'
import { getSkillById, calculateBaseValue } from '@/data/skills'
import { ATTRIBUTE_LABELS } from '@/data/character-model'

const ATTR_KEYS = ['str', 'con', 'pow', 'dex', 'app', 'siz', 'int', 'edu'] as const

const PLAYERS = [
  { name: '杰克·布朗', role: '私家侦探 · 调查员', status: 'ready' as const },
  { name: '等待中…', role: '空缺', status: 'waiting' as const },
  { name: '等待中…', role: '空缺', status: 'waiting' as const },
  { name: 'AI 调查员', role: '自动补位', status: 'ai' as const },
]

export default function LobbyPage() {
  const navigate = useNavigate()
  const [showSheet, setShowSheet] = useState<number | null>(null)
  const { character } = useCharacterStore()

  return (
    <div className="animate-screen-in px-5 pt-6">
      <button
        onClick={() => navigate('/character')}
        className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150 mb-3"
      >
        <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
      </button>
      <div className="flex items-center justify-center gap-2 mb-1">
        <span className="font-mono text-2xl font-bold text-text-primary tracking-[0.15em] bg-card border border-dashed border-border-mid px-4 py-1.5 rounded-sm">
          AR-1927
        </span>
      </div>
      <p className="text-center text-xs text-text-muted mb-5">等待大厅 · 1/4 人已就绪</p>

      <div className="flex flex-col gap-2">
        {PLAYERS.map((p, i) => (
          <div key={i} className="flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md">
            <div className={`
              w-10 h-10 rounded-full bg-panel border border-border-mid flex items-center justify-center text-lg flex-shrink-0
              ${p.status === 'ready' ? 'border-brass' : ''}
              ${p.status === 'ai' ? 'border-ink-blue' : ''}
            `}>
              {p.status === 'ready' ? '🔍' : p.status === 'ai' ? '🤖' : '○'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-text-primary">{p.name}</div>
              <div className="text-xs text-text-muted">{p.role}</div>
            </div>
            <div className="flex items-center gap-2">
              {p.status === 'waiting' ? (
                <button className="flex items-center gap-1 text-[11px] font-semibold px-2.5 py-[5px] rounded-[99px] bg-brass text-white cursor-pointer active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap">
                  <UserPlus className="w-3 h-3" />
                  加入
                </button>
              ) : (
                <>
                  {p.status === 'ready' && character && (
                    <button onClick={() => setShowSheet(i)}
                      className="text-[11px] font-semibold px-2 py-1 rounded-[99px] bg-brass/10 text-brass-dark flex items-center gap-1 active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap cursor-pointer">
                      <ScrollText className="w-3 h-3" /> 角色卡
                    </button>
                  )}
                  <span className={`
                    text-[11px] font-semibold px-2.5 py-[3px] rounded-[99px]
                    ${p.status === 'ready' ? 'bg-[rgba(74,138,74,0.12)] text-mold' : ''}
                    ${p.status === 'ai' ? 'bg-[rgba(74,112,152,0.12)] text-ink-blue' : ''}
                  `}>
                    {p.status === 'ready' ? '已就绪' : 'AI 队友'}
                  </span>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={() => navigate('/story')}
        className="w-full mt-5 px-6 py-3.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all"
      >
        开始游戏 (1/3 人已就绪)
      </button>

      {/* Character Sheet Modal */}
      {showSheet !== null && character && (
        <>
          <div className="fixed inset-0 bg-black/50 z-30 animate-fade-in" onClick={() => setShowSheet(null)} />
          <div className="fixed inset-x-0 bottom-0 z-40 bg-card rounded-t-2xl animate-slide-up max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 pt-4 pb-2">
              <h3 className="text-base font-bold text-text-primary">调查员 · {character.info.name}</h3>
              <button onClick={() => setShowSheet(null)} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center">
                <X className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
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
                  {ATTR_KEYS.map(key => (
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
      )}
    </div>
  )
}
