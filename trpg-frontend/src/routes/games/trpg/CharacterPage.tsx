import { useNavigate } from 'react-router-dom'
import { useState, useMemo, useEffect, useRef } from 'react'
import { ArrowLeft, Plus, Minus, Search, Shield, Heart, Brain, Zap, Eye, Maximize2, Lightbulb, BookOpen, ChevronDown, X, Info } from 'lucide-react'
import type { CharacterComputeResult, SkillComputeView } from 'trpg-sdk'
import { OCCUPATION_ICONS, OCCUPATION_GROUPS } from '@/data/occupations'
import { ATTRIBUTE_LABELS, type Attributes, type InvestigatorInfo } from '@/data/character-model'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { createCharacterDraft, saveCharacter, completeCharacter, toUpperAttrs } from '@/services/character/character-api'
import { previewCharacter, translateCharacterValidationError } from '@/services/character/ruleset-api'
import { friendlyErrorMessage } from '@/services/api-client'
import { useRuleset } from '@/hooks/useRuleset'
import type { OccupationSpec, SkillSpec } from '@/data/types'

const ATTR_KEYS = ['str', 'con', 'pow', 'dex', 'app', 'siz', 'int', 'edu'] as const

const ATTR_ICONS: Record<string, typeof Heart> = {
  str: Shield, con: Heart, pow: Brain, dex: Zap,
  app: Eye, siz: Maximize2, int: Lightbulb, edu: BookOpen,
}

const ATTR_COLORS: Record<string, string> = {
  str: '#c04040', con: '#c08050', pow: '#7050a0', dex: '#4a8a4a',
  app: '#8a4070', siz: '#b8976a', int: '#4a7098', edu: '#6a6050',
}

// 建卡阶段的衍生值面板用小写 key，后端 derivedStats 是 { HP, MP, SAN, DB,
// Build, MOV } 这种大写 key 的松散字典（不是固定字段的 DTO），这里做一次
// 归一化，纯粹是取值/改大小写，不是规则计算。
function normalizeDerivedStats(d: CharacterComputeResult['derivedStats'] | undefined) {
  const num = (v: unknown) => (typeof v === 'number' ? v : 0)
  const str = (v: unknown) => (v == null ? '0' : String(v))
  return {
    hp: num(d?.HP),
    san: num(d?.SAN),
    mp: num(d?.MP),
    db: str(d?.DB),
    move: num(d?.MOV),
  }
}

