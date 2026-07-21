import { useNavigate } from 'react-router-dom'
import { useState, useMemo, useEffect, useRef } from 'react'
import { ArrowLeft, Plus, Minus, Search, Shield, Heart, Brain, Zap, Eye, Maximize2, Lightbulb, BookOpen, ChevronDown, X, Info, Clover } from 'lucide-react'
import type { CharacterComputeResult, SkillComputeView } from 'trpg-sdk'
import { OCCUPATION_ICONS, OCCUPATION_GROUPS } from '@/data/occupations'
import type { Attributes, InvestigatorInfo } from '@/data/character-model'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { createCharacterDraft, saveCharacter, completeCharacter, fetchCharacter } from '@/services/character/character-api'
import { previewCharacter, translateCharacterValidationError } from '@/services/character/ruleset-api'
import { friendlyErrorMessage } from '@/services/api-client'
import { useRuleset } from '@/hooks/useRuleset'
import type { OccupationSpec, SkillSpec } from '@/data/types'

// 图标和配色是纯 UI 装饰，不是规则数据，留在前端；键用后端 ruleset 的属性键。
// 「有哪些属性、哪些能加点、默认值多少、预算和上下限是什么」全部来自
// `ruleset`，前端不再自己维护（issue #96）。
const ATTR_ICONS: Record<string, typeof Heart> = {
  STR: Shield, CON: Heart, POW: Brain, DEX: Zap,
  APP: Eye, SIZ: Maximize2, INT: Lightbulb, EDU: BookOpen,
}

