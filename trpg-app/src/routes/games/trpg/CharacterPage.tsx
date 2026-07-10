import { useNavigate } from 'react-router-dom'
import { useState, useMemo, useEffect } from 'react'
import { ArrowLeft, Plus, Minus, Search, Shield, Heart, Brain, Zap, Eye, Maximize2, Lightbulb, BookOpen, ChevronDown, X, Info } from 'lucide-react'
import { ALL_SKILLS, getSkillById, calculateBaseValue } from '@/data/skills'
import { ATTRIBUTE_LABELS, calculateOccupationSkillPoints, calculateInterestSkillPoints, deriveStats, type Attributes, type InvestigatorInfo } from '@/data/character-model'
import { fetchOccupationGroups, fetchOccupations } from '@/services/character/occupation-service'
import type { OccupationDefinition, OccupationGroup, SkillDefinition } from '@/data/types'

const ATTR_KEYS = ['str', 'con', 'pow', 'dex', 'app', 'siz', 'int', 'edu'] as const

const ATTR_ICONS: Record<string, typeof Heart> = {
  str: Shield, con: Heart, pow: Brain, dex: Zap,
  app: Eye, siz: Maximize2, int: Lightbulb, edu: BookOpen,
}

const ATTR_COLORS: Record<string, string> = {
  str: '#c04040', con: '#c08050', pow: '#7050a0', dex: '#4a8a4a',
  app: '#8a4070', siz: '#b8976a', int: '#4a7098', edu: '#6a6050',
}

// ─── Occupation skill filter helper ──────────────────
function getOccupationById(occupations: OccupationDefinition[], occupationId: number | null): OccupationDefinition | null {
  if (!occupationId) return null
  return occupations.find(occupation => occupation.id === occupationId) ?? null
}

function getOccupationSkillIds(occupations: OccupationDefinition[], occupationId: number | null): string[] {
  return getOccupationById(occupations, occupationId)?.skillIds ?? []
}

function getOccupationsByGroup(occupations: OccupationDefinition[], groups: OccupationGroup[], groupId: string): OccupationDefinition[] {
  const group = groups.find(g => g.label === groupId)
  if (!group) return occupations
  const ids = new Set(group.ids)
  return occupations.filter(occupation => ids.has(occupation.id))
}