// ─── SkillRow Component ──────────────────────────────
function SkillRow({
  skill, base, cap, poolAllocation, otherPoolPoints, onChange, onSetAllocation, maxPoints, minPoints
}: {
  skill: SkillSpec
  base: number
  cap: number
  poolAllocation: number
  otherPoolPoints: number
  onChange: (delta: number) => void
  onSetAllocation: (allocation: number) => void
  maxPoints: number
  minPoints: number
}) {
  // 总显示值 = 基础值 + 另一个点数池已经加的 + 当前这个池加的——另一个池的部分
  // 在这个 tab 里是只读的背景值，编辑只作用于当前池自己的那部分。
  const current = base + otherPoolPoints + poolAllocation
  const canAdd = poolAllocation < maxPoints && current < cap
  const canSub = poolAllocation > minPoints

  // 手动输入这个技能的最终值——先允许自由打字，失焦时再校验：不能低于
  // minPoints（一般是 0），也不能超出这个分类（职业/兴趣）剩余的可用点数，
  // 还要满足单项技能不超过上限（cap，来自后端），三个限制取交集里最松的那个。
  const [inputValue, setInputValue] = useState(String(current))
  useEffect(() => { setInputValue(String(current)) }, [current])

  const commitInput = () => {
    const typed = parseInt(inputValue, 10)
    if (Number.isNaN(typed)) { setInputValue(String(current)); return }
    const maxAllocByCap = Math.min(maxPoints, cap - base - otherPoolPoints)
    const newAlloc = Math.max(minPoints, Math.min(maxAllocByCap, typed - base - otherPoolPoints))
    onSetAllocation(newAlloc)
    setInputValue(String(base + otherPoolPoints + newAlloc))
  }

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
      <input
        type="number"
        inputMode="numeric"
        value={inputValue}
        onChange={e => setInputValue(e.target.value)}
        onBlur={commitInput}
        className="text-[15px] font-bold font-mono text-text-primary min-w-[28px] w-[34px] text-center bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
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

  // 建卡规则目录（职业/技能/属性）改从后端 GET /systems/{systemId}/ruleset
  // 拿（issue #84 S3），职业网格/技能列表在数据到达前先显示 loading。
  const { ruleset, loading: rulesetLoading, error: rulesetError } = useRuleset()

  // ★ 从"人物卡准备页"点"编辑"回来时，如果已经建过卡（哪怕只是草稿），
  // 用已有数据预填，不要每次都从空白表单重新开始——之前一编辑就把之前填的
  // 全部作废，逼用户重填一遍。用 getForRoom 而不是直接读 character：
  // 本地缓存不按房间区分的话，换了房间会把上一个房间的角色数据错误地
  // 当成"已经建过卡"预填进来（见 PR #67 review）。
  const existingCharacter = useCharacterStore
    .getState()
    .getForRoom(useRoomStore.getState().roomId ?? '')

  // Investigator info
  const [info, setInfo] = useState<InvestigatorInfo>(() => existingCharacter?.info ?? {
    name: '', playerName: '', age: '28', gender: '男',
    residence: '阿卡姆', birthplace: '阿卡姆', occupationId: null,
  })

  // Attributes
  const [attr, setAttr] = useState<Attributes>(() => existingCharacter?.attr ?? {
    str: 50, con: 50, pow: 50, dex: 50,
    app: 50, siz: 50, int: 50, edu: 50,
  })

  // Skill allocations: skillId -> points spent
  const [skillAlloc, setSkillAlloc] = useState<Record<string, number>>(() => existingCharacter ? { ...existingCharacter.skillAlloc } : {})

  // Equipment & background
  const [equipment, setEquipment] = useState(existingCharacter?.equipment ?? '')
  const [background, setBackground] = useState(existingCharacter?.background ?? '')
  const [notes, setNotes] = useState(existingCharacter?.notes ?? '')

  // UI state
  const [search, setSearch] = useState('')
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [skillTab, setSkillTab] = useState<'occupation' | 'interest'>('occupation')
  const [showGroupPicker, setShowGroupPicker] = useState(false)
  const [detailOcc, setDetailOcc] = useState<OccupationSpec | null>(null)

  const selectedOcc = useMemo(() => {
    if (!ruleset || info.occupationId == null) return null
    return ruleset.occupations.find(o => o.id === info.occupationId) ?? null
  }, [ruleset, info.occupationId])

  // 信用评级（credit-rating）是后端建成的必填技能，值须落在所选职业的
  // [creditMin, creditMax] 内（后端 CREDIT_OUT_OF_RANGE）。这里给它一个专门
  // 的默认值初始化：只在"职业真正发生变化"（ref 记的上一次处理过的职业 id
  // 跟这次不一样）时才动，且只在当前值缺失或落在新职业区间外时才写入/夹紧，
  // 不会覆盖玩家已经手动调过、且仍然合法的值——也不会覆盖编辑已有角色时
  // 带进来的既有信用值。
  const creditInitializedForOcc = useRef<number | null>(null)
  useEffect(() => {
    if (!selectedOcc) return
    if (creditInitializedForOcc.current === selectedOcc.id) return
    creditInitializedForOcc.current = selectedOcc.id
    setSkillAlloc(prev => {
      const current = prev['credit-rating']
      const clamped = current == null
        ? selectedOcc.creditMin
        : Math.max(selectedOcc.creditMin, Math.min(selectedOcc.creditMax, current))
      if (clamped === current) return prev
      return { ...prev, 'credit-rating': clamped }
    })
  }, [selectedOcc])

  // Filter occupations by search and group
  const filteredOccupations = useMemo(() => {
    if (!ruleset) return []
    let list = ruleset.occupations
    if (activeGroup) {
      const group = OCCUPATION_GROUPS.find(g => g.label === activeGroup)
      const ids = new Set(group?.ids ?? [])
      list = list.filter(o => ids.has(o.id))
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(o => o.name.includes(q) || o.description.includes(q))
    }
    return list
  }, [ruleset, activeGroup, search])

  // Occupation skill IDs（保留职业技能清单里定义的顺序，不是技能表里的顺序）
  const occSkillIds = useMemo(() => {
    if (!ruleset || info.occupationId == null) return []
    return ruleset.occupations.find(o => o.id === info.occupationId)?.skillIds ?? []
  }, [ruleset, info.occupationId])

  const occSkills = useMemo(() => {
    if (!ruleset) return []
    const bySkillId = new Map(ruleset.skills.map(s => [s.id, s]))
    // credit-rating 有专门的信用评级卡片，不在这里重复出现。
    return occSkillIds.map(id => bySkillId.get(id)).filter((s): s is SkillSpec => !!s && s.id !== 'credit-rating')
  }, [ruleset, occSkillIds])

  // 兴趣技能 tab 的技能清单：排除职业技能，也排除 credit-rating（同上，
  // 有专门卡片）。单独抽出来，好让 tab 徽标数字和实际渲染列表长度一致。
  const interestSkills = useMemo(() => {
    if (!ruleset) return []
    return ruleset.skills.filter(s => !occSkillIds.includes(s.id) && s.id !== 'credit-rating')
  }, [ruleset, occSkillIds])

  // ── 建卡计算预览（issue #84 S2 previewCharacter，路线乙的接缝）──────────
  // 衍生值/技能点预算/每个技能的 base·cap/校验报告全部来自这里，前端不再
  // 本地重算 COC7 规则数值。不需要每次点技能 +/- 都调用：base/cap/预算只
  // 跟"属性"和"职业"有关，跟具体分配了多少点无关，所以只在属性/职业变化
  // 时（防抖）请求一次；技能分配阶段的"剩余点数"允许前端本地做
  // 剩余=预算-已分配 这种平凡算术，不需要为每次点击都发一次请求。
  const [preview, setPreview] = useState<CharacterComputeResult | null>(null)
  const [previewError, setPreviewError] = useState('')

  // 请求代次守卫：清 debounce 的 timer 只能取消"还没发出"的下一次调用，取消
  // 不了已经在飞的那次网络请求——如果旧请求比新请求慢返回，会用过期数据
  // 覆盖新状态。每次真正发请求前 +1 代，回调里只有当自己仍是最新一代时才
  // setPreview/setPreviewError。
  const previewGenRef = useRef(0)

  useEffect(() => {
    if (!ruleset) return
    const timer = setTimeout(() => {
      const gen = ++previewGenRef.current
      previewCharacter({
        attributes: toUpperAttrs(attr),
        occupationId: info.occupationId,
        skills: {},
      })
        .then((result) => {
          if (gen !== previewGenRef.current) return
          setPreview(result)
          setPreviewError('')
        })
        .catch((err) => {
          if (gen !== previewGenRef.current) return
          setPreviewError(friendlyErrorMessage(err, '规则计算失败'))
        })
    }, 400)
    return () => clearTimeout(timer)
  }, [ruleset, attr, info.occupationId])

  const skillComputeMap = useMemo(() => {
    const map = new Map<string, SkillComputeView>()
    preview?.skillView.forEach(v => map.set(v.id, v))
    return map
  }, [preview])

  const occPointsTotal = preview?.occupationSkillPoints.budget ?? 0
  const interestPointsTotal = preview?.interestSkillPoints.budget ?? 0

  // 职业点数只能花在职业技能列表里；兴趣点数可以花在任何技能上（包括职业技能，
  // COC7 规则本来就允许兴趣点数给职业技能"加成"）。所以同一个技能的总加点
  // （skillAlloc，提交给后端用的那份）可能是职业点数和兴趣点数两部分凑出来
  // 的，这里单独记一份"这个技能里有多少是兴趣点数"，职业点数部分就是
  // 总数减掉这部分，不需要再单独存。
  const [interestAlloc, setInterestAlloc] = useState<Record<string, number>>({})
  const interestAllocInitialized = useRef(false)

  // 编辑已有角色时重建 interestAlloc 需要知道这个职业的技能清单，只有
  // ruleset 到位之后才能算——只在 ruleset 第一次到位时跑一次，不要覆盖用户
  // 之后自己的编辑。
  useEffect(() => {
    if (!ruleset || !existingCharacter || interestAllocInitialized.current) return
    interestAllocInitialized.current = true
    const occIds = new Set(
      ruleset.occupations.find(o => o.id === existingCharacter.info.occupationId)?.skillIds ?? []
    )
    const out: Record<string, number> = {}
    for (const [id, pts] of Object.entries(existingCharacter.skillAlloc)) {
      if (!occIds.has(id)) out[id] = pts
    }
    setInterestAlloc(out)
  }, [ruleset, existingCharacter])

  // 信用评级按 COC7 官方裁定分账（跟后端 coc7_rules._compute 的记账口径
  // 保持一致）：下限（creditMin）那部分点数算职业点负担，超出下限的部分算
  // 兴趣点负担。两条预算 bar 的"已花"必须把这部分算进去，否则会出现前端
  // bar 看着没花满、后端却因为信用挤占了额度而拒绝的情况。
  const occPointsSpent = useMemo(() => {
    const skillsSpent = occSkillIds.reduce((sum, id) => sum + ((skillAlloc[id] || 0) - (interestAlloc[id] || 0)), 0)
    return skillsSpent + (selectedOcc ? selectedOcc.creditMin : 0)
  }, [occSkillIds, skillAlloc, interestAlloc, selectedOcc])

  const interestPointsSpent = useMemo(() => {
    const skillsSpent = Object.values(interestAlloc).reduce((sum, pts) => sum + pts, 0)
    const creditValue = skillAlloc['credit-rating'] ?? selectedOcc?.creditMin ?? 0
    const creditExcess = selectedOcc ? Math.max(0, creditValue - selectedOcc.creditMin) : 0
    return skillsSpent + creditExcess
  }, [interestAlloc, skillAlloc, selectedOcc])

  const derived = useMemo(() => normalizeDerivedStats(preview?.derivedStats), [preview])

  const roomId = useRoomStore((s) => s.roomId)
  const setCharacterId = useRoomStore((s) => s.setCharacterId)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  // 兴趣技能页签（只列非职业技能）：单纯的兴趣点数池，逻辑简单，加/减只动
  // interestAlloc，skillAlloc 跟着同步——因为这些技能压根碰不到职业点数。
  const handleInterestSkillChange = (skillId: string, delta: number) => {
    const prevInterest = interestAlloc[skillId] || 0
    const nextInterest = Math.max(0, prevInterest + delta)
    const appliedDelta = nextInterest - prevInterest
    setInterestAlloc(prev => ({ ...prev, [skillId]: nextInterest }))
    setSkillAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + appliedDelta }))
  }

  const handleInterestSkillSet = (skillId: string, newAllocation: number) => {
    const occPart = (skillAlloc[skillId] || 0) - (interestAlloc[skillId] || 0)
    const clamped = Math.max(0, newAllocation)
    setInterestAlloc(prev => ({ ...prev, [skillId]: clamped }))
    setSkillAlloc(prev => ({ ...prev, [skillId]: occPart + clamped }))
  }

  // 职业技能页签：加点优先扣职业点数池，职业点数用完了自动改扣兴趣点数池
  // （这是本轮用户明确要的行为——不是要手动切到兴趣页签才能给职业技能
  // 补点，职业技能这一侧自己就该会"溢出"到兴趣池）。减点则反过来，先退
  // 兴趣池占的部分（后加的先退），再退职业池的部分。
  const handleOccSkillChange = (skillId: string, delta: number) => {
    if (delta > 0) {
      const occRemaining = occPointsTotal - occPointsSpent
      if (occRemaining > 0) {
        setSkillAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + 1 }))
        return
      }
      const interestRemaining = interestPointsTotal - interestPointsSpent
      if (interestRemaining > 0) {
        setInterestAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + 1 }))
        setSkillAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + 1 }))
      }
    } else if (delta < 0) {
      const interestPart = interestAlloc[skillId] || 0
      if (interestPart > 0) {
        setInterestAlloc(prev => ({ ...prev, [skillId]: interestPart - 1 }))
      }
      setSkillAlloc(prev => ({ ...prev, [skillId]: Math.max(0, (prev[skillId] || 0) - 1) }))
    }
  }

  const handleOccSkillSet = (skillId: string, newTotalAllocation: number) => {
    const occPart = (skillAlloc[skillId] || 0) - (interestAlloc[skillId] || 0)
    const interestPart = interestAlloc[skillId] || 0
    const currentTotal = occPart + interestPart
    let delta = Math.max(0, newTotalAllocation) - currentTotal
    let newOccPart = occPart
    let newInterestPart = interestPart

    if (delta > 0) {
      const occRemaining = Math.max(0, occPointsTotal - occPointsSpent)
      const occAdd = Math.min(delta, occRemaining)
      newOccPart += occAdd
      delta -= occAdd
      const interestRemaining = Math.max(0, interestPointsTotal - interestPointsSpent)
      newInterestPart += Math.min(delta, interestRemaining)
    } else if (delta < 0) {
      let remove = -delta
      const interestRemove = Math.min(remove, newInterestPart)
      newInterestPart -= interestRemove
      remove -= interestRemove
      newOccPart -= Math.min(remove, newOccPart)
    }

    setInterestAlloc(prev => ({ ...prev, [skillId]: newInterestPart }))
    setSkillAlloc(prev => ({ ...prev, [skillId]: newOccPart + newInterestPart }))
  }

  // 信用评级 +/- ：直接夹在所选职业的 [creditMin, creditMax] 内。信用的
  // base 固定是 0（见后端 SkillSpec），所以 skillAlloc['credit-rating']
  // 本身就是最终信用值，不需要像其它技能那样叠加 base。
  const handleCreditChange = (delta: number) => {
    if (!selectedOcc) return
    setSkillAlloc(prev => {
      const current = prev['credit-rating'] ?? selectedOcc.creditMin
      const next = Math.max(selectedOcc.creditMin, Math.min(selectedOcc.creditMax, current + delta))
      return { ...prev, 'credit-rating': next }
    })
  }

  const [attrInputs, setAttrInputs] = useState<Record<string, string>>(
    () => Object.fromEntries(ATTR_KEYS.map(k => [k, String(attr[k])]))
  )

  const handleAttrChange = (key: keyof Attributes, delta: number) => {
    setAttr(prev => {
      const newVal = Math.max(10, Math.min(90, prev[key] + delta))
      if (delta > 0) {
        const totalOthers = Object.entries(prev).filter(([k]) => k !== key).reduce((s, [, v]) => s + v, 0)
        if (totalOthers + newVal > 480) return prev
      }
      setAttrInputs(inputs => ({ ...inputs, [key]: String(newVal) }))
      return { ...prev, [key]: newVal }
    })
  }

  // 手动输入属性值——允许先清空再打字（不在每次按键就夹值，否则没法删了重打），
  // 只在失焦时校验：范围 10-90，且不能让总点数超过 480（超了就按"其余属性剩多少
  // 点"封顶，而不是直接拒绝，体验上比"打了数字却没反应"更清楚）。
  const commitAttrInput = (key: keyof Attributes) => {
    const raw = parseInt(attrInputs[key], 10)
    setAttr(prev => {
      const totalOthers = Object.entries(prev).filter(([k]) => k !== key).reduce((s, [, v]) => s + v, 0)
      const maxAllowed = Math.min(90, 480 - totalOthers)
      const clamped = Number.isNaN(raw) ? prev[key] : Math.max(10, Math.min(maxAllowed, raw))
      setAttrInputs(inputs => ({ ...inputs, [key]: String(clamped) }))
      return { ...prev, [key]: clamped }
    })
  }

  const steps = [
    { label: '信息', key: 'info', done: step > 0 },
    { label: '属性', key: 'attr', done: step > 1 },
    { label: '技能', key: 'skill', done: step > 2 },
    { label: '完成', key: 'done', done: step > 3 },
  ]

  const handleSubmit = async () => {
    if (!roomId) {
      setSubmitError('房间信息丢失，请重新创建/加入房间')
      return
    }
    if (!ruleset) return
    setSubmitting(true)
    setSubmitError('')
    try {
      // 最终提交前再拉一次权威计算：用当前 base（来自 skillComputeMap）把
      // 已分配点数换算成"最终值"，连同属性/职业一起发给后端拿回完整的
      // skillView（79 项技能的最终值）和衍生值，两边都以这次结果为准落库。
      const skillsPayload: Record<string, number> = {}
      for (const [id, pts] of Object.entries(skillAlloc)) {
        if (!pts) continue
        const base = skillComputeMap.get(id)?.base ?? 0
        skillsPayload[id] = base + pts
      }
      const finalPreview = await previewCharacter({
        attributes: toUpperAttrs(attr),
        occupationId: info.occupationId,
        skills: skillsPayload,
      })
      const finalDerived = normalizeDerivedStats(finalPreview.derivedStats)
      const skillFinalValues = Object.fromEntries(
        finalPreview.skillView.map(v => [v.id, v.current])
      )

      const characterId = await createCharacterDraft(roomId)
      await saveCharacter(roomId, characterId, {
        name: info.name,
        attr,
        derived: { hp: finalDerived.hp, san: finalDerived.san, mp: finalDerived.mp },
        skillValues: skillsPayload,
        equipment,
        occupationName: selectedOcc?.name ?? null,
        background,
        notes,
      })
      await completeCharacter(roomId, characterId)
      setCharacterId(characterId)
      useCharacterStore.getState().setCharacter(
        {
          info: { ...info, playerName: info.playerName || info.name },
          attr: { ...attr },
          skillAlloc: { ...skillAlloc },
          skillFinalValues,
          equipment, background, notes,
          derived: finalDerived,
        },
        roomId
      )
      navigate('/room/ready')
    } catch (err) {
      setSubmitError(translateCharacterValidationError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page">
      {rulesetLoading ? (
        <div className="flex flex-col items-center justify-center min-h-screen px-5 text-center">
          <p className="text-sm text-text-muted">正在加载规则数据…</p>
        </div>
      ) : rulesetError ? (
        <div className="flex flex-col items-center justify-center min-h-screen px-5 text-center gap-3">
          <p className="text-sm text-[#c04040]">{rulesetError}</p>
          <button onClick={() => navigate(-1)}
            className="px-5 py-2.5 rounded-sm bg-card border border-border-light text-text-body text-sm font-semibold">
            返回
          </button>
        </div>
      ) : (
        <>
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
            {/* ★ 提前告知"没有房间"这件事，不要等填完四步、点完成创建才在最后一刻
                报错——之前"浏览已有游戏"这条路径就是这样把用户的输入全部作废的
                （见 2026-07-13 测试报告）。 */}
            {!roomId && (
              <div className="mx-5 mb-3 px-3.5 py-2.5 bg-[#fdf3e0] border border-[#e0c088] rounded-[6px] text-[12px] text-[#8a6a2a]">
                当前未加入房间，创建的角色不会被保存。请先返回创建或加入一个房间。
              </div>
            )}
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
                  <div className="grid grid-cols-2 gap-2.5">
                    <div>
                      <label className="text-[11px] font-medium text-text-muted mb-1 block">年龄</label>
                      <input type="number" min={10} max={100} value={info.age}
                        onChange={e => setInfo(i => ({ ...i, age: e.target.value }))}
                        onBlur={e => {
                          const v = Math.max(10, Math.min(100, parseInt(e.target.value, 10) || 10))
                          setInfo(i => ({ ...i, age: String(v) }))
                        }}
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
                    <span className="text-xl">{OCCUPATION_ICONS[selectedOcc.id] ?? '❔'}</span>
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-text-primary">{selectedOcc.name}</div>
                      <div className="text-[11px] text-text-muted">信用 {selectedOcc.creditMin}-{selectedOcc.creditMax} · {selectedOcc.skillPointsFormula}</div>
                    </div>
                    <button onClick={() => setInfo(i => ({ ...i, occupationId: null }))} className="text-[11px] text-text-dim underline">更换</button>
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
                          {OCCUPATION_GROUPS.map(g => (
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
                  {filteredOccupations.map(occ => {
                    const selected = info.occupationId === occ.id
                    return (
                      <div key={occ.id}
                        className={`group relative px-2.5 py-3 bg-input border rounded-[6px] text-center cursor-pointer active:scale-[0.96] transition-all ${
                          selected ? 'border-brass bg-[#fdfaf4] shadow-[0_0_0_2px_rgba(184,151,106,0.15)]' : 'border-border-light'
                        }`}>
                        <button
                          onClick={(e) => { e.stopPropagation(); setDetailOcc(occ); }}
                          className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-[rgba(255,255,255,0.7)] border border-border-light flex items-center justify-center text-text-dim hover:text-text-body transition-all opacity-0 group-hover:opacity-100"
                        >
                          <Info className="w-3 h-3" />
                        </button>
                        <div onClick={() => setInfo(i => ({ ...i, occupationId: occ.id }))}>
                          <div className="text-[20px] mb-1">{OCCUPATION_ICONS[occ.id] ?? '❔'}</div>
                          <div className="text-[12px] font-semibold text-text-primary">{occ.name}</div>
                          <div className="text-[9px] text-text-dim mt-0.5 leading-[1.3]">{occ.description}</div>
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
                <p className="text-[11px] text-text-muted mb-2">点击 +/- 调整属性值（范围 10-90，每次 ±5）</p>
                <div className="bg-panel rounded-md px-3.5 py-2 mb-3 flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] font-medium text-text-muted">总点数</span>
                      <span className="text-[12px] font-bold font-mono text-text-primary">{Object.values(attr).reduce((a, b) => a + b, 0)}<span className="text-text-dim font-normal">/480</span></span>
                    </div>
                    <div className="h-1.5 rounded-full bg-border-light overflow-hidden">
                      <div className="h-full rounded-full bg-brass transition-all duration-300" style={{ width: `${Math.min(100, (Object.values(attr).reduce((a, b) => a + b, 0) / 480) * 100)}%` }} />
                    </div>
                  </div>
                  <span className="text-[10px] text-text-dim">{480 - Object.values(attr).reduce((a, b) => a + b, 0)} 点剩余</span>
                </div>
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
                        <input
                          type="number"
                          inputMode="numeric"
                          min={10}
                          max={90}
                          value={attrInputs[key]}
                          onChange={e => setAttrInputs(inputs => ({ ...inputs, [key]: e.target.value }))}
                          onBlur={() => commitAttrInput(key)}
                          className="text-[17px] font-bold font-mono text-text-primary min-w-[36px] w-[36px] text-center bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                        />
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
                {previewError && <p className="text-[11px] text-[#c04040] mb-2">{previewError}</p>}
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
                    职业技能 <span className="text-text-dim">({selectedOcc?.skillPointsFormula || '—'})</span>
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

              {/* Credit Rating — 后端必填技能，值须落在所选职业信用区间内，
                  单独给一张显眼卡片，不跟普通技能混在职业/兴趣两个 tab 里。 */}
              {selectedOcc && (
                <div className="bg-[#fdfaf4] border border-brass rounded-md p-3.5 mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <h4 className="text-[12px] font-semibold text-brass-dark">
                      信用评级 (Credit Rating) · <span className="text-[#c04040]">必填</span>
                    </h4>
                    <span className="text-[11px] text-text-muted font-mono">
                      范围 {selectedOcc.creditMin}–{selectedOcc.creditMax}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2">
                    <button onClick={() => handleCreditChange(-1)}
                      disabled={(skillAlloc['credit-rating'] ?? selectedOcc.creditMin) <= selectedOcc.creditMin}
                      className="w-8 h-8 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all disabled:opacity-40 disabled:active:scale-100"
                    >
                      <Minus className="w-4 h-4" />
                    </button>
                    <div className="flex-1 text-center text-[20px] font-bold font-mono text-text-primary">
                      {skillAlloc['credit-rating'] ?? selectedOcc.creditMin}
                    </div>
                    <button onClick={() => handleCreditChange(1)}
                      disabled={(skillAlloc['credit-rating'] ?? selectedOcc.creditMin) >= selectedOcc.creditMax}
                      className="w-8 h-8 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all disabled:opacity-40 disabled:active:scale-100"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="flex gap-2 mb-3">
                {[
                  { key: 'occupation', label: '职业技能', count: occSkills.length },
                  { key: 'interest', label: '兴趣技能', count: interestSkills.length },
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
                  ) : occSkills.map(skill => {
                    // 职业技能这一侧的"总加点"= 职业池部分 + 兴趣池部分（可能因为职业
                    // 点数用完了、自动溢出用了兴趣点数），两部分合并成一个数显示和编辑，
                    // maxPoints 是两个池子剩余额度的总和，加点时由 handleOccSkillChange
                    // /handleOccSkillSet 内部决定具体从哪个池子扣。
                    const totalAllocation = skillAlloc[skill.id] || 0
                    const occRemaining = Math.max(0, occPointsTotal - occPointsSpent)
                    const interestRemaining = Math.max(0, interestPointsTotal - interestPointsSpent)
                    const compute = skillComputeMap.get(skill.id)
                    const base = compute?.base ?? (typeof skill.base === 'number' ? skill.base : 0)
                    const cap = compute?.cap ?? 99
                    return (
                      <SkillRow key={skill.id} skill={skill} base={base} cap={cap}
                        poolAllocation={totalAllocation}
                        otherPoolPoints={0}
                        onChange={(d) => handleOccSkillChange(skill.id, d)}
                        onSetAllocation={(v) => handleOccSkillSet(skill.id, v)}
                        maxPoints={occRemaining + interestRemaining + totalAllocation}
                        minPoints={0}
                      />
                    )
                  })
                ) : (
                  // 兴趣技能页签只列非职业技能——职业技能那边已经能自动溢出用兴趣点数了，
                  // 不需要在这里重复出现。这里纯粹是兴趣点数池，加点只碰 interestAlloc。
                  interestSkills.map(skill => {
                    const interestAllocation = interestAlloc[skill.id] || 0
                    const compute = skillComputeMap.get(skill.id)
                    const base = compute?.base ?? (typeof skill.base === 'number' ? skill.base : 0)
                    const cap = compute?.cap ?? 99
                    return (
                      <SkillRow key={skill.id} skill={skill} base={base} cap={cap}
                        poolAllocation={interestAllocation}
                        otherPoolPoints={0}
                        onChange={(d) => handleInterestSkillChange(skill.id, d)}
                        onSetAllocation={(v) => handleInterestSkillSet(skill.id, v)}
                        maxPoints={interestPointsTotal - interestPointsSpent + interestAllocation}
                        minPoints={0}
                      />
                    )
                  })
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
                      <span className="text-[32px]">{OCCUPATION_ICONS[detailOcc.id] ?? '❔'}</span>
                      <div>
                        <h3 className="text-[18px] font-bold text-text-primary">{detailOcc.name}</h3>
                        <p className="text-xs text-text-muted font-mono">{detailOcc.description}</p>
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
                          <span className="font-bold text-text-primary">{detailOcc.creditMin}-{detailOcc.creditMax}</span>
                        </div>
                        <div>
                          <span className="text-[11px] text-text-muted block">技能点数</span>
                          <span className="font-bold font-mono text-text-primary">{detailOcc.skillPointsFormula}</span>
                        </div>
                      </div>
                    </div>

                    <div className="bg-input border border-border-light rounded-[6px] p-3.5">
                      <div className="text-[11px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">职业技能 ({detailOcc.skillIds.length})</div>
                      <div className="grid grid-cols-2 gap-1.5">
                        {detailOcc.skillIds.map(id => {
                          const skill = ruleset?.skills.find(s => s.id === id)
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
                    onClick={() => { setInfo(i => ({ ...i, occupationId: detailOcc.id })); setDetailOcc(null) }}
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
            {submitError && <p className="text-[11px] text-[#c04040] text-center mb-2">{submitError}</p>}
            <div className="flex gap-2.5">
              <button onClick={() => step > 0 ? setStep(s => s - 1) : navigate(-1)}
                className="flex-1 flex items-center justify-center gap-1.5 px-5 py-3 rounded-sm text-sm font-semibold transition-all border border-border-mid bg-card text-text-body active:bg-panel active:scale-[0.97]">
                上一步
              </button>
              <button onClick={() => {
                if (step < 3) {
                  setStep(s => s + 1)
                  return
                }
                void handleSubmit()
              }}
                disabled={submitting}
                className="flex-1 flex items-center justify-center gap-1.5 px-5 py-3 rounded-sm text-sm font-semibold transition-all bg-brass text-white active:bg-brass-dark active:scale-[0.97] disabled:opacity-60">
                {submitting ? '提交中…' : step === 3 ? '完成创建' : '下一步'} →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