const ATTR_COLORS: Record<string, string> = {
  STR: '#c04040', CON: '#c08050', POW: '#7050a0', DEX: '#4a8a4a',
  APP: '#8a4070', SIZ: '#b8976a', INT: '#4a7098', EDU: '#6a6050',
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
  // 后端还没返回权威计算结果时是 null——此时不允许加点，而不是前端自己编一个
  // 上限（原来写死兜底 99，等于在后端沉默时凭空造了一条规则，issue #96 决策 4）。
  cap: number | null
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
  const canAdd = cap !== null && poolAllocation < maxPoints && current < cap
  const canSub = poolAllocation > minPoints

  // 手动输入这个技能的最终值——先允许自由打字，失焦时再校验：不能低于
  // minPoints（一般是 0），也不能超出这个分类（职业/兴趣）剩余的可用点数，
  // 还要满足单项技能不超过上限（cap，来自后端），三个限制取交集里最松的那个。
  const [inputValue, setInputValue] = useState(String(current))
  useEffect(() => { setInputValue(String(current)) }, [current])

  const commitInput = () => {
    const typed = parseInt(inputValue, 10)
    if (Number.isNaN(typed)) { setInputValue(String(current)); return }
    if (cap === null) { setInputValue(String(current)); return }
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
  const [attr, setAttr] = useState<Attributes>(() => ({ ...existingCharacter?.attr }))

  // 可用点数购买的属性键（幸运不在其中——COC7 里它只能掷）。这份名单来自
  // 后端 ruleset 的 pointBuy 标志，前端不再自己维护（issue #96）。
  const pointBuyAttributes = useMemo(
    () => (ruleset?.attributes ?? []).filter(a => a.pointBuy),
    [ruleset]
  )
  const pointBuyRules = ruleset?.attributePointBuy ?? null

  // 从后端读回已保存的角色卡（issue #96）。
  //
  // 后端是角色卡的唯一事实来源；本地那份 localStorage 缓存只是加速用的，不能
  // 当权威源——它的结构会随后端 schema 演进而过期（PR #88 给属性加了幸运之后，
  // 本地存的 8 键旧卡再打开就被后端的 9 键校验拒了，玩家的卡直接编辑不了）。
  // 有 characterId 就以后端那份为准覆盖表单，清掉浏览器缓存也照样能继续编辑。
  useEffect(() => {
    const roomId = useRoomStore.getState().roomId
    const characterId = useRoomStore.getState().characterId
    if (!roomId || !characterId || !ruleset) return

    let cancelled = false
    fetchCharacter(roomId, characterId)
      .then(async saved => {
        if (cancelled || !saved.attributes || Object.keys(saved.attributes).length === 0) return
        const matched = saved.occupation
          ? (ruleset.occupations.find(o => o.name === saved.occupation) ?? null)
          : null

        // 🔴 两个请求都拿到结果之后才动 state，中途一律不落地。
        //
        // 技能点反推必须走后端的权威预览（PR #97 review [3]）：ruleset 里的
        // base 有公式型（闪避 = DEX/2、母语 = EDU），前端把公式串当 0 处理会
        // 把「基础 25 + 加 15」的闪避 40 误读成「加了 40 点」，提交时再叠一次
        // base 变成 65。preview 的 skillView.allocated 是后端用同一份属性算
        // 出来的，没有歧义。
        //
        // 但这就意味着水合要发两个请求，**顺序很要紧**：先把属性/基本信息填
        // 进表单再去 await preview，一旦 preview 失败（token 过期、网络抖动、
        // 后端 500），下面的 catch 只会静默吞掉，用户看到的是「属性来自后端、
        // 技能却全是 0」这种半截状态——技能页还没有任何错误提示，此时点完成
        // 就会把技能点清空覆盖回后端。所以改成先算后填：失败就整体不水合，
        // 退回本地缓存/空白表单，跟"压根没读回来"是同一种一致状态。
        const view = await previewCharacter({
          attributes: saved.attributes,
          occupationId: matched?.id ?? null,
          skills: saved.skills ?? {},
        })
        if (cancelled) return

        // skillAlloc 和 interestAlloc 两份状态都要重建（PR #97 review [4]）：
        // 兴趣技能的行和计数器读的是 interestAlloc，只重建 skillAlloc 的话，
        // 清掉本地缓存后兴趣技能显示成 0 点、兴趣预算 bar 也是空的。
        // 拆分口径跟后端记账保持一致（coc7_rules：职业技能上的点数全算职业点、
        // 其余全算兴趣点），所以从最终值可以无歧义地还原出这两份状态。
        const occIds = new Set(matched?.skillIds ?? [])
        const alloc: Record<string, number> = {}
        const interest: Record<string, number> = {}
        for (const v of view.skillView) {
          if (v.allocated <= 0) continue
          alloc[v.id] = v.allocated
          // 信用评级不进 interestAlloc：它不在任何职业的 skillIds 里，但也不是
          // 普通兴趣技能——两条 bar 是用 creditMin / 超出部分单独记它的账
          // （见下面的 occPointsSpent / interestPointsSpent），放进来会重复计一遍。
          if (v.id === 'credit-rating') continue
          if (!occIds.has(v.id)) interest[v.id] = v.allocated
        }

        setAttr({ ...saved.attributes })
        // 每个字段都无条件覆盖（PR #97 review [2]）：只在后端值非空时才赋值的话，
        // 服务端被清空的字段会保留本地缓存里的旧值，下一次保存又把它写回去——
        // 删掉的背景/笔记/装备会"复活"。后端是唯一事实来源，空值也是事实。
        setInfo(prev => ({
          ...prev,
          name: saved.name ?? '',
          age: saved.age != null ? String(saved.age) : '',
          gender: saved.gender ?? '',
          residence: saved.residence ?? '',
          birthplace: saved.birthplace ?? '',
          // 职业名映射不回 ruleset（比如规则改版删了这个职业）时保持原样，
          // 别把已选职业清成 null——那会连带清掉技能预算。
          ...(matched ? { occupationId: matched.id } : {}),
        }))
        setBackground(saved.background ?? '')
        setNotes(saved.notes ?? '')
        setEquipment((saved.equipment ?? []).join('、'))
        setSkillAlloc(alloc)
        setInterestAlloc(interest)
        // 后端那份已经是权威，别再让 localStorage 那条重建逻辑覆盖回去。
        interestAllocInitialized.current = true
      })
      .catch(() => {
        // 读不回来（比如还没建过草稿）就沿用本地缓存/空白表单，不打断建卡。
      })
    return () => { cancelled = true }
  }, [ruleset])

  // ruleset 到达后，把缺失的属性补上默认值。
  //
  // 不能在 useState 初始值里做：ruleset 是异步拉的，首次渲染时还没有。放在
  // 这里还顺带解决了「本地存的旧角色少了新属性」——后端加了一项属性，旧卡缺
  // 那个键时会在这里被补齐，而不是带着残缺结构提交上去被校验拒（PR #88 加
  // 幸运后旧卡打不开就是这个问题）。
  useEffect(() => {
    if (!ruleset || !pointBuyRules) return
    setAttr(prev => {
      const filled = { ...prev }
      let changed = false
      for (const attribute of ruleset.attributes) {
        if (typeof filled[attribute.key] !== 'number') {
          filled[attribute.key] = pointBuyRules.defaultValue
          changed = true
        }
      }
      return changed ? filled : prev
    })
  }, [ruleset, pointBuyRules])

  // 属性总点数只统计可购买的那几项，不能用 Object.values(attr)——那样会把不占
  // 预算的幸运也算进去，凭空吃掉 50 点。
  const attrPointsTotal = pointBuyAttributes.reduce((sum, a) => sum + (attr[a.key] ?? 0), 0)

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
        attributes: attr,
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
      // 信用评级由 creditMin / 超出部分单独记账，不能当普通兴趣技能算一遍
      // （跟上面从后端重建那份保持同一个口径）。
      if (id === 'credit-rating') continue
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

  // 输入框的字符串态跟 attr 同步（attr 会在 ruleset 到达时被补上默认值）。
  const [attrInputs, setAttrInputs] = useState<Record<string, string>>({})
  useEffect(() => {
    setAttrInputs(Object.fromEntries(pointBuyAttributes.map(a => [a.key, String(attr[a.key] ?? '')])))
    // 只在属性项集合变化时重建；单项数值的变化由各自的 onChange 维护，
    // 否则每敲一个字都会被这里覆盖回去。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointBuyAttributes])

  // 只累加「可购买」的其余属性——之前这里用 Object.entries(prev) 把幸运也算了
  // 进去，等于凭空占掉 50 点预算，加点上限实际卡在 430 而不是 480。
  const sumOtherPointBuy = (values: Attributes, exceptKey: string) =>
    pointBuyAttributes.reduce(
      (sum, a) => (a.key === exceptKey ? sum : sum + (values[a.key] ?? 0)),
      0
    )

  const handleAttrChange = (key: string, delta: number) => {
    if (!pointBuyRules) return
    setAttr(prev => {
      const newVal = Math.max(
        pointBuyRules.minValue,
        Math.min(pointBuyRules.maxValue, (prev[key] ?? 0) + delta)
      )
      if (delta > 0 && sumOtherPointBuy(prev, key) + newVal > pointBuyRules.budget) return prev
      setAttrInputs(inputs => ({ ...inputs, [key]: String(newVal) }))
      return { ...prev, [key]: newVal }
    })
  }

  // 手动输入属性值——允许先清空再打字（不在每次按键就夹值，否则没法删了重打），
  // 只在失焦时校验：范围和总预算都取自后端 ruleset。超出总预算时按"其余属性
  // 还剩多少点"封顶，而不是直接拒绝，体验上比"打了数字却没反应"更清楚。
  const commitAttrInput = (key: string) => {
    if (!pointBuyRules) return
    const raw = parseInt(attrInputs[key], 10)
    setAttr(prev => {
      const maxAllowed = Math.min(
        pointBuyRules.maxValue,
        pointBuyRules.budget - sumOtherPointBuy(prev, key)
      )
      const clamped = Number.isNaN(raw)
        ? (prev[key] ?? pointBuyRules.defaultValue)
        : Math.max(pointBuyRules.minValue, Math.min(maxAllowed, raw))
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
        attributes: attr,
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
        age: info.age ? Number(info.age) : null,
        gender: info.gender || null,
        residence: info.residence,
        birthplace: info.birthplace,
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
                      <input type="number" min={ruleset?.ageRange?.minValue} max={ruleset?.ageRange?.maxValue} value={info.age}
                        onChange={e => setInfo(i => ({ ...i, age: e.target.value }))}
                        onBlur={e => {
                          // 夹值范围必须跟上面 input 的 min/max 用同一个数据源。
                          // 之前这里写死 [10, 100]，属性改成消费后端之后没跟着改，
                          // 结果是「显示的范围是 15-89、实际能填 12 和 90」——
                          // 展示和生效的规则对不上，比两处都写死更难发现。
                          const range = ruleset?.ageRange
                          if (!range) return
                          const typed = parseInt(e.target.value, 10)
                          const v = Number.isNaN(typed)
                            ? range.minValue
                            : Math.max(range.minValue, Math.min(range.maxValue, typed))
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
                <p className="text-[11px] text-text-muted mb-2">点击 +/- 调整属性值（范围 {pointBuyRules?.minValue ?? '—'}-{pointBuyRules?.maxValue ?? '—'}，每次 ±5）</p>
                <div className="bg-panel rounded-md px-3.5 py-2 mb-3 flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] font-medium text-text-muted">总点数</span>
                      <span className="text-[12px] font-bold font-mono text-text-primary">{attrPointsTotal}<span className="text-text-dim font-normal">/{pointBuyRules?.budget ?? '—'}</span></span>
                    </div>
                    <div className="h-1.5 rounded-full bg-border-light overflow-hidden">
                      <div className="h-full rounded-full bg-brass transition-all duration-300" style={{ width: `${pointBuyRules ? Math.min(100, (attrPointsTotal / pointBuyRules.budget) * 100) : 0}%` }} />
                    </div>
                  </div>
                  <span className="text-[10px] text-text-dim">{pointBuyRules ? pointBuyRules.budget - attrPointsTotal : 0} 点剩余</span>
                </div>
                <div className="grid grid-cols-1 gap-2">
                  {pointBuyAttributes.map(attribute => {
                    const key = attribute.key
                    const Icon = ATTR_ICONS[key] || Shield
                    const color = ATTR_COLORS[key] || '#b8976a'
                    const val = attr[key] ?? 0
                    return (
                      <div key={key} className="flex items-center gap-3 px-3 py-2.5 bg-input border border-border-light rounded-[6px]">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                          <Icon className="w-4 h-4" style={{ color }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-semibold text-text-primary flex items-center gap-1.5">
                            {attribute.label}
                            <span className="text-[10px] font-mono text-text-dim font-normal">{key}</span>
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
                          min={pointBuyRules?.minValue}
                          max={pointBuyRules?.maxValue}
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

                {/* 不参与点数购买的属性（COC7 里就是幸运：只能掷、不能用属性点买）。
                    同样由 ruleset 驱动，不写死是哪一项——换个规则系统这里自然跟着变。 */}
                {(ruleset?.attributes ?? []).filter(a => !a.pointBuy).map(attribute => (
                  <div key={attribute.key} className="flex items-center gap-3 px-3 py-2.5 mt-2 bg-panel border border-border-light rounded-[6px]">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: '#4a8a4a18' }}>
                      <Clover className="w-4 h-4" style={{ color: '#4a8a4a' }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-semibold text-text-primary flex items-center gap-1.5">
                        {attribute.label}
                        <span className="text-[10px] font-mono text-text-dim font-normal">{attribute.key}</span>
                      </div>
                      <div className="text-[10px] text-text-dim mt-0.5">不占属性点数（规则为独立掷 {attribute.generation}，掷骰生成待接入，暂为默认值）</div>
                    </div>
                    <span className="text-[17px] font-bold font-mono text-text-primary min-w-[36px] text-center">{attr[attribute.key] ?? '—'}</span>
                  </div>
                ))}
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
                    const cap = compute?.cap ?? null
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
                    const cap = compute?.cap ?? null
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