// ─── SkillRow Component ──────────────────────────────
function SkillRow({
  skill, attr, allocation, onChange, maxPoints, minPoints
}: {
  skill: SkillDefinition
  attr: Attributes
  allocation: number
  onChange: (delta: number) => void
  maxPoints: number
  minPoints: number
}) {
  const base = calculateBaseValue(skill, attr)
  const current = base + allocation
  const canAdd = allocation < maxPoints && current < 99
  const canSub = allocation > minPoints

  return (
    <div className="flex items-center gap-2.5 px-3 py-2 bg-input border border-border-light rounded-[6px]">
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-medium text-text-primary">{skill.name}</div>
        <div className="text-[10px] text-text-dim font-mono">{skill.nameEn}</div>
      </div>
      <div className="text-[10px] text-text-muted font-mono min-w-[32px] text-center">
        {base}%
      </div>
      <button
        onClick={() => onChange(-1)}
        className={`w-6 h-6 rounded-full flex items-center justify-center transition-all ${
          canSub ? 'bg-card border border-border-light text-text-muted active:bg-panel active:scale-90' : 'bg-transparent text-border-light cursor-not-allowed'
        }`}
        disabled={!canSub}
      >
        <Minus className="w-3 h-3" />
      </button>
      <div className="text-[15px] font-bold font-mono text-text-primary min-w-[28px] text-center">
        {current}
      </div>
      <button
        onClick={() => onChange(1)}
        className={`w-6 h-6 rounded-full flex items-center justify-center transition-all ${
          canAdd ? 'bg-card border border-border-light text-text-muted active:bg-panel active:scale-90' : 'bg-transparent text-border-light cursor-not-allowed'
        }`}
        disabled={!canAdd}
      >
        <Plus className="w-3 h-3" />
      </button>
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────
export default function CharacterPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)

  // Investigator info
  const [info, setInfo] = useState<InvestigatorInfo>({
    name: '', playerName: '', age: '28', gender: '男',
    residence: '阿卡姆', birthplace: '阿卡姆', occupationId: null,
  })

  // Attributes
  const [attr, setAttr] = useState<Attributes>({
    str: 50, con: 50, pow: 50, dex: 50,
    app: 50, siz: 50, int: 50, edu: 50,
  })

  // Skill allocations: skillId -> points spent
  const [skillAlloc, setSkillAlloc] = useState<Record<string, number>>({})

  // Equipment & background
  const [equipment, setEquipment] = useState('')
  const [background, setBackground] = useState('')
  const [notes, setNotes] = useState('')

  // UI state
  const [occupations, setOccupations] = useState<OccupationDefinition[]>([])
  const [occupationGroups, setOccupationGroups] = useState<OccupationGroup[]>([])
  const [occupationLoading, setOccupationLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [skillTab, setSkillTab] = useState<'occupation' | 'interest'>('occupation')
  const [showGroupPicker, setShowGroupPicker] = useState(false)
  const [detailOcc, setDetailOcc] = useState<OccupationDefinition | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadOccupationData() {
      try {
        const [loadedOccupations, loadedGroups] = await Promise.all([
          fetchOccupations(),
          fetchOccupationGroups(),
        ])
        if (cancelled) return
        setOccupations(loadedOccupations)
        setOccupationGroups(loadedGroups)
      } finally {
        if (!cancelled) setOccupationLoading(false)
      }
    }

    loadOccupationData()

    return () => {
      cancelled = true
    }
  }, [])

  const selectedOcc = useMemo(() => {
    return getOccupationById(occupations, info.occupationId)
  }, [occupations, info.occupationId])

  // Filter occupations by search and group
  const filteredOccupations = useMemo(() => {
    let list = activeGroup ? getOccupationsByGroup(occupations, occupationGroups, activeGroup) : occupations
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(o => o.name.toLowerCase().includes(q) || o.shortDesc.toLowerCase().includes(q))
    }
    return list
  }, [activeGroup, occupationGroups, occupations, search])

  // Occupation skill IDs
  const occSkillIds = useMemo(() => getOccupationSkillIds(occupations, info.occupationId), [occupations, info.occupationId])
  const occSkills = useMemo(() => occSkillIds.map(id => getSkillById(id)).filter(Boolean) as SkillDefinition[], [occSkillIds])

  // Skill points
  const occPointsTotal = useMemo(() => {
    if (!selectedOcc) return 0
    return calculateOccupationSkillPoints(selectedOcc.skillPoints, attr)
  }, [selectedOcc, attr])

  const interestPointsTotal = useMemo(() => calculateInterestSkillPoints(attr), [attr])

  const occPointsSpent = useMemo(() => {
    return occSkillIds.reduce((sum, id) => sum + (skillAlloc[id] || 0), 0)
  }, [occSkillIds, skillAlloc])

  const interestPointsSpent = useMemo(() => {
    return Object.entries(skillAlloc).reduce((sum, [id, pts]) => {
      if (!occSkillIds.includes(id)) return sum + pts
      return sum
    }, 0)
  }, [skillAlloc, occSkillIds])

  const derived = useMemo(() => deriveStats(attr), [attr])

  // Skill allocation handler
  const handleSkillChange = (skillId: string, delta: number) => {
    setSkillAlloc(prev => ({
      ...prev,
      [skillId]: Math.max(0, (prev[skillId] || 0) + delta),
    }))
  }

  const handleAttrChange = (key: keyof Attributes, delta: number) => {
    setAttr(prev => ({
      ...prev,
      [key]: Math.max(15, Math.min(99, prev[key] + delta)),
    }))
  }

  const handleSelectOccupation = (occupationId: number | null) => {
    setInfo(current => ({ ...current, occupationId }))
    setSkillAlloc({})
  }

  const steps = [
    { label: '信息', key: 'info', done: step > 0 },
    { label: '属性', key: 'attr', done: step > 1 },
    { label: '技能', key: 'skill', done: step > 2 },
    { label: '完成', key: 'done', done: step > 3 },
  ]

  return (
    <div className="animate-screen-in min-h-screen bg-page">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-page pt-1 pb-0">
        <div className="flex items-center gap-2.5 px-5 pt-0.5">
          <button onClick={() => step > 0 ? setStep(s => s - 1) : navigate(-1)}
            className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all"
          >
            <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
          </button>
          <h2 className="text-lg font-bold text-text-primary">创建角色</h2>
        </div>
        {/* Progress */}
        <div className="flex gap-1.5 px-5 py-3">
          {steps.map((s, i) => (
            <div key={i} className={`flex-1 h-[3px] rounded-[99px] transition-all duration-300 ${
              s.done ? 'bg-brass-dark' : i === step ? 'bg-brass' : 'bg-border-light'
            }`} />
          ))}
        </div>
      </div>

      {/* ═══════════════ Step 0: Info + Occupation ═══════════════ */}
      {step === 0 && (
        <div className="px-5 pb-20 animate-screen-in">
          {/* Basic Info */}
          <div className="bg-card border border-border-light rounded-md p-[18px] mb-3">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3.5">调查员信息</h4>
            <div className="space-y-3">
              <input value={info.name} onChange={e => setInfo(i => ({ ...i, name: e.target.value }))}
                placeholder="角色姓名" className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
              <input value={info.playerName} onChange={e => setInfo(i => ({ ...i, playerName: e.target.value }))}
                placeholder="玩家昵称" className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="text-[11px] font-medium text-text-muted mb-1 block">年龄</label>
                  <input value={info.age} onChange={e => setInfo(i => ({ ...i, age: e.target.value }))}
                    className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-text-muted mb-1 block">性别</label>
                  <select value={info.gender} onChange={e => setInfo(i => ({ ...i, gender: e.target.value }))}
                    className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass">
                    <option>男</option><option>女</option><option>其他</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="text-[11px] font-medium text-text-muted mb-1 block">居住地</label>
                  <input value={info.residence} onChange={e => setInfo(i => ({ ...i, residence: e.target.value }))}
                    className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-text-muted mb-1 block">出生地</label>
                  <input value={info.birthplace} onChange={e => setInfo(i => ({ ...i, birthplace: e.target.value }))}
                    className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                </div>
              </div>
            </div>
          </div>

          {/* Occupation */}
          <div className="bg-card border border-border-light rounded-md p-[18px]">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3.5">选择职业</h4>
            {info.occupationId && selectedOcc && (
              <div className="mb-3.5 px-3 py-2.5 bg-[#fdfaf4] border border-brass rounded-[6px] flex items-center gap-2.5">
                <span className="text-xl">{selectedOcc.icon}</span>
                <div className="flex-1">
                  <div className="text-sm font-semibold text-text-primary">{selectedOcc.name}</div>
                  <div className="text-[11px] text-text-muted">信用 {selectedOcc.creditRange ?? '自定'} · {selectedOcc.skillPoints}</div>
                </div>
                <button onClick={() => handleSelectOccupation(null)} className="text-[11px] text-text-dim underline">更换</button>
              </div>
            )}

            {/* Search + Group filter */}
            <div className="flex gap-2 mb-3">
              <div className="flex-1 relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="搜索职业…" className="w-full pl-8 pr-3 py-2 text-[12px] rounded-[6px] bg-input border border-border-light outline-none focus:border-brass text-text-primary" />
              </div>
              <div className="relative">
                <button onClick={() => setShowGroupPicker(!showGroupPicker)}
                  className="px-3 py-2 text-[12px] rounded-[6px] bg-input border border-border-light text-text-muted flex items-center gap-1 active:bg-panel">
                  {activeGroup || '全部分类'} <ChevronDown className="w-3 h-3" />
                </button>
                {showGroupPicker && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setShowGroupPicker(false)} />
                    <div className="absolute right-0 top-full mt-1 z-20 bg-card border border-border-light rounded-md shadow-lg min-w-[140px] overflow-hidden">
                      <button onClick={() => { setActiveGroup(null); setShowGroupPicker(false) }}
                        className="w-full text-left px-3.5 py-2 text-[12px] text-text-primary hover:bg-panel">
                        全部分类
                      </button>
                      {occupationGroups.map(g => (
                        <button key={g.label} onClick={() => { setActiveGroup(g.label); setShowGroupPicker(false) }}
                          className="w-full text-left px-3.5 py-2 text-[12px] text-text-primary hover:bg-panel flex items-center gap-2">
                          <span>{g.icon}</span> {g.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Occupation grid */}
            <div className="grid grid-cols-2 gap-2 max-h-[320px] overflow-y-auto pr-0.5">
              {occupationLoading && (
                <div className="col-span-2 text-center py-8 text-text-muted text-sm">
                  正在读取职业列表…
                </div>
              )}
              {!occupationLoading && filteredOccupations.length === 0 && (
                <div className="col-span-2 text-center py-8 text-text-muted text-sm">
                  未找到匹配职业
                </div>
              )}
              {filteredOccupations.map(occ => {
                const selected = info.occupationId === occ.id
                return (
                  <div key={occ.id}
                    className={`group relative px-2.5 py-3 bg-input border rounded-[6px] text-center cursor-pointer active:scale-[0.96] transition-all ${
                      selected ? 'border-brass bg-[#fdfaf4] shadow-[0_0_0_2px_rgba(184,151,106,0.15)]' : 'border-border-light'
                    }`}>
                    <button
                      onClick={(e) => { e.stopPropagation(); setDetailOcc(occ); }}
                      className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-[rgba(255,255,255,0.7)] border border-border-light flex items-center justify-center text-text-dim hover:text-text-body transition-all"
                    >
                      <Info className="w-3 h-3" />
                    </button>
                    <div onClick={() => handleSelectOccupation(occ.id)}>
                      <div className="text-[20px] mb-1">{occ.icon}</div>
                      <div className="text-[12px] font-semibold text-text-primary">{occ.name}</div>
                      <div className="text-[9px] text-text-dim mt-0.5 leading-[1.3]">{occ.shortDesc}</div>
                      {selected && (
                        <div className="mt-1 inline-block px-2 py-0.5 bg-brass/10 text-brass-dark text-[9px] rounded-full font-semibold">
                          已选择
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════ Step 1: Attributes ═══════════════ */}
      {step === 1 && (
        <div className="px-5 pb-20 animate-screen-in">
          <div className="bg-card border border-border-light rounded-md p-[18px]">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-1.5">属性分配</h4>
            <p className="text-[11px] text-text-muted mb-3.5">点击 +/- 调整属性值（范围 15-99，每次 ±5）</p>
            <div className="grid grid-cols-1 gap-2">
              {ATTR_KEYS.map(key => {
                const label = ATTRIBUTE_LABELS[key]
                const Icon = ATTR_ICONS[key] || Shield
                const color = ATTR_COLORS[key] || '#b8976a'
                const val = attr[key]
                return (
                  <div key={key} className="flex items-center gap-3 px-3 py-2.5 bg-input border border-border-light rounded-[6px]">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                      <Icon className="w-4 h-4" style={{ color }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-semibold text-text-primary flex items-center gap-1.5">
                        {label.full}
                        <span className="text-[10px] font-mono text-text-dim font-normal">{label.short}</span>
                      </div>
                      <div className="w-full h-1.5 rounded-full bg-border-light mt-1 overflow-hidden">
                        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, val)}%`, backgroundColor: color }} />
                      </div>
                    </div>
                    <button onClick={() => handleAttrChange(key, -5)}
                      className="w-7 h-7 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all"
                    >
                      <Minus className="w-3.5 h-3.5" />
                    </button>
                    <div className="text-[17px] font-bold font-mono text-text-primary min-w-[30px] text-center">{val}</div>
                    <button onClick={() => handleAttrChange(key, 5)}
                      className="w-7 h-7 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all"
                    >
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Derived Stats */}
          <div className="bg-card border border-border-light rounded-md p-[18px] mt-3">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">衍生属性</h4>
            <div className="flex gap-2">
              {[
                { label: 'HP', value: `${derived.hp}`, color: '#4a8a4a' },
                { label: 'SAN', value: `${derived.san}`, color: '#7050a0' },
                { label: 'MP', value: `${derived.mp}`, color: '#4a7098' },
                { label: 'DB', value: derived.db, color: '#b8976a' },
                { label: 'MOV', value: `${derived.move}`, color: '#c08050' },
              ].map(pill => (
                <div key={pill.label} className="flex-1 bg-panel rounded-md px-2.5 py-2 text-center">
                  <div className="text-[10px] text-text-muted font-semibold">{pill.label}</div>
                  <div className="text-[16px] font-bold font-mono" style={{ color: pill.color }}>{pill.value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════ Step 2: Skills ═══════════════ */}
      {step === 2 && (
        <div className="px-5 pb-20 animate-screen-in">
          {/* Point counters */}
          <div className="flex gap-2.5 mb-3">
            <div className="flex-1 bg-card border border-border-light rounded-md p-3">
              <div className="text-[10px] text-text-muted font-semibold mb-1">
                职业技能 <span className="text-text-dim">({selectedOcc?.skillPoints || '—'})</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                  <div className="h-full rounded-full bg-brass transition-all" style={{ width: `${Math.min(100, occPointsTotal ? (occPointsSpent / occPointsTotal) * 100 : 0)}%` }} />
                </div>
                <span className="text-xs font-bold font-mono text-text-primary">{occPointsSpent}/{occPointsTotal}</span>
              </div>
            </div>
            <div className="flex-1 bg-card border border-border-light rounded-md p-3">
              <div className="text-[10px] text-text-muted font-semibold mb-1">兴趣技能 <span className="text-text-dim">(INT×2)</span></div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                  <div className="h-full rounded-full bg-[#4a7098] transition-all" style={{ width: `${Math.min(100, interestPointsTotal ? (interestPointsSpent / interestPointsTotal) * 100 : 0)}%` }} />
                </div>
                <span className="text-xs font-bold font-mono text-text-primary">{interestPointsSpent}/{interestPointsTotal}</span>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-3">
            {[
              { key: 'occupation', label: '职业技能', count: occSkills.length },
              { key: 'interest', label: '兴趣技能', count: ALL_SKILLS.length },
            ].map(tab => (
              <button key={tab.key} onClick={() => setSkillTab(tab.key as typeof skillTab)}
                className={`flex-1 py-2 text-[12px] font-semibold rounded-[6px] transition-all ${
                  skillTab === tab.key ? 'bg-brass text-white' : 'bg-card border border-border-light text-text-muted'
                }`}>
                {tab.label} <span className="font-mono">({tab.count})</span>
              </button>
            ))}
          </div>

          {/* Skill list */}
          <div className="space-y-1.5">
            {skillTab === 'occupation' ? (
              occSkills.length === 0 ? (
                <div className="text-center py-8 text-text-muted text-sm">
                  请先在上一步中选择职业
                </div>
              ) : occSkills.map(skill => (
                <SkillRow key={skill.id} skill={skill} attr={attr}
                  allocation={skillAlloc[skill.id] || 0}
                  onChange={(d) => handleSkillChange(skill.id, d)}
                  maxPoints={occPointsTotal - occPointsSpent + (skillAlloc[skill.id] || 0)}
                  minPoints={0}
                />
              ))
            ) : (
              ALL_SKILLS.filter(s => !occSkillIds.includes(s.id)).map(skill => (
                <SkillRow key={skill.id} skill={skill} attr={attr}
                  allocation={skillAlloc[skill.id] || 0}
                  onChange={(d) => handleSkillChange(skill.id, d)}
                  maxPoints={interestPointsTotal - interestPointsSpent + (skillAlloc[skill.id] || 0)}
                  minPoints={0}
                />
              ))
            )}
          </div>
        </div>
      )}

      {/* ═══════════════ Step 3: Summary ═══════════════ */}
      {step === 3 && (
        <div className="px-5 pb-20 animate-screen-in">
          {/* Equipment */}
          <div className="bg-card border border-border-light rounded-md p-[18px] mb-3">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">装备与物品</h4>
            <textarea value={equipment} onChange={e => setEquipment(e.target.value)}
              placeholder="手电筒、笔记本、相机、急救包…" rows={3}
              className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-none" />
          </div>

          {/* Background */}
          <div className="bg-card border border-border-light rounded-md p-[18px] mb-3">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">背景故事</h4>
            <textarea value={background} onChange={e => setBackground(e.target.value)}
              placeholder="简单描述你的角色背景…" rows={4}
              className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-none" />
          </div>

          {/* Notes */}
          <div className="bg-card border border-border-light rounded-md p-[18px] mb-3">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">其他备注</h4>
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="角色特质、秘密、人际关系…" rows={3}
              className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-none" />
          </div>

          {/* Summary Card */}
          <div className="bg-card border border-border-light rounded-md p-[18px]">
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3.5">角色概览</h4>
            <div className="space-y-2.5 text-sm">
              <div className="flex items-center gap-2.5">
                <span className="text-[28px]">{selectedOcc?.icon || '❓'}</span>
                <div>
                  <div className="font-bold text-text-primary text-[17px]">{info.name || '未命名调查员'}</div>
                  <div className="text-xs text-text-muted">{selectedOcc?.name || '未选择职业'} · {info.age}岁 · {info.gender}</div>
                </div>
              </div>
              <div className="h-px bg-border-light" />
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 font-mono text-[12px] text-text-muted">
                {ATTR_KEYS.map(key => (
                  <span key={key}>{ATTRIBUTE_LABELS[key].short} <span className="font-bold text-text-primary">{attr[key]}</span></span>
                ))}
              </div>
              <div className="flex gap-2">
                {[
                  { label: 'HP', value: `${derived.hp}`, color: 'text-mold' },
                  { label: 'SAN', value: `${derived.san}`, color: 'text-[#7050a0]' },
                  { label: 'MP', value: `${derived.mp}`, color: 'text-[#4a7098]' },
                  { label: 'DB', value: derived.db, color: 'text-text-muted' },
                  { label: 'MOV', value: `${derived.move}`, color: 'text-text-muted' },
                ].map(pill => (
                  <span key={pill.label} className={`text-[11px] ${pill.color} font-mono bg-panel px-2.5 py-1 rounded-full`}>
                    {pill.label} {pill.value}
                  </span>
                ))}
              </div>
              <div className="h-px bg-border-light" />
              <div>
                <div className="text-[11px] text-text-muted mb-1.5">已分配技能</div>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {Object.entries(skillAlloc).filter(([, v]) => v > 0).map(([id, pts]) => {
                    const skill = getSkillById(id)
                    if (!skill) return null
                    const base = calculateBaseValue(skill, attr)
                    return (
                      <span key={id} className="text-[11px] font-mono bg-panel px-2 py-0.5 rounded-full text-text-muted">
                        {skill.name} {base + pts}%
                      </span>
                    )
                  })}
                  {Object.keys(skillAlloc).filter(k => (skillAlloc[k] || 0) > 0).length === 0 && (
                    <span className="text-[11px] text-text-dim">暂无技能分配</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

            {/* ═══════════════ Occupation Detail Modal ═══════════════ */}
      {detailOcc && (
        <>
          <div className="fixed inset-0 bg-black/50 z-30 animate-fade-in" onClick={() => setDetailOcc(null)} />
          <div className="fixed inset-x-0 bottom-0 z-40 animate-slide-up">
            <div className="bg-page border border-border-light rounded-t-xl px-5 pt-5 pb-8 max-h-[80vh] overflow-y-auto">
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-3">
                  <span className="text-[32px]">{detailOcc.icon}</span>
                  <div>
                    <h3 className="text-[18px] font-bold text-text-primary">{detailOcc.name}</h3>
                    <p className="text-xs text-text-muted">{detailOcc.category} · 信用 {detailOcc.creditRange ?? '自定'} · {detailOcc.skillPoints}</p>
                  </div>
                </div>
                <button onClick={() => setDetailOcc(null)}
                  className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-text-muted active:bg-panel">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-3.5">
                <div className="bg-input border border-border-light rounded-[6px] p-3.5">
                  <div className="text-[11px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">基础信息</div>
                  <div className="flex items-center gap-6 text-sm">
                    <div>
                      <span className="text-[11px] text-text-muted block">信用范围</span>
                      <span className="font-bold text-text-primary">{detailOcc.creditRange ?? '自定'}</span>
                    </div>
                    <div>
                      <span className="text-[11px] text-text-muted block">技能点数</span>
                      <span className="font-bold font-mono text-text-primary">{detailOcc.skillPoints}</span>
                    </div>
                  </div>
                </div>

                <div className="bg-input border border-border-light rounded-[6px] p-3.5">
                  <div className="text-[11px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">职业介绍</div>
                  <p className="text-[12px] leading-[1.75] text-text-muted whitespace-pre-line">
                    {detailOcc.description || detailOcc.shortDesc}
                  </p>
                  {detailOcc.sourceNote && (
                    <p className="mt-2 text-[10px] leading-[1.5] text-text-dim">
                      来源说明：{detailOcc.sourceNote}
                    </p>
                  )}
                </div>

                <div className="bg-input border border-border-light rounded-[6px] p-3.5">
                  <div className="text-[11px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">职业技能 ({detailOcc.skillIds.length})</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {detailOcc.skillIds.map(id => {
                      const skill = getSkillById(id)
                      return (
                        <div key={id} className="flex items-center gap-2 px-2.5 py-1.5 bg-card border border-border-light rounded-[4px]">
                          <div className="flex-1 min-w-0">
                            <div className="text-[12px] font-medium text-text-primary">{skill?.name || id}</div>
                            <div className="text-[9px] text-text-dim font-mono">{skill?.nameEn}</div>
                          </div>
                          <div className="text-[10px] font-mono bg-panel px-1.5 py-0.5 rounded text-text-muted">
                            {skill && (typeof skill.base === 'number' ? skill.base + '%' : skill.base)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>

              <button
                onClick={() => { handleSelectOccupation(detailOcc.id); setDetailOcc(null) }}
                className="mt-4 w-full flex items-center justify-center gap-2 py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all"
              >
                选择 {detailOcc.name}
              </button>
            </div>
          </div>
        </>
      )}

      {/* ═══════════════ Bottom action bar ═══════════════ */}
      <div className="fixed bottom-0 left-0 right-0 bg-page border-t border-border-light px-5 py-3 max-w-[430px] mx-auto z-20">
        <div className="flex gap-2.5">
          <button onClick={() => step > 0 ? setStep(s => s - 1) : navigate(-1)}
            className="flex-1 flex items-center justify-center gap-1.5 px-5 py-3 rounded-sm text-sm font-semibold transition-all border border-border-mid bg-card text-text-body active:bg-panel active:scale-[0.97]">
            上一步
          </button>
          <button onClick={() => {
            if (step < 3) setStep(s => s + 1)
            else navigate('/lobby')
          }}
            className="flex-1 flex items-center justify-center gap-1.5 px-5 py-3 rounded-sm text-sm font-semibold transition-all bg-brass text-white active:bg-brass-dark active:scale-[0.97]">
            {step === 3 ? '完成创建' : '下一步'} →
          </button>
        </div>
      </div>
    </div>
  )
}
