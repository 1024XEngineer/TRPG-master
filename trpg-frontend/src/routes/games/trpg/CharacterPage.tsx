import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useState, useMemo, useEffect, useRef } from 'react'
import { Plus, Minus, Search, Shield, Heart, Brain, Zap, Eye, Maximize2, Lightbulb, BookOpen, ChevronDown, ChevronUp, X, Info, Clover, Sparkles } from 'lucide-react'
import type { CharacterComputeResult, SkillComputeView } from 'trpg-sdk'
import type { Attributes, InvestigatorInfo } from '@/data/character-model'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { createCharacterDraft, saveCharacter, completeCharacter, fetchCharacter, quickGenerateCharacter, type BuiltCharacter } from '@/services/character/character-api'
import type { CharacterTemplate } from '@/services/character/template-api'
import {
  characterReadFromTemplate,
  listCharacterTemplates,
  getCharacterTemplate,
  quickGenerateResultAsCharacter,
  quickGenerateTemplate,
  templateDataFromBuilt,
  updateCharacterTemplate,
} from '@/services/character/template-api'
import { previewCharacter, translateCharacterValidationError } from '@/services/character/ruleset-api'
import { ApiError, disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
import { useRuleset } from '@/hooks/useRuleset'
import type { OccupationSpec, SkillSpec } from '@/data/types'
import {
  BACKGROUND_SECTION_DEFINITIONS,
  CHARACTER_BACKGROUND_MAX_LENGTH,
  parseCharacterBackground,
  serializeCharacterBackground,
} from '@/data/character-background'
import type { BackgroundSectionKey } from '@/data/character-background'
import {
  DERIVED_STAT_DEFINITIONS,
  normalizeDerivedStats,
} from '@/data/derived-stats'
import { OnboardingTrigger } from '@/features/onboarding'

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

// 这些是 COC 新手教学文案，不参与规则计算；属性集合、点数限制和生成公式
// 仍然以后端 ruleset 为准。
const ATTRIBUTE_HELP: Record<string, string> = {
  STR: '衡量肌肉力量与爆发力。常用于推、拉、举起、攀住目标和近战力量对抗，也参与伤害加值与体格计算。',
  CON: '衡量健康程度与持久力。它会影响生命值，也常用于抵抗疾病、毒素、疲劳和昏迷。',
  POW: '衡量意志与精神力量。它决定初始理智和魔法值，也常用于抵抗精神影响或进行意志对抗。',
  DEX: '衡量反应速度与身体协调。它常影响行动顺序，并用于闪避、敏捷动作和精细操作。',
  APP: '衡量外貌、气质与第一印象。它会影响陌生人的初始态度，但不能代替取悦、说服等社交技能。',
  SIZ: '综合表示调查员的身高与体重。它参与生命值、伤害加值和体格计算；体型大不等于力量高。',
  INT: '衡量理解、推理与临场判断。它决定兴趣技能点，也常用于灵感和线索联想相关的判断。',
  EDU: '衡量正式教育与知识积累。它常参与职业技能点计算，也反映调查员可以调用的常识与专业知识。',
  LUCK: '表示不由个人能力决定的偶然运气，用于幸运检定。它不占属性点，按 COC 规则独立生成。',
}

const BACKGROUND_PLACEHOLDERS: Record<BackgroundSectionKey, string> = {
  personalDescription: '外貌、衣着、举止或给人的第一印象……',
  ideologyBeliefs: '角色坚持的原则、信仰或世界观……',
  significantPeople: '对角色影响深远的人，以及彼此的关系……',
  meaningfulLocations: '承载重要回忆或意义的地点……',
  treasuredPossessions: '角色珍视的物品及其来历……',
  traits: '性格特点、习惯或待人处事方式……',
  injuriesScars: '身体或心理上留下的伤痕……',
  phobiasManias: '角色恐惧、执着或难以控制的倾向……',
}

const EMPTY_CHOICE_SELECTIONS: string[][] = []

function occupationIcon(occupation: Pick<OccupationSpec, 'icon'>): string {
  return occupation.icon ?? '·'
}

function occupationSkillLabel(skillId: string, skills: SkillSpec[]): string {
  return skills.find(skill => skill.id === skillId)?.name ?? skillId
}

async function previewWithAllocations(
  attributes: Attributes,
  occupationId: number | null,
  allocations: Record<string, number>,
  occupationChoiceSkillIds: string[],
  generationMethod: 'pointbuy' | 'roll' = 'pointbuy',
) {
  const basePreview = await previewCharacter({
    attributes,
    occupationId,
    skills: {},
    occupationChoiceSkillIds,
    generationMethod,
  })
  const allocatedSkills = Object.entries(allocations).filter(([, points]) => points > 0)
  if (allocatedSkills.length === 0) {
    return { preview: basePreview, skillValues: {} }
  }

  const baseBySkill = new Map(basePreview.skillView.map(skill => [skill.id, skill.base]))
  const skillValues = Object.fromEntries(
    allocatedSkills.map(([id, points]) => [id, (baseBySkill.get(id) ?? 0) + points])
  )
  const preview = await previewCharacter({
    attributes,
    occupationId,
    skills: skillValues,
    occupationChoiceSkillIds,
    generationMethod,
  })
  return { preview, skillValues }
}

type OccupationChoiceSlot = NonNullable<OccupationSpec['choiceSlots']>[number]

function splitChoiceSkillIds(
  slots: OccupationChoiceSlot[],
  skillIds: string[],
): string[][] {
  let offset = 0
  return slots.map(slot => {
    const selected = skillIds.slice(offset, offset + slot.count)
    offset += slot.count
    return selected
  })
}

// ─── SkillRow Component ──────────────────────────────
function SkillRow({
  skill, base, cap, poolAllocation, onChange, onSetAllocation, maxPoints, minPoints
}: {
  skill: SkillSpec
  base: number
  // 后端还没返回权威计算结果时是 null——此时不允许加点，而不是前端自己编一个
  // 上限（原来写死兜底 99，等于在后端沉默时凭空造了一条规则，issue #96 决策 4）。
  cap: number | null
  poolAllocation: number
  onChange: (delta: number) => void
  onSetAllocation: (allocation: number) => void
  maxPoints: number
  minPoints: number
}) {
  const current = base + poolAllocation
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
    const maxAllocByCap = Math.min(maxPoints, cap - base)
    const newAlloc = Math.max(minPoints, Math.min(maxAllocByCap, typed - base))
    onSetAllocation(newAlloc)
    setInputValue(String(base + newAlloc))
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
        aria-label={`${skill.name} 减少技能点`}
        onClick={() => onChange(-1)}
        className={`w-6 h-6 rounded-full flex items-center justify-center transition-all ${
          canSub ? 'bg-card border border-border-light text-text-muted active:bg-panel active:scale-90' : 'bg-transparent text-border-light cursor-not-allowed'
        }`}
        disabled={!canSub}
      >
        <Minus className="w-3 h-3" />
      </button>
      <input
        aria-label={`${skill.name} 技能点`}
        type="number"
        inputMode="numeric"
        value={inputValue}
        onChange={e => setInputValue(e.target.value)}
        onBlur={commitInput}
        className="text-[15px] font-bold font-mono text-text-primary min-w-[28px] w-[34px] text-center bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
      <button
        aria-label={`${skill.name} 增加技能点`}
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
  // 建卡宿主（#337 决策 A）：路由带 templateId 就是在给卡库卡建卡，否则是房间卡。
  // 两者共用整套向导——它们本来就是同一种东西的两份拷贝，区别只在"存到哪、
  // 存完去哪"。房间卡还要 complete（房间状态机要知道这个人准备好了），卡库卡
  // 没有这一步：它不属于任何一局。
  const { templateId } = useParams<{ templateId: string }>()
  const templateHostId = templateId ?? null
  const isTemplateHost = templateHostId !== null
  const location = useLocation()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [confirmExit, setConfirmExit] = useState(false)
  const isEditingExistingCharacter = Boolean(
    (location.state as { fromCharacterReady?: boolean } | null)?.fromCharacterReady
  )
  const characterPageRef = useRef<HTMLDivElement>(null)

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

  const [generationMethod, setGenerationMethod] = useState<'pointbuy' | 'roll'>(
    existingCharacter?.generationMethod ?? 'pointbuy'
  )

  // Investigator info
  const [info, setInfo] = useState<InvestigatorInfo>(() => existingCharacter?.info ?? {
    name: '', playerName: '', age: '28', gender: '男',
    residence: '阿卡姆', birthplace: '阿卡姆', occupationId: null,
  })

  // Attributes
  const [attr, setAttr] = useState<Attributes>(() => ({ ...existingCharacter?.attr }))
  const [attributeHelpKey, setAttributeHelpKey] = useState<string | null>(null)

  // 职业自选技能按槽位分组保存在表单中；提交时再按槽位顺序压平成 API 的
  // occupationChoiceSkillIds。occupationId 跟选择放在同一份状态里，避免异步
  // 水合或切换职业时把上一职业的槽位误套到新职业。
  const [occupationChoiceState, setOccupationChoiceState] = useState<{
    occupationId: number | null
    selections: string[][]
  }>({ occupationId: null, selections: [] })

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
    if (!ruleset) return
    const roomId = useRoomStore.getState().roomId
    const characterId = useRoomStore.getState().characterId
    // 卡库宿主没有房间，也没有 characterId；读的是那张卡库卡，摊平成向导已经
    // 会读的形状后走同一条水合路径（属性 → 权威 preview 反推技能点 → 填表单）。
    const load = templateHostId
      ? getCharacterTemplate(templateHostId).then(characterReadFromTemplate)
      : roomId && characterId
        ? fetchCharacter(roomId, characterId)
        : null
    if (!load) return

    let cancelled = false
    load
      .then(async saved => {
        if (cancelled || !saved.attributes || Object.keys(saved.attributes).length === 0) return
        // 存成局部常量：下面几处在闭包里用到它，直接写 saved.attributes 会丢掉
        // 上面这行的收窄，TS 认为它仍可能是 undefined。
        const savedAttrs = saved.attributes
        const savedGenerationMethod: 'pointbuy' | 'roll' = saved.generationMethod === 'roll'
          ? 'roll'
          : 'pointbuy'
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
          attributes: savedAttrs,
          occupationId: matched?.id ?? null,
          skills: saved.skills ?? {},
          occupationChoiceSkillIds: saved.occupationChoiceSkillIds ?? null,
          generationMethod: savedGenerationMethod,
        })
        if (cancelled) return

        const hydratedChoiceSkillIds = saved.occupationChoiceSkillIds
          ?? view.resolvedOccupationChoiceSkillIds
          ?? []

        // skillAlloc 和 interestAlloc 两份状态都要重建（PR #97 review [4]）：
        // 兴趣技能的行和计数器读的是 interestAlloc，只重建 skillAlloc 的话，
        // 清掉本地缓存后兴趣技能显示成 0 点、兴趣预算 bar 也是空的。
        // 拆分口径跟后端记账保持一致（coc7_rules：职业技能上的点数全算职业点、
        // 其余全算兴趣点），所以从最终值可以无歧义地还原出这两份状态。
        const occIds = new Set([
          ...(matched?.skillIds ?? []),
          ...hydratedChoiceSkillIds,
        ])
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

        setAttr({ ...savedAttrs })
        setGenerationMethod(savedGenerationMethod)
        // 输入框的字符串镜像必须一起重建。它平时只在「属性项集合变化」时同步
        // 一次（见下面 attrInputs 那个 effect：跟着 attr 走的话，每敲一个字都会
        // 被覆盖回去），而水合是之后才异步到达的——不在这里补一次，清掉本地
        // 缓存重进时 8 个属性输入框会**全是空白**，尽管背后的 attr 是对的
        // （总点数条 400/480 和衍生值都正常，只有输入框空着）。
        setAttrInputs(
          Object.fromEntries(
            ruleset.attributes
              .filter(a => a.pointBuy)
              .map(a => [a.key, String(savedAttrs[a.key] ?? '')])
          )
        )
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
        setBackgroundForm(parseCharacterBackground(saved.background ?? ''))
        setNotes(saved.notes ?? '')
        setEquipment((saved.equipment ?? []).join('、'))
        setSkillAlloc(alloc)
        setInterestAlloc(interest)
        setOccupationChoiceState({
          occupationId: matched?.id ?? null,
          selections: splitChoiceSkillIds(matched?.choiceSlots ?? [], hydratedChoiceSkillIds),
        })
        // 后端那份已经是权威，别再让 localStorage 那条重建逻辑覆盖回去。
        interestAllocInitialized.current = true
      })
      .catch(() => {
        // 读不回来（比如还没建过草稿）就沿用本地缓存/空白表单，不打断建卡。
      })
    return () => { cancelled = true }
  }, [ruleset, templateHostId])

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
  const [backgroundForm, setBackgroundForm] = useState(() =>
    parseCharacterBackground(existingCharacter?.background ?? '')
  )
  const [notes, setNotes] = useState(existingCharacter?.notes ?? '')
  const serializedBackground = useMemo(
    () => serializeCharacterBackground(backgroundForm),
    [backgroundForm]
  )

  const updateBackgroundSection = (key: BackgroundSectionKey, value: string) => {
    setBackgroundForm(previous => ({
      ...previous,
      sections: { ...previous.sections, [key]: value },
    }))
  }

  // UI state
  const [search, setSearch] = useState('')
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [skillTab, setSkillTab] = useState<'occupation' | 'interest'>('occupation')
  const [showGroupPicker, setShowGroupPicker] = useState(false)
  const [showGenderPicker, setShowGenderPicker] = useState(false)
  const [detailOcc, setDetailOcc] = useState<OccupationSpec | null>(null)
  const [choicePickerSlotIndex, setChoicePickerSlotIndex] = useState<number | null>(null)
  const [choiceSkillSearch, setChoiceSkillSearch] = useState('')
  const [choiceActionError, setChoiceActionError] = useState('')
  const [quickGenerating, setQuickGenerating] = useState(false)
  const [quickGenerateError, setQuickGenerateError] = useState('')
  // 车卡界面与卡库之间的两条通路（#337）：把当前这张存进卡库，或从卡库选一张
  // 播种成本房间的草稿。只对房间宿主成立——卡库宿主本身就在编辑卡库卡。
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [libraryCards, setLibraryCards] = useState<CharacterTemplate[] | null>(null)
  const [libraryError, setLibraryError] = useState('')
  const [libraryBusy, setLibraryBusy] = useState(false)
  const [showQuickGenerateConfirm, setShowQuickGenerateConfirm] = useState(false)

  const selectedOcc = useMemo(() => {
    if (!ruleset || info.occupationId == null) return null
    return ruleset.occupations.find(o => o.id === info.occupationId) ?? null
  }, [ruleset, info.occupationId])

  useEffect(() => {
    if (!selectedOcc) {
      if (occupationChoiceState.occupationId !== null) {
        setOccupationChoiceState({ occupationId: null, selections: [] })
      }
      return
    }
    if (occupationChoiceState.occupationId === selectedOcc.id) return
    const cachedSkillIds = existingCharacter?.info.occupationId === selectedOcc.id
      ? (existingCharacter.occupationChoiceSkillIds ?? [])
      : []
    setOccupationChoiceState({
      occupationId: selectedOcc.id,
      selections: splitChoiceSkillIds(selectedOcc.choiceSlots ?? [], cachedSkillIds),
    })
  }, [existingCharacter, occupationChoiceState.occupationId, selectedOcc])

  const occupationChoiceSelections = selectedOcc
    && occupationChoiceState.occupationId === selectedOcc.id
    ? occupationChoiceState.selections
    : EMPTY_CHOICE_SELECTIONS
  const occupationChoiceSkillIds = useMemo(
    () => occupationChoiceSelections.flat(),
    [occupationChoiceSelections]
  )
  const selectedChoiceSkillIdSet = useMemo(
    () => new Set(occupationChoiceSkillIds),
    [occupationChoiceSkillIds]
  )
  const occupationChoicesComplete = (selectedOcc?.choiceSlots ?? []).every(
    (slot, index) => (occupationChoiceSelections[index]?.length ?? 0) === slot.count
  )

  const selectOccupation = (occupationId: number | null) => {
    if (occupationId === info.occupationId) return
    const occupation = ruleset?.occupations.find(item => item.id === occupationId) ?? null
    const fixedIds = new Set(occupation?.skillIds ?? [])
    const nextInterest: Record<string, number> = {}
    for (const [skillId, points] of Object.entries(skillAlloc)) {
      if (skillId !== 'credit-rating' && !fixedIds.has(skillId) && points > 0) {
        nextInterest[skillId] = points
      }
    }
    setInfo(previous => ({ ...previous, occupationId }))
    setOccupationChoiceState({
      occupationId,
      selections: (occupation?.choiceSlots ?? []).map(() => []),
    })
    setInterestAlloc(nextInterest)
    setPendingOccupationDelta(0)
    setPendingInterestDelta(0)
    setChoicePickerSlotIndex(null)
    setChoiceSkillSearch('')
    setChoiceActionError('')
  }

  const selectedOccupationSkillPreview = useMemo(() => {
    if (!ruleset || !selectedOcc) return []
    const fixed = selectedOcc.skillIds.map(id => occupationSkillLabel(id, ruleset.skills))
    const slots = (selectedOcc.choiceSlots ?? []).map(slot => slot.label)
    return [...fixed, ...slots]
  }, [ruleset, selectedOcc])

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

  const occupationCategories = useMemo(() => {
    if (!ruleset) return []
    if (ruleset.occupationCategories?.length) return ruleset.occupationCategories
    const labels = Array.from(
      new Set(ruleset.occupations.flatMap(occupation => occupation.categories ?? []))
    )
    return labels.map(label => ({ label, icon: '' }))
  }, [ruleset])

  // Filter occupations by search and group
  const filteredOccupations = useMemo(() => {
    if (!ruleset) return []
    let list = ruleset.occupations
    if (activeGroup) {
      list = list.filter(o => (o.categories ?? []).includes(activeGroup))
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
    const fixed = ruleset.occupations.find(o => o.id === info.occupationId)?.skillIds ?? []
    return [...fixed, ...occupationChoiceSkillIds]
  }, [ruleset, info.occupationId, occupationChoiceSkillIds])

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
  // 衍生值/技能点预算/每个技能的 base·cap/校验报告 + **两条 bar 的"已花"**全部
  // 来自这里，前端不再本地重算 COC7 规则数值。
  //
  // issue #114 之前这里刻意只在属性/职业变化时请求、不带 skills：那时"已花"是
  // 「occSkillIds 里的算职业点、其余算兴趣点」这种平凡算术，前端本地算即可。但
  // 职业技能 = 固定 + 自选槽后，某个技能的点数算职业还是兴趣，取决于后端的全局
  // 最优占槽（后端匹配器会处理开放槽与限定槽重叠），前端无法在不
  // 复刻规则的前提下算对。所以现在**把当前 skillAlloc 一起发过去、并在它变化时
  // （防抖）重新预演**，"已花"直接读后端返回的 occupationSkillPoints.spent /
  // interestSkillPoints.spent。代价是加点后数字有 ~400ms 防抖延迟。
  const [preview, setPreview] = useState<CharacterComputeResult | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [previewStatus, setPreviewStatus] = useState<'idle' | 'pending' | 'ready' | 'error'>('idle')

  // 请求代次守卫：清 debounce 的 timer 只能取消"还没发出"的下一次调用，取消
  // 不了已经在飞的那次网络请求——如果旧请求比新请求慢返回，会用过期数据
  // 覆盖新状态。每次真正发请求前 +1 代，回调里只有当自己仍是最新一代时才
  // setPreview/setPreviewError。
  const previewGenRef = useRef(0)

  // 加点手感依赖同步反馈，但预算数字要等 preview 防抖+网络往返才更新——两者
  // 之间有个窗口：连续快点"+"时，每次判断都在拿同一份还没反映最新点数的旧
  // spent 算"剩余"，会被越过预算。这里按预算池分别记一个"已落到本地状态、
  // 但还没被最新一次 preview 确认"的净加点数，只影响还能不能继续加，不影响
  // 两条 bar 本身的显示值（那两个数字仍然只读 preview.spent，见下）。
  const [pendingOccupationDelta, setPendingOccupationDelta] = useState(0)
  const [pendingInterestDelta, setPendingInterestDelta] = useState(0)

  useEffect(() => {
    if (!ruleset) return
    setPreviewStatus('pending')
    const timer = setTimeout(() => {
      const gen = ++previewGenRef.current
      previewWithAllocations(
        attr,
        info.occupationId,
        skillAlloc,
        occupationChoiceSkillIds,
        generationMethod,
      )
        .then(({ preview: result }) => {
          if (gen !== previewGenRef.current) return
          setPreview(result)
          setPreviewError('')
          setPreviewStatus('ready')
          setPendingOccupationDelta(0)
          setPendingInterestDelta(0)
        })
        .catch((err) => {
          if (gen !== previewGenRef.current) return
          setPreviewError(friendlyErrorMessage(err, '规则计算失败'))
          setPreviewStatus('error')
        })
    }, 400)
    return () => clearTimeout(timer)
  }, [ruleset, attr, info.occupationId, skillAlloc, occupationChoiceSkillIds, generationMethod])

  const skillComputeMap = useMemo(() => {
    const map = new Map<string, SkillComputeView>()
    preview?.skillView.forEach(v => map.set(v.id, v))
    return map
  }, [preview])

  const occPointsTotal = preview?.occupationSkillPoints.budget ?? 0
  const interestPointsTotal = preview?.interestSkillPoints.budget ?? 0

  const previewValidationIssues = preview?.validation ?? []

  // 兴趣技能的局部分配量需要单独保存；职业技能可以先吃职业池，再按 COC7
  // 规则使用剩余兴趣点，因此它们只保存在总分配 skillAlloc 中。
  const [interestAlloc, setInterestAlloc] = useState<Record<string, number>>({})
  const interestAllocInitialized = useRef(false)

  // 编辑已有角色时重建 interestAlloc 需要知道这个职业的技能清单，只有
  // ruleset 到位之后才能算——只在 ruleset 第一次到位时跑一次，不要覆盖用户
  // 之后自己的编辑。
  useEffect(() => {
    if (!ruleset || !existingCharacter || interestAllocInitialized.current) return
    interestAllocInitialized.current = true
    const occIds = new Set(
      [
        ...(ruleset.occupations.find(o => o.id === existingCharacter.info.occupationId)?.skillIds ?? []),
        ...(existingCharacter.occupationChoiceSkillIds ?? []),
      ]
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

  // 后端把所有职业技能投入都记在 occupation.spent 中，即使它已经超过职业预算；
  // 超出的部分在 COC7 中实际由兴趣点承担。显示和前端闸门在这里做同一份转换，
  // 让两条进度条展示玩家真正还剩下的两份预算。
  const rawOccupationPointsSpent = preview?.occupationSkillPoints.spent ?? 0
  const rawInterestPointsSpent = preview?.interestSkillPoints.spent ?? 0
  const confirmedOccupationOverflow = Math.max(0, rawOccupationPointsSpent - occPointsTotal)
  const occPointsSpent = Math.min(rawOccupationPointsSpent, occPointsTotal)
  const interestPointsSpent = rawInterestPointsSpent + confirmedOccupationOverflow

  const projectedOccupationSpent = rawOccupationPointsSpent + pendingOccupationDelta
  const projectedInterestSpent = rawInterestPointsSpent + pendingInterestDelta
  const projectedOccupationOverflow = Math.max(0, projectedOccupationSpent - occPointsTotal)
  const combinedPointsRemaining = Math.max(
    0,
    occPointsTotal + interestPointsTotal - projectedOccupationSpent - projectedInterestSpent,
  )
  const interestPointsRemaining = Math.max(
    0,
    interestPointsTotal - projectedInterestSpent - projectedOccupationOverflow,
  )

  const derived = useMemo(() => normalizeDerivedStats(preview?.derivedStats), [preview])

  const roomId = useRoomStore((s) => s.roomId)
  const setCharacterId = useRoomStore((s) => s.setCharacterId)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [validationAttempted, setValidationAttempted] = useState(false)

  useEffect(() => {
    setValidationAttempted(false)
  }, [step])

  // 兴趣技能页签（只列非职业技能）：只动兴趣点数池。
  const handleInterestSkillChange = (skillId: string, delta: number) => {
    if (delta > 0 && interestPointsRemaining <= 0) return
    const prevInterest = interestAlloc[skillId] || 0
    const nextInterest = Math.max(0, prevInterest + delta)
    const appliedDelta = nextInterest - prevInterest
    setInterestAlloc(prev => ({ ...prev, [skillId]: nextInterest }))
    setSkillAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + appliedDelta }))
    if (appliedDelta !== 0) setPendingInterestDelta(d => Math.max(0, d + appliedDelta))
  }

  const handleInterestSkillSet = (skillId: string, newAllocation: number) => {
    const prevInterest = interestAlloc[skillId] || 0
    let clamped = Math.max(0, newAllocation)
    if (clamped > prevInterest) clamped = Math.min(clamped, prevInterest + interestPointsRemaining)
    setInterestAlloc(prev => ({ ...prev, [skillId]: clamped }))
    setSkillAlloc(prev => ({ ...prev, [skillId]: clamped }))
    const appliedDelta = clamped - prevInterest
    if (appliedDelta !== 0) setPendingInterestDelta(d => Math.max(0, d + appliedDelta))
  }

  // 职业技能先使用职业预算，超过职业预算的部分按 COC7 规则由兴趣预算承担。
  // 因此这里用总剩余点数做闸门；非职业技能仍由上面的 interestPointsRemaining
  // 单独限制，不能反过来借职业点。
  const handleOccSkillChange = (skillId: string, delta: number) => {
    if (delta > 0) {
      if (combinedPointsRemaining <= 0) return
      setSkillAlloc(prev => ({ ...prev, [skillId]: (prev[skillId] || 0) + 1 }))
      setPendingOccupationDelta(d => Math.max(0, d + 1))
    } else if (delta < 0) {
      setSkillAlloc(prev => ({ ...prev, [skillId]: Math.max(0, (prev[skillId] || 0) - 1) }))
      setPendingOccupationDelta(d => Math.max(0, d - 1))
    }
  }

  const handleOccSkillSet = (skillId: string, newTotalAllocation: number) => {
    const prevOcc = skillAlloc[skillId] || 0
    let clamped = Math.max(0, newTotalAllocation)
    if (clamped > prevOcc) clamped = Math.min(clamped, prevOcc + combinedPointsRemaining)
    setSkillAlloc(prev => ({ ...prev, [skillId]: clamped }))
    const appliedDelta = clamped - prevOcc
    if (appliedDelta !== 0) setPendingOccupationDelta(d => Math.max(0, d + appliedDelta))
  }

  const addOccupationChoice = (slotIndex: number, skillId: string) => {
    if (!selectedOcc || selectedChoiceSkillIdSet.has(skillId)) return
    const slot = selectedOcc.choiceSlots?.[slotIndex]
    if (!slot || (occupationChoiceSelections[slotIndex]?.length ?? 0) >= slot.count) return
    setOccupationChoiceState(previous => {
      if (previous.occupationId !== selectedOcc.id) return previous
      const selections = (selectedOcc.choiceSlots ?? []).map((_, index) => [
        ...(previous.selections[index] ?? []),
      ])
      selections[slotIndex].push(skillId)
      return { occupationId: previous.occupationId, selections }
    })
    // 原本作为兴趣技能加过点时保留总分配量，但移出兴趣池的本地镜像；后端
    // preview 会按新的显式职业选择重新给两条预算记账。
    setInterestAlloc(previous => {
      const next = { ...previous }
      delete next[skillId]
      return next
    })
    setPendingOccupationDelta(0)
    setPendingInterestDelta(0)
    setChoiceActionError('')
    if ((occupationChoiceSelections[slotIndex]?.length ?? 0) + 1 >= slot.count) {
      setChoicePickerSlotIndex(null)
      setChoiceSkillSearch('')
    }
  }

  const removeOccupationChoice = (slotIndex: number, skillId: string) => {
    if ((skillAlloc[skillId] ?? 0) > 0) {
      setChoiceActionError(`请先将「${occupationSkillLabel(skillId, ruleset?.skills ?? [])}」的加点清零`)
      return
    }
    setOccupationChoiceState(previous => {
      if (!selectedOcc || previous.occupationId !== selectedOcc.id) return previous
      const selections = previous.selections.map((selection, index) => (
        index === slotIndex ? selection.filter(id => id !== skillId) : [...selection]
      ))
      return { occupationId: previous.occupationId, selections }
    })
    setPendingOccupationDelta(0)
    setPendingInterestDelta(0)
    setChoiceActionError('')
  }

  const activeChoiceSlot = choicePickerSlotIndex == null
    ? null
    : selectedOcc?.choiceSlots?.[choicePickerSlotIndex] ?? null
  const choiceCandidateSkills = useMemo(() => {
    if (!ruleset || !selectedOcc || !activeChoiceSlot) return []
    const fixedIds = new Set(selectedOcc.skillIds)
    const allowedIds = activeChoiceSlot.candidateSkillIds
      ? new Set(activeChoiceSlot.candidateSkillIds)
      : null
    const query = choiceSkillSearch.trim().toLowerCase()
    return ruleset.skills.filter(skill => {
      if (skill.id === 'credit-rating' || skill.id === 'cthulhu-mythos') return false
      if (fixedIds.has(skill.id) || selectedChoiceSkillIdSet.has(skill.id)) return false
      if (allowedIds && !allowedIds.has(skill.id)) return false
      if (!query) return true
      return skill.name.toLowerCase().includes(query)
        || (skill.nameEn ?? '').toLowerCase().includes(query)
    })
  }, [activeChoiceSlot, choiceSkillSearch, ruleset, selectedChoiceSkillIdSet, selectedOcc])

  // 信用评级 +/- ：直接夹在所选职业的 [creditMin, creditMax] 内。信用的
  // base 固定是 0（见后端 SkillSpec），所以 skillAlloc['credit-rating']
  // 本身就是最终信用值，不需要像其它技能那样叠加 base。
  const creditRating = selectedOcc
    ? (skillAlloc['credit-rating'] ?? selectedOcc.creditMin)
    : null

  const handleCreditChange = (delta: number) => {
    if (!selectedOcc) return
    const current = creditRating ?? selectedOcc.creditMin
    const next = Math.max(selectedOcc.creditMin, Math.min(selectedOcc.creditMax, current + delta))
    setSkillAlloc(prev => {
      return { ...prev, 'credit-rating': next }
    })
    setCreditInput(String(next))
  }

  const [creditInput, setCreditInput] = useState('')
  useEffect(() => {
    if (!selectedOcc) {
      setCreditInput('')
      return
    }
    setCreditInput(String(creditRating))
  }, [creditRating, selectedOcc])

  const commitCreditInput = () => {
    if (!selectedOcc) return
    const typed = parseInt(creditInput, 10)
    const current = creditRating ?? selectedOcc.creditMin
    const next = Number.isNaN(typed)
      ? current
      : Math.max(selectedOcc.creditMin, Math.min(selectedOcc.creditMax, typed))
    setSkillAlloc(prev => ({ ...prev, 'credit-rating': next }))
    setCreditInput(String(next))
  }

  // 输入框的字符串态跟 attr 同步（attr 会在 ruleset 到达时被补上默认值）。
  const [attrInputs, setAttrInputs] = useState<Record<string, string>>({})
  useEffect(() => {
    setAttrInputs(Object.fromEntries(pointBuyAttributes.map(a => [a.key, String(attr[a.key] ?? '')])))
    // 输入时只更新 attrInputs；attr 会在失焦或 +/- 后才更新。
  }, [pointBuyAttributes, attr])

  // 只累加「可购买」的其余属性——之前这里用 Object.entries(prev) 把幸运也算了
  // 进去，等于凭空占掉 50 点预算，加点上限实际卡在 430 而不是 480。
  const sumOtherPointBuy = (values: Attributes, exceptKey: string) =>
    pointBuyAttributes.reduce(
      (sum, a) => (a.key === exceptKey ? sum : sum + (values[a.key] ?? 0)),
      0
    )

  const handleAttrChange = (key: string, delta: number) => {
    if (!pointBuyRules) return
    const current = attr[key] ?? 0
    const newVal = Math.max(
      pointBuyRules.minValue,
      Math.min(pointBuyRules.maxValue, current + delta)
    )
    if (generationMethod !== 'roll' && delta > 0 && sumOtherPointBuy(attr, key) + newVal > pointBuyRules.budget) return
    if (newVal === current) return
    setGenerationMethod('pointbuy')
    setAttrInputs(inputs => ({ ...inputs, [key]: String(newVal) }))
    setAttr(prev => ({ ...prev, [key]: newVal }))
  }

  // 手动输入属性值——允许先清空再打字（不在每次按键就夹值，否则没法删了重打），
  // 只在失焦时校验：范围和总预算都取自后端 ruleset。超出总预算时按"其余属性
  // 还剩多少点"封顶，而不是直接拒绝，体验上比"打了数字却没反应"更清楚。
  const commitAttrInput = (key: string) => {
    if (!pointBuyRules) return
    const raw = parseInt(attrInputs[key], 10)
    const current = attr[key] ?? pointBuyRules.defaultValue
    const maxAllowed = generationMethod === 'roll'
      ? pointBuyRules.maxValue
      : Math.min(
          pointBuyRules.maxValue,
          pointBuyRules.budget - sumOtherPointBuy(attr, key)
        )
    const clamped = Number.isNaN(raw)
      ? current
      : Math.max(pointBuyRules.minValue, Math.min(maxAllowed, raw))
    setAttrInputs(inputs => ({ ...inputs, [key]: String(clamped) }))
    if (clamped !== current) {
      setGenerationMethod('pointbuy')
      setAttr(prev => ({ ...prev, [key]: clamped }))
    }
  }

  const hasQuickGenerateDraft = Boolean(
    info.occupationId != null
      || Object.values(skillAlloc).some(value => value > 0)
      || serializedBackground.trim()
      || equipment.trim()
      || notes.trim()
  )

  const hydrateQuickGeneratedCharacter = async (
    result: Awaited<ReturnType<typeof quickGenerateCharacter>>,
    roomId: string,
    playerInfo: InvestigatorInfo,
    // 生成结果怎么落库由宿主决定：房间要 save + complete，卡库那边服务端在
    // quick-generate 里已经写进卡了，这里就什么都不用做。把这一步做成参数，
    // 免得为第二个宿主复制一份状态回填代码（那才是真正长的部分）。
    persist: (built: BuiltCharacter) => Promise<void>,
  ) => {
    const generated = result.character
    const generatedOccupation = ruleset?.occupations.find(occupation => occupation.id === result.occupationId)
    const generatedChoiceIds = generated.occupationChoiceSkillIds ?? result.compute.resolvedOccupationChoiceSkillIds ?? []
    const generatedAllocations = Object.fromEntries(
      result.compute.skillView
        .filter(skill => skill.allocated > 0)
        .map(skill => [skill.id, skill.allocated])
    )
    const occupationSkillIds = new Set([
      ...(generatedOccupation?.skillIds ?? []),
      ...generatedChoiceIds,
    ])
    const generatedInterestAllocations = Object.fromEntries(
      Object.entries(generatedAllocations).filter(([skillId]) => (
        skillId !== 'credit-rating' && !occupationSkillIds.has(skillId)
      ))
    )
    const finalDerived = normalizeDerivedStats(result.compute.derivedStats)
    const skillFinalValues = Object.fromEntries(
      result.compute.skillView.map(skill => [skill.id, skill.current])
    )

    await persist({
      name: playerInfo.name.trim(),
      age: playerInfo.age ? Number(playerInfo.age) : null,
      gender: playerInfo.gender || null,
      residence: playerInfo.residence,
      birthplace: playerInfo.birthplace,
      attr: generated.attributes ?? {},
      derived: { hp: finalDerived.hp, san: finalDerived.san, mp: finalDerived.mp },
      skillValues: skillFinalValues,
      occupationChoiceSkillIds: generatedChoiceIds,
      equipment: generated.equipment ?? [],
      occupationName: generated.occupation ?? generatedOccupation?.name ?? null,
      background: generated.background ?? '',
      notes: generated.notes ?? '',
    })

    setGenerationMethod('roll')
    const generatedInfo: InvestigatorInfo = {
      ...playerInfo,
      name: playerInfo.name.trim(),
      playerName: playerInfo.playerName || playerInfo.name.trim(),
      occupationId: result.occupationId,
    }
    setInfo(previous => ({
      ...previous,
      name: generatedInfo.name,
      age: generatedInfo.age,
      gender: generatedInfo.gender,
      residence: generatedInfo.residence,
      birthplace: generatedInfo.birthplace,
      occupationId: result.occupationId,
    }))
    setAttr({ ...(generated.attributes ?? {}) })
    setAttrInputs(Object.fromEntries(
      (ruleset?.attributes ?? [])
        .filter(attribute => attribute.pointBuy)
        .map(attribute => [attribute.key, String(generated.attributes?.[attribute.key] ?? '')])
    ))
    setSkillAlloc(generatedAllocations)
    setInterestAlloc(generatedInterestAllocations)
    setOccupationChoiceState({
      occupationId: result.occupationId,
      selections: splitChoiceSkillIds(generatedOccupation?.choiceSlots ?? [], generatedChoiceIds),
    })
    setEquipment((generated.equipment ?? []).join('、'))
    setBackgroundForm(parseCharacterBackground(generated.background ?? ''))
    setNotes(generated.notes ?? '')
    setPreview(result.compute)
    setPreviewError('')
    setPreviewStatus('ready')
    setPendingOccupationDelta(0)
    setPendingInterestDelta(0)
    setValidationAttempted(false)
    setQuickGenerateError('')
    useCharacterStore.getState().setCharacter(
      {
        info: generatedInfo,
        generationMethod: 'roll',
        attr: { ...(generated.attributes ?? {}) },
        skillAlloc: generatedAllocations,
        skillFinalValues,
        occupationChoiceSkillIds: [...generatedChoiceIds],
        equipment: (generated.equipment ?? []).join('、'),
        background: generated.background ?? '',
        notes: generated.notes ?? '',
        derived: finalDerived,
      },
      roomId
    )
    navigate(isTemplateHost ? '/home/characters' : '/room/ready')
  }

  const runQuickGenerate = async () => {
    if (!ruleset || quickGenerating) return
    if (!templateHostId && !roomId) return
    setQuickGenerating(true)
    setQuickGenerateError('')
    setShowQuickGenerateConfirm(false)
    try {
      if (templateHostId) {
        // 服务端在 quick-generate 里已经把结果写进这张卡并背书 roll 了，所以
        // 回填之后不再写一次——再 PATCH 一遍属性反而会把那条背书降级成点数
        // 购买法（见后端 `_data_with_attested_generation_method`）。
        const generated = await quickGenerateTemplate(templateHostId, {
          name: info.name,
          age: info.age ? Number(info.age) : null,
          gender: info.gender,
          residence: info.residence,
          birthplace: info.birthplace,
        })
        const asCharacter = quickGenerateResultAsCharacter(
          templateHostId,
          info.name.trim(),
          generated,
        )
        await hydrateQuickGeneratedCharacter(
          { character: asCharacter, occupationId: generated.occupationId ?? 0, compute: generated.compute! },
          '',
          { ...info },
          async () => {},
        )
        return
      }
      const activeRoomId = roomId as string
      let characterId = useRoomStore.getState().characterId
      if (!characterId) {
        characterId = await createCharacterDraft(activeRoomId)
        setCharacterId(characterId)
      }
      const result = await quickGenerateCharacter(activeRoomId, characterId, { ...info })
      const draftId = characterId
      await hydrateQuickGeneratedCharacter(result, activeRoomId, { ...info }, async (built) => {
        await saveCharacter(activeRoomId, draftId, built)
        // 一键生成的接口先保存为草稿；进入 ready 前完成同一张卡，确保房间状态和
        // 头像生成接口都能把它视为已完成角色，而不是一个无法生图的半成品。
        await completeCharacter(activeRoomId, draftId)
      })
    } catch (err) {
      setQuickGenerateError(friendlyErrorMessage(err, '一键生成失败，请稍后重试'))
    } finally {
      setQuickGenerating(false)
    }
  }

  const handleQuickGenerate = () => {
    if (quickGenerating) return
    if (!info.name.trim()) {
      setQuickGenerateError('请先填写调查员姓名，姓名和性别由你自己决定。')
      setValidationAttempted(true)
      return
    }
    if (!info.gender.trim()) {
      setQuickGenerateError('请先选择调查员性别，姓名和性别由你自己决定。')
      setValidationAttempted(true)
      return
    }
    if (hasQuickGenerateDraft) {
      setShowQuickGenerateConfirm(true)
      return
    }
    void runQuickGenerate()
  }

  const adjustAge = (delta: number) => {
    const range = ruleset?.ageRange
    if (!range) return
    const parsed = parseInt(info.age, 10)
    const candidate = Number.isNaN(parsed) ? range.minValue : parsed + delta
    const nextAge = Math.max(range.minValue, Math.min(range.maxValue, candidate))
    setInfo(current => ({ ...current, age: String(nextAge) }))
  }

  const steps = [
    { label: '基础信息', key: 'info' },
    { label: '属性', key: 'attr' },
    { label: '技能', key: 'skill' },
    { label: '背景', key: 'background' },
  ]

  // 书签用于浏览和补填不同书页，不强制按顺序访问；底部「下一步」与最终提交
  // 仍走原有校验，因此自由切页不会绕过人物卡完整性检查。
  const handleStepTabChange = (nextStep: number) => {
    setValidationAttempted(false)
    setSubmitError('')
    setStep(nextStep)
    characterPageRef.current?.parentElement?.scrollTo?.({ top: 0, behavior: 'smooth' })
  }

  const getBlockingIssues = (targetStep: number) => {
    const issues: string[] = []
    if (!info.name.trim()) issues.push('角色姓名不能为空')
    if (info.occupationId == null) issues.push('请选择职业')
    if (targetStep >= 3 && selectedOcc && !occupationChoicesComplete) {
      const missingSlot = (selectedOcc.choiceSlots ?? []).find(
        (slot, index) => (occupationChoiceSelections[index]?.length ?? 0) < slot.count
      )
      issues.push(missingSlot ? `请完成职业自选技能：${missingSlot.label}` : '请完成职业自选技能')
    }
    if (targetStep >= 4 && serializedBackground.length > CHARACTER_BACKGROUND_MAX_LENGTH) {
      issues.push(`背景故事不能超过 ${CHARACTER_BACKGROUND_MAX_LENGTH} 个字符`)
    }
    const needsReadyPreview = targetStep >= 1 && info.name.trim() && info.occupationId != null
    if (needsReadyPreview) {
      if (previewStatus === 'pending') {
        issues.push('规则预览尚未准备好，请稍后')
      } else if (previewStatus === 'error') {
        issues.push(previewError || '规则预览失败，请重试')
      } else if (previewStatus !== 'ready') {
        issues.push('规则预览尚未准备好，请稍后')
      } else {
        issues.push(...previewValidationIssues
          .filter(issue => issue.code !== 'OCCUPATION_CHOICES_INCOMPLETE')
          .map(issue => issue.message))
      }
    }
    return issues
  }

  const handlePrimaryAction = () => {
    const targetStep = step < 3 ? step + 1 : 4
    const issues = getBlockingIssues(targetStep)
    if (issues.length > 0) {
      setValidationAttempted(true)
      return
    }
    setValidationAttempted(false)
    setSubmitError('')
    if (step < 3) {
      setStep(s => s + 1)
      return
    }
    void handleSubmit()
  }

  const handleOpenLibrary = async () => {
    setLibraryOpen(true)
    setLibraryError('')
    // 每次打开都重新拉：玩家可能刚点过"存入卡库"，缓存住的话新卡不会出现在
    // 这个面板里，看起来就像刚才那次保存没生效。
    setLibraryCards(null)
    try {
      setLibraryCards(await listCharacterTemplates())
    } catch (err) {
      setLibraryError(friendlyErrorMessage(err, '加载角色卡库失败'))
    }
  }

  // 用卡库的卡开这一局。后端在已有草稿时会 409（不静默忽略玩家改了一半的
  // 草稿），这里把它翻成人话而不是抛一个通用错误。
  const handleUseLibraryCard = async (templateId: string) => {
    if (!roomId || libraryBusy) return
    setLibraryBusy(true)
    setLibraryError('')
    try {
      const characterId = await createCharacterDraft(roomId, templateId)
      setCharacterId(characterId)
      setLibraryOpen(false)
      // 卡库卡通常已经是捏好的，没道理再让玩家把四步向导点一遍。直接完成建卡进
      // 准备页——准备页本来就自己从后端拉角色卡，不需要这里再拼一份 store 数据。
      //
      // 完不成的情况是真实存在的（例如玩家刚在卡库里新建了一张空白卡就拿来用），
      // 后端会用 422 明确拒绝。那时候退回向导让玩家补完，而不是卡在一个说不清
      // 为什么失败的准备页。
      try {
        await completeCharacter(roomId, characterId)
        navigate('/room/ready')
      } catch {
        setLibraryError('这张卡还没建完，先在这里补完剩下的部分。')
        // 草稿已经带着卡库卡的数据落库了，重新进这个页面让既有的水合逻辑把它读
        // 回表单——不在这里再抄一遍字段映射。
        navigate(0)
      }
    } catch (err) {
      setLibraryError(
        err instanceof ApiError && err.status === 409
          ? '本房间已经有一张角色卡草稿了。想换成卡库里的卡，请先处理掉当前草稿。'
          : friendlyErrorMessage(err, '套用角色卡失败'),
      )
    } finally {
      setLibraryBusy(false)
    }
  }

  const handleSubmit = async () => {
    if (!isTemplateHost && !roomId) {
      setSubmitError('房间信息丢失，请重新创建/加入房间')
      return
    }
    if (!ruleset) return
    const issues = getBlockingIssues(4)
    if (issues.length > 0) {
      setValidationAttempted(true)
      return
    }
    setSubmitting(true)
    setValidationAttempted(false)
    setSubmitError('')
    try {
      // 最终提交前再拉一次权威计算：用当前 base（来自 skillComputeMap）把
      // 已分配点数换算成"最终值"，连同属性/职业一起发给后端拿回完整的
      // skillView（79 项技能的最终值）和衍生值，两边都以这次结果为准落库。
      const { preview: finalPreview, skillValues: skillsPayload } =
        await previewWithAllocations(
          attr,
          info.occupationId,
          skillAlloc,
          occupationChoiceSkillIds,
          generationMethod,
        )
      const finalDerived = normalizeDerivedStats(finalPreview.derivedStats)
      const skillFinalValues = Object.fromEntries(
        finalPreview.skillView.map(v => [v.id, v.current])
      )

      const built: BuiltCharacter = {
        name: info.name,
        age: info.age ? Number(info.age) : null,
        gender: info.gender || null,
        residence: info.residence,
        birthplace: info.birthplace,
        attr,
        derived: { hp: finalDerived.hp, san: finalDerived.san, mp: finalDerived.mp },
        skillValues: skillsPayload,
        occupationChoiceSkillIds,
        equipment,
        occupationName: selectedOcc?.name ?? null,
        background: serializedBackground,
        notes,
      }

      if (templateHostId) {
        // 卡库卡没有 complete：它不属于任何一局，"完成"就是存下来。顶层 name
        // 也一起更新——卡库列表展示的是它，不是 data.name。
        await updateCharacterTemplate(templateHostId, {
          name: info.name.trim() || '未命名调查员',
          data: templateDataFromBuilt(built),
        })
        navigate('/home/characters')
        return
      }

      const activeRoomId = roomId as string
      // 已经有草稿就复用，不要每次提交都新建一条。原来无条件 createCharacterDraft，
      // 「编辑已有角色 → 再次完成创建」会在 characters 表里再插一行，上一条就成了
      // 孤儿记录（改几次就攒几条），而房间里真正生效的只有最后那条。
      let characterId = useRoomStore.getState().characterId
      if (!characterId) {
        characterId = await createCharacterDraft(activeRoomId)
        // Persist the draft identity before PATCH/complete. If either later
        // request fails, the next submission resumes this same server draft.
        setCharacterId(characterId)
      }
      await saveCharacter(activeRoomId, characterId, built)
      await completeCharacter(activeRoomId, characterId)
      useCharacterStore.getState().setCharacter(
        {
          info: { ...info, playerName: info.playerName || info.name },
          generationMethod,
          attr: { ...attr },
          skillAlloc: { ...skillAlloc },
          skillFinalValues,
          occupationChoiceSkillIds: [...occupationChoiceSkillIds],
          equipment, background: serializedBackground, notes,
          derived: finalDerived,
        },
        activeRoomId
      )
      navigate('/room/ready')
    } catch (err) {
      setSubmitError(translateCharacterValidationError(err))
    } finally {
      setSubmitting(false)
    }
  }

  const currentNavigationIssues = validationAttempted ? getBlockingIssues(step < 3 ? step + 1 : 4) : []
  const visiblePreviewIssues = previewValidationIssues.filter(
    issue => issue.code !== 'OCCUPATION_CHOICES_INCOMPLETE'
  )

  const handleLeaveCharacterPage = () => {
    if (isTemplateHost) {
      navigate('/home/characters')
      return
    }
    if (isEditingExistingCharacter) {
      navigate(-1)
      return
    }
    setConfirmExit(true)
  }

  const handleConfirmExit = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  const handlePreviousStep = () => {
    if (step > 0) {
      setStep(current => current - 1)
      return
    }
    handleLeaveCharacterPage()
  }

  const previewIssuesBanner = previewStatus === 'ready' && visiblePreviewIssues.length > 0 ? (
    <div className="mt-3 rounded-[6px] border border-[#e0a0a0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c04040]">
      <div className="font-semibold mb-1">当前人物卡有校验问题</div>
      <div className="space-y-0.5">
        {visiblePreviewIssues.map((issue) => (
          <div key={`${issue.field}-${issue.code}`}>{issue.message}</div>
        ))}
      </div>
    </div>
  ) : null

  return (
    <div ref={characterPageRef} className="character-create animate-screen-in min-h-screen bg-page">
      {confirmExit && (
        <div
          className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center px-8"
          onClick={() => setConfirmExit(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="character-exit-title"
            className="bg-card border border-border-light rounded-md p-5 w-full max-w-[300px]"
            onClick={(event) => event.stopPropagation()}
          >
            <p id="character-exit-title" className="text-sm text-text-body text-center mb-4">
              确定要退出游戏吗？房间会保留，之后可以从「我的游戏」继续。
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setConfirmExit(false)}
                className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium active:bg-border-light"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleConfirmExit}
                className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030]"
              >
                确认退出
              </button>
            </div>
          </section>
        </div>
      )}

      {rulesetLoading ? (
        <div className="flex flex-col items-center justify-center min-h-screen px-5 text-center">
          <p className="text-sm text-text-muted">正在加载规则数据…</p>
        </div>
      ) : rulesetError ? (
        <div className="flex flex-col items-center justify-center min-h-screen px-5 text-center gap-3">
          <p className="text-sm text-[#c04040]">{rulesetError}</p>
          <button onClick={handleLeaveCharacterPage}
            className="px-5 py-2.5 rounded-sm bg-card border border-border-light text-text-body text-sm font-semibold">
            返回
          </button>
        </div>
      ) : (
        <>
          <header className="character-create__header">
            <button
              type="button"
              aria-label={step > 0 ? '返回上一页' : '返回'}
              onClick={handlePreviousStep}
              className="character-create__back"
            >
              <img src="/assets/character/create/back.webp" alt="" aria-hidden="true" />
            </button>
            <img
              className="character-create__title"
              src="/assets/character/create/title.webp"
              alt="创建角色"
            />
            <OnboardingTrigger className="character-create__rules" />
          </header>

          <div
            className="character-create__tabs"
            role="tablist"
            aria-label="角色创建页面"
          >
            <span
              data-onboarding-target="character-progress"
              className="character-create__tabs-guide-target"
              aria-hidden="true"
            />
            {steps.map((page, index) => (
              <button
                key={page.key}
                type="button"
                role="tab"
                id={`character-tab-${page.key}`}
                aria-selected={step === index}
                aria-controls={`character-step-${page.key}`}
                className={`character-create__tab ${step === index ? 'is-active' : ''}`}
                onClick={() => handleStepTabChange(index)}
              >
                <span className="character-create__tab-label">{page.label}</span>
              </button>
            ))}
          </div>

          {/* ★ 提前告知"没有房间"这件事，不要等填完四步、点完成创建才在最后一刻报错。
              卡库宿主没有房间是正常的（#337 决策 A），这条警告只对房间建卡成立。 */}
          {!isTemplateHost && !roomId && (
            <div className="character-create__room-warning">
              当前未加入房间，创建的角色不会被保存。请先返回创建或加入一个房间。
            </div>
          )}

          <div className="character-create__book">

          {/* ═══════════════ Step 0: Info + Occupation ═══════════════ */}
          {step === 0 && (
            <div id="character-step-info" role="tabpanel" aria-labelledby="character-tab-info" className="character-create__page character-create__page--info px-5 pb-20 animate-screen-in">
              {/* 车卡界面与卡库的两条通路（#337）。只对房间宿主显示——卡库宿主
                  本身就在编辑卡库卡，"存进卡库"和"从卡库选"都没有意义。 */}
              {/* 只放"从卡库选卡"。存卡入口在 /room/ready——那才是卡建好的时刻，
                  而且手动「完成创建」和「一键生成」都落在那里；放在这一步的话，
                  一键生成会直接跳走，玩家再也见不到存卡按钮。 */}
              {!isTemplateHost && roomId && (
                <div className="mb-3">
                  <button
                    type="button"
                    onClick={handleOpenLibrary}
                    disabled={libraryBusy}
                    className="w-full px-3 py-2 rounded-sm text-xs font-semibold bg-card text-text-body border border-border-mid active:bg-panel active:scale-[0.97] transition-all disabled:opacity-60"
                  >
                    从卡库选卡
                  </button>
                </div>
              )}
              {libraryError && (
                <p className="mb-3 text-[11px] text-[#c04040] text-center">{libraryError}</p>
              )}
              {libraryOpen && (
                <div className="mb-3 rounded-sm border border-border-mid bg-card p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-text-primary">我的角色卡</span>
                    <button
                      type="button"
                      onClick={() => setLibraryOpen(false)}
                      className="text-[11px] text-text-muted"
                    >
                      收起
                    </button>
                  </div>
                  {libraryCards === null && <p className="text-[11px] text-text-dim">加载中…</p>}
                  {libraryCards !== null && libraryCards.length === 0 && (
                    <p className="text-[11px] text-text-dim">卡库里还没有角色卡。</p>
                  )}
                  {libraryCards?.map((card) => (
                    <button
                      key={card.templateId}
                      type="button"
                      onClick={() => handleUseLibraryCard(card.templateId)}
                      disabled={libraryBusy}
                      className="w-full text-left px-3 py-2 rounded-sm border border-border-light active:bg-panel active:scale-[0.99] transition-all disabled:opacity-60"
                    >
                      <span className="text-xs font-semibold text-text-primary">{card.name}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="character-create__quick-wrap mb-3">
                <button
                  type="button"
                  aria-label="一键生成调查员"
                  onClick={handleQuickGenerate}
                  disabled={quickGenerating || (!isTemplateHost && !roomId)}
                  className="character-create__quick flex flex-col items-center justify-center text-sm font-semibold transition-all disabled:opacity-60"
                >
                  {quickGenerating ? (
                    <span>正在生成…</span>
                  ) : (
                    <><span>一键创建</span><span>角色</span></>
                  )}
                </button>
              </div>
              {/* Basic Info */}
              <div data-onboarding-target="character-info" className="character-create__section character-create__info bg-card border border-border-light rounded-md p-[18px] mb-3">
                <h4 className="character-create__section-title">调查员档案</h4>
                <div className="space-y-2">
                  <div className="character-create__name-field">
                    <label className="character-create__field-label" htmlFor="character-name">角色姓名：</label>
                    <input value={info.name} onChange={e => setInfo(i => ({ ...i, name: e.target.value }))}
                      id="character-name"
                      autoComplete="off"
                      placeholder="请输入角色姓名"
                      className={`w-full px-3.5 py-2.5 rounded-[6px] bg-input text-text-primary text-[15px] outline-none focus:border-brass border ${
                        validationAttempted && !info.name.trim() ? 'border-[#c04040]' : 'border-border-light'
                      }`} />
                  </div>
                  {validationAttempted && !info.name.trim() && (
                    <p className="mt-1 text-[11px] text-[#c04040]">角色姓名不能为空</p>
                  )}
                  <div className="grid grid-cols-2 gap-2.5">
                    <div className="character-create__inline-field">
                      <label className="text-[11px] font-medium text-text-muted">年龄：</label>
                      <div className="character-create__age-control">
                        <input type="number" min={ruleset?.ageRange?.minValue} max={ruleset?.ageRange?.maxValue} value={info.age}
                          onChange={e => setInfo(i => ({ ...i, age: e.target.value }))}
                          onBlur={e => {
                            // 夹值范围必须跟上面 input 的 min/max 用同一个数据源。
                            const range = ruleset?.ageRange
                            if (!range) return
                            const typed = parseInt(e.target.value, 10)
                            const v = Number.isNaN(typed)
                              ? range.minValue
                              : Math.max(range.minValue, Math.min(range.maxValue, typed))
                            setInfo(i => ({ ...i, age: String(v) }))
                          }}
                          className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                        <div className="character-create__age-steppers" aria-label="调整年龄">
                          <button type="button" onClick={() => adjustAge(1)} aria-label="年龄增加一岁">
                            <ChevronUp aria-hidden="true" />
                          </button>
                          <button type="button" onClick={() => adjustAge(-1)} aria-label="年龄减少一岁">
                            <ChevronDown aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="character-create__inline-field">
                      <label className="text-[11px] font-medium text-text-muted">性别：</label>
                      <div className="character-create__gender-picker">
                        <button
                          type="button"
                          role="combobox"
                          aria-label="性别"
                          aria-controls="character-gender-options"
                          aria-expanded={showGenderPicker}
                          onClick={() => setShowGenderPicker(open => !open)}
                          className="character-create__gender-trigger"
                        >
                          <span>{info.gender || '请选择'}</span>
                          <ChevronDown aria-hidden="true" />
                        </button>
                        {showGenderPicker && (
                          <>
                            <button
                              type="button"
                              aria-label="关闭性别选择"
                              className="fixed inset-0 z-10 cursor-default bg-transparent"
                              onClick={() => setShowGenderPicker(false)}
                            />
                            <div
                              id="character-gender-options"
                              role="listbox"
                              aria-label="选择性别"
                              className="character-create__gender-options"
                            >
                              {['男', '女', '其他'].map(gender => (
                                <button
                                  key={gender}
                                  type="button"
                                  role="option"
                                  aria-selected={info.gender === gender}
                                  onClick={() => {
                                    setInfo(current => ({ ...current, gender }))
                                    setShowGenderPicker(false)
                                  }}
                                >
                                  {gender}
                                </button>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
                    <div className="character-create__location-field">
                      <label className="character-create__location-label text-text-muted mb-1 block">居住地</label>
                      <input value={info.residence} onChange={e => setInfo(i => ({ ...i, residence: e.target.value }))}
                        placeholder="请选择居住地"
                        className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                    </div>
                    <div className="character-create__location-field">
                      <label className="character-create__location-label text-text-muted mb-1 block">出生地</label>
                      <input value={info.birthplace} onChange={e => setInfo(i => ({ ...i, birthplace: e.target.value }))}
                        placeholder="请选择出生地"
                        className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass" />
                    </div>
                  </div>
                </div>
              </div>

              {/* Occupation */}
              <div data-onboarding-target="occupation-picker" className="character-create__section character-create__occupation bg-card border border-border-light rounded-md p-[18px]">
                <h4 className="character-create__section-title">选择职业</h4>

                {/* Search + Group filter */}
                <div className="grid grid-cols-2 gap-2.5 mb-3">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
                    <input value={search} onChange={e => setSearch(e.target.value)}
                      placeholder="搜索职业…" className="w-full pl-8 pr-3 py-2 text-[12px] rounded-[6px] bg-input border border-border-light outline-none focus:border-brass text-text-primary" />
                  </div>
                  <div className="character-create__category-field relative">
                    <button onClick={() => setShowGroupPicker(!showGroupPicker)}
                      className="character-create__category-trigger w-full justify-between px-3 py-2 text-[12px] rounded-[6px] bg-input border border-border-light text-text-muted flex items-center gap-1 active:bg-panel">
                      {activeGroup || '全部分类'} <ChevronDown className="w-3 h-3" />
                    </button>
                    {showGroupPicker && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setShowGroupPicker(false)} />
                        <div className="character-create__category-options absolute right-0 top-full mt-1 z-20 bg-card border border-border-light rounded-md shadow-lg overflow-hidden">
                          <button onClick={() => { setActiveGroup(null); setShowGroupPicker(false) }}
                            className="w-full text-left px-3.5 py-2 text-[12px] text-text-primary hover:bg-panel">
                            全部分类
                          </button>
                          {occupationCategories.map(g => (
                            <button key={g.label} onClick={() => { setActiveGroup(g.label); setShowGroupPicker(false) }}
                              className="w-full text-left px-3.5 py-2 text-[12px] text-text-primary hover:bg-panel">
                              {g.label}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {selectedOcc && (
                  <div className="character-create__selected-occupation mb-3.5 px-3 py-3 border border-brass rounded-[6px]">
                    <div className="flex items-start gap-2.5">
                      <span className="character-create__occupation-icon text-2xl leading-none">{occupationIcon(selectedOcc)}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-semibold text-text-primary">{selectedOcc.name}</div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            <button onClick={() => setDetailOcc(selectedOcc)}
                              aria-label="详情"
                              title="查看职业详情"
                              className="character-create__occupation-detail-button rounded-full border border-border-light bg-[rgba(255,255,255,0.55)] text-brass-dark hover:text-text-body transition-all">
                              <Info aria-hidden="true" className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => selectOccupation(null)}
                              className="character-create__cancel-occupation text-[11px] underline">
                              取消选择
                            </button>
                          </div>
                        </div>
                        <div className="character-create__selected-occupation-meta mt-1 text-[11px]">
                          信用 <span className="character-create__number">{selectedOcc.creditMin}-{selectedOcc.creditMax}</span>
                          {' · '}
                          <span className="character-create__number">{selectedOcc.skillPointsFormula}</span>
                          {selectedOcc.categories?.length ? ` · ${selectedOcc.categories.join(' / ')}` : ''}
                        </div>
                        <div className="character-create__selected-skills mt-2">
                          {selectedOccupationSkillPreview.slice(0, 8).map((label, index) => (
                            <span key={`${label}-${index}`} className={`character-create__selected-skill px-2 py-1 bg-card border border-border-light text-[10px] text-text-body ${
                              Array.from(label).length > 8 ? 'is-wide' : ''
                            }`}>
                              {label}
                            </span>
                          ))}
                          {selectedOccupationSkillPreview.length > 8 && (
                            <span className="character-create__number px-2 py-1 text-[10px] text-text-dim">
                              +{selectedOccupationSkillPreview.length - 8} 项
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Occupation grid */}
                <div className="character-create__occupation-list grid grid-cols-2 gap-2 pr-0.5">
                  {filteredOccupations.map(occ => {
                    const selected = info.occupationId === occ.id
                    return (
                      <div key={occ.id}
                        className={`group relative min-h-[82px] px-2.5 py-3 bg-input border rounded-[6px] text-center cursor-pointer active:scale-[0.96] transition-all ${
                          selected ? 'is-selected' : 'border-border-light'
                        }`}>
                        <button
                          onClick={(e) => { e.stopPropagation(); setDetailOcc(occ); }}
                          aria-label={`查看${occ.name}详细内容`}
                          title="查看职业详情"
                          className="character-create__occupation-detail-button absolute top-1.5 right-1.5 z-[1] rounded-[4px] bg-[rgba(255,255,255,0.55)] border border-border-light px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-body transition-all"
                        >
                          <Info aria-hidden="true" className="h-3.5 w-3.5" />
                        </button>
                        <div onClick={() => selectOccupation(occ.id)} className="h-full flex flex-col items-center justify-center">
                          <div className="character-create__occupation-icon text-[20px] mb-1">{occupationIcon(occ)}</div>
                          <div className="text-[12px] font-semibold text-text-primary leading-[1.3]">{occ.name}</div>
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
                {validationAttempted && info.occupationId == null && (
                  <p className="mt-2 text-[11px] text-[#c04040]">请选择职业后再继续</p>
                )}
              </div>
            </div>
          )}

          {/* ═══════════════ Step 1: Attributes ═══════════════ */}
          {step === 1 && (
            <div id="character-step-attr" role="tabpanel" aria-labelledby="character-tab-attr" className="character-create__page character-create__page--attributes px-5 pb-20 animate-screen-in">
              <div className="character-create__attribute-panel">
                <h4 className="character-create__section-title character-create__attribute-title">属性分配</h4>
                <p className="character-create__attribute-description mb-2">
                  点击 +/- 调整属性值（范围 <span className="character-create__number">{pointBuyRules?.minValue ?? '—'}-{pointBuyRules?.maxValue ?? '—'}</span>，每次 <span className="character-create__number">±5</span>）
                </p>
                {generationMethod === 'roll' ? (
                  <div className="bg-[#fdf3e0] border border-[#e0c088] rounded-md px-3.5 py-2 mb-3 text-[11px] text-[#8a6a2a]">
                    这些属性由 COC7 标准骰法生成，不占用属性点。手动调整后会切换为点数购买法，并按预算校验。
                  </div>
                ) : (
                  <div className="bg-panel rounded-md px-3.5 py-2 mb-2 flex items-center gap-3">
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <span className="character-create__attribute-total-label text-[11px] font-medium">总点数</span>
                        <span className="character-create__attribute-total-value text-[12px] font-bold font-mono">{attrPointsTotal}<span className="font-normal">/{pointBuyRules?.budget ?? '—'}</span></span>
                      </div>
                      <div className="h-1.5 rounded-full bg-border-light overflow-hidden">
                        <div className="h-full rounded-full bg-brass transition-all duration-300" style={{ width: `${pointBuyRules ? Math.min(100, (attrPointsTotal / pointBuyRules.budget) * 100) : 0}%` }} />
                      </div>
                    </div>
                    <span className="character-create__attribute-remaining text-[10px]">（剩余点数：<span className="character-create__number">{pointBuyRules ? pointBuyRules.budget - attrPointsTotal : 0}</span>）</span>
                  </div>
                )}
                <div className="grid grid-cols-1 gap-0">
                  {pointBuyAttributes.map(attribute => {
                    const key = attribute.key
                    const Icon = ATTR_ICONS[key] || Shield
                    const color = ATTR_COLORS[key] || '#b8976a'
                    const val = attr[key] ?? 0
                    const helpOpen = attributeHelpKey === key
                    return (
                      <div
                        key={key}
                        data-onboarding-target={key === pointBuyAttributes[0]?.key ? 'attribute-example-row' : undefined}
                        className="character-create__attribute-row px-3 py-2.5 bg-input border border-border-light rounded-[6px]"
                      >
                        <div className="character-create__attribute-row-main flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                            <Icon className="w-4 h-4" style={{ color }} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] font-semibold text-text-primary flex items-center gap-1.5">
                              {attribute.label}
                              <span className="character-create__attribute-key text-[10px] font-mono font-normal">{key}</span>
                              <button
                                type="button"
                                onClick={() => setAttributeHelpKey(helpOpen ? null : key)}
                                aria-label={`了解${attribute.label}`}
                                aria-expanded={helpOpen}
                                aria-controls={`attribute-help-${key}`}
                                title={`了解${attribute.label}`}
                                className="w-4.5 h-4.5 rounded-full border border-border-mid text-text-muted flex items-center justify-center active:bg-panel transition-colors"
                              >
                                <Info className="w-2.5 h-2.5" strokeWidth={2.5} />
                              </button>
                            </div>
                            <div className="w-full h-1.5 rounded-full bg-border-light mt-1 overflow-hidden">
                              <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, val)}%`, backgroundColor: color }} />
                            </div>
                          </div>
                          <button onClick={() => handleAttrChange(key, -5)}
                            aria-label={`减少${attribute.label}`}
                            className="w-7 h-7 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all"
                          >
                            <Minus className="w-3.5 h-3.5" />
                          </button>
                          <input
                            type="number"
                            inputMode="numeric"
                            aria-label={`${attribute.label}数值`}
                            min={pointBuyRules?.minValue}
                            max={pointBuyRules?.maxValue}
                            value={attrInputs[key]}
                            onChange={e => setAttrInputs(inputs => ({ ...inputs, [key]: e.target.value }))}
                            onBlur={() => commitAttrInput(key)}
                            className="character-create__attribute-value text-[17px] font-bold font-mono text-text-primary min-w-[36px] w-[36px] text-center bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                          />
                          <button onClick={() => handleAttrChange(key, 5)}
                            aria-label={`增加${attribute.label}`}
                            className="w-7 h-7 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all"
                          >
                            <Plus className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {helpOpen && (
                          <p id={`attribute-help-${key}`} className="mt-2 border-t border-border-light pt-2 text-[11px] leading-relaxed text-text-muted">
                            {ATTRIBUTE_HELP[key] ?? `${attribute.label}是当前规则系统定义的基础属性。`}
                          </p>
                        )}
                      </div>
                    )
                  })}
                </div>

                {/* 不参与点数购买的属性（COC7 里就是幸运：只能掷、不能用属性点买）。
                    同样由 ruleset 驱动，不写死是哪一项——换个规则系统这里自然跟着变。 */}
                {(ruleset?.attributes ?? []).filter(a => !a.pointBuy).map(attribute => {
                  const helpOpen = attributeHelpKey === attribute.key
                  return (
                    <div key={attribute.key} className="character-create__attribute-row character-create__attribute-row--standalone px-3 py-2.5 bg-panel rounded-md">
                      <div className="character-create__attribute-row-main flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: '#4a8a4a18' }}>
                          <Clover className="w-4 h-4" style={{ color: '#4a8a4a' }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-semibold text-text-primary flex items-center gap-1.5">
                            {attribute.label}
                            <span className="character-create__attribute-key text-[10px] font-mono font-normal">{attribute.key}</span>
                            <button
                              type="button"
                              onClick={() => setAttributeHelpKey(helpOpen ? null : attribute.key)}
                              aria-label={`了解${attribute.label}`}
                              aria-expanded={helpOpen}
                              aria-controls={`attribute-help-${attribute.key}`}
                              title={`了解${attribute.label}`}
                              className="w-4.5 h-4.5 rounded-full border border-border-mid text-text-muted flex items-center justify-center active:bg-input transition-colors"
                            >
                              <Info className="w-2.5 h-2.5" strokeWidth={2.5} />
                            </button>
                          </div>
                          <div className="character-create__attribute-note text-[10px] mt-0.5">不占属性点数（规则为独立掷 <span className="character-create__number">{attribute.generation}</span>，由当前生成方式决定）</div>
                        </div>
                        <span className="character-create__attribute-static-value character-create__attribute-static-value--plain text-[17px] font-bold font-mono text-text-primary min-w-[36px] text-center">{attr[attribute.key] ?? '—'}</span>
                      </div>
                      {helpOpen && (
                        <p id={`attribute-help-${attribute.key}`} className="mt-2 border-t border-border-light pt-2 text-[11px] leading-relaxed text-text-muted">
                          {ATTRIBUTE_HELP[attribute.key] ?? `${attribute.label}是当前规则系统定义的基础属性。`}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Derived Stats */}
              <div className="character-create__derived mt-3">
                <h4 className="character-create__derived-title font-semibold text-brass-dark tracking-[0.08em] mb-3">衍生属性</h4>
                {previewError && <p className="text-[11px] text-[#c04040] mb-2">{previewError}</p>}
                <div className="grid grid-cols-3 gap-2" data-testid="derived-stats-grid">
                  {DERIVED_STAT_DEFINITIONS.map(definition => (
                    <div key={definition.key} className="bg-panel rounded-md px-2.5 py-2 text-center">
                      <div className="text-[10px] text-text-muted font-semibold">
                        {definition.label} <span className="font-mono text-text-dim">{definition.abbreviation}</span>
                      </div>
                      <div className="text-[16px] font-bold font-mono" style={{ color: definition.color }}>
                        {derived[definition.key]}
                      </div>
                    </div>
                  ))}
                </div>
                {previewIssuesBanner}
              </div>
            </div>
          )}

          {/* ═══════════════ Step 2: Skills ═══════════════ */}
          {step === 2 && (
            <div id="character-step-skill" role="tabpanel" aria-labelledby="character-tab-skill" className="character-create__page character-create__page--skills px-5 pb-20 animate-screen-in">
              <h4 className="character-create__section-title character-create__skill-title">技能点分配</h4>
              {/* Point counters */}
              <div data-onboarding-target="skill-editor" className="flex gap-2.5 mb-3">
                <div className="flex-1 bg-panel rounded-md p-3">
                  <div className="character-create__skill-counter-title text-text-muted font-semibold mb-1">
                    职业技能
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                      <div className="character-create__skill-progress h-full rounded-full transition-all" style={{ width: `${Math.min(100, occPointsTotal ? (occPointsSpent / occPointsTotal) * 100 : 0)}%` }} />
                    </div>
                    <span className="character-create__skill-number text-xs font-bold text-text-primary">{occPointsSpent}/{occPointsTotal}</span>
                  </div>
                </div>
                <div className="flex-1 bg-panel rounded-md p-3">
                  <div className="character-create__skill-counter-title text-text-muted font-semibold mb-1">兴趣技能</div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                      <div className="character-create__skill-progress h-full rounded-full transition-all" style={{ width: `${Math.min(100, interestPointsTotal ? (interestPointsSpent / interestPointsTotal) * 100 : 0)}%` }} />
                    </div>
                    <span className="character-create__skill-number text-xs font-bold text-text-primary">{interestPointsSpent}/{interestPointsTotal}</span>
                  </div>
                </div>
              </div>
              {previewIssuesBanner}

              {/* Credit Rating — 后端必填技能，值须落在所选职业信用区间内。 */}
              {selectedOcc && (
                <div
                  data-onboarding-target="credit-rating-editor"
                  className="character-create__credit-rating rounded-md p-3.5 my-3"
                >
                  <div className="flex items-center justify-between mb-1">
                    <h4 className="character-create__credit-title font-semibold text-brass-dark">
                      信用评级 · <span className="text-[#c04040]">必填</span>
                    </h4>
                    <span className="character-create__credit-range text-text-muted font-mono">
                      范围 {selectedOcc.creditMin}–{selectedOcc.creditMax}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2">
                    <button onClick={() => handleCreditChange(-1)}
                      aria-label="减少信用评级"
                      disabled={(creditRating ?? selectedOcc.creditMin) <= selectedOcc.creditMin}
                      className="w-8 h-8 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all disabled:opacity-40 disabled:active:scale-100"
                    >
                      <Minus className="w-4 h-4" />
                    </button>
                    <input
                      aria-label="信用评级"
                      type="number"
                      inputMode="numeric"
                      value={creditInput}
                      onChange={e => setCreditInput(e.target.value)}
                      onBlur={commitCreditInput}
                      className="flex-1 min-w-0 text-center text-[20px] font-bold font-mono text-text-primary bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    />
                    <button onClick={() => handleCreditChange(1)}
                      aria-label="增加信用评级"
                      disabled={(creditRating ?? selectedOcc.creditMin) >= selectedOcc.creditMax}
                      className="w-8 h-8 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center active:bg-panel active:scale-90 transition-all disabled:opacity-40 disabled:active:scale-100"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}

              {selectedOcc && (selectedOcc.choiceSlots?.length ?? 0) > 0 && (
                <div className="character-create__occupation-choice bg-card border border-border-light rounded-md p-3.5 my-3" data-testid="occupation-choice-panel">
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <h4 className="character-create__occupation-choice-title font-semibold text-brass-dark">职业自选技能</h4>
                      <p className="character-create__occupation-choice-description text-text-muted mt-0.5">选中的技能将使用职业技能点</p>
                    </div>
                    <span className={`character-create__occupation-choice-count font-mono font-semibold ${
                      occupationChoicesComplete ? 'text-mold' : 'text-[#c08050]'
                    }`}>
                      {occupationChoiceSkillIds.length}/
                      {(selectedOcc.choiceSlots ?? []).reduce((sum, slot) => sum + slot.count, 0)}
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {(selectedOcc.choiceSlots ?? []).map((slot, slotIndex) => {
                      const selectedIds = occupationChoiceSelections[slotIndex] ?? []
                      return (
                        <div key={`${slot.label}-${slotIndex}`} className="rounded-[6px] bg-input border border-border-light p-3">
                          <div className="flex items-center justify-between gap-2 mb-2">
                            <div className="text-[12px] font-medium text-text-primary">{slot.label}</div>
                            <span className="text-[10px] font-mono text-text-muted">{selectedIds.length}/{slot.count}</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedIds.map(skillId => (
                              <button
                                key={skillId}
                                type="button"
                                onClick={() => removeOccupationChoice(slotIndex, skillId)}
                                className="flex items-center gap-1 px-2 py-1 rounded-[4px] bg-card border border-brass text-[11px] text-text-body"
                                aria-label={`取消职业自选技能 ${occupationSkillLabel(skillId, ruleset?.skills ?? [])}`}
                              >
                                {occupationSkillLabel(skillId, ruleset?.skills ?? [])}
                                <X className="w-3 h-3" />
                              </button>
                            ))}
                            {selectedIds.length < slot.count && (
                              <button
                                type="button"
                                onClick={() => {
                                  setChoicePickerSlotIndex(slotIndex)
                                  setChoiceSkillSearch('')
                                  setChoiceActionError('')
                                }}
                                className="flex items-center gap-1 px-2 py-1 rounded-[4px] border border-dashed border-brass text-[11px] text-brass-dark"
                              >
                                <Plus className="w-3 h-3" /> 选择技能
                              </button>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {choiceActionError && (
                    <p className="mt-2 text-[11px] text-[#c04040]">{choiceActionError}</p>
                  )}
                  {validationAttempted && !occupationChoicesComplete && (
                    <p className="mt-2 text-[11px] text-[#c04040]">请填满全部职业自选技能槽位</p>
                  )}
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
                    // 职业技能优先吃职业池，超出部分由兴趣池承担。
                    const totalAllocation = skillAlloc[skill.id] || 0
                    const compute = skillComputeMap.get(skill.id)
                    const base = compute?.base ?? (typeof skill.base === 'number' ? skill.base : 0)
                    const cap = compute?.cap ?? null
                    return (
                      <SkillRow key={skill.id} skill={skill} base={base} cap={cap}
                        poolAllocation={totalAllocation}
                        onChange={(d) => handleOccSkillChange(skill.id, d)}
                        onSetAllocation={(v) => handleOccSkillSet(skill.id, v)}
                        maxPoints={totalAllocation + combinedPointsRemaining}
                        minPoints={0}
                      />
                    )
                  })
                ) : (
                  // 兴趣页只列非职业技能；它们只能使用兴趣预算，不会占用职业点。
                  interestSkills.map(skill => {
                    const interestAllocation = interestAlloc[skill.id] || 0
                    const compute = skillComputeMap.get(skill.id)
                    const base = compute?.base ?? (typeof skill.base === 'number' ? skill.base : 0)
                    const cap = compute?.cap ?? null
                    return (
                      <SkillRow key={skill.id} skill={skill} base={base} cap={cap}
                        poolAllocation={interestAllocation}
                        onChange={(d) => handleInterestSkillChange(skill.id, d)}
                        onSetAllocation={(v) => handleInterestSkillSet(skill.id, v)}
                        maxPoints={interestAllocation + interestPointsRemaining}
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
            <div id="character-step-background" role="tabpanel" aria-labelledby="character-tab-background" data-onboarding-target="background-editor" className="character-create__page px-5 pb-20 animate-screen-in">
              {/* Equipment */}
              <div className="character-create__equipment-section mb-3">
                <h4 className="character-create__background-title font-semibold text-brass-dark tracking-[0.08em] mb-3">装备与物品</h4>
                <textarea value={equipment} onChange={e => setEquipment(e.target.value)}
                  placeholder="手电筒、笔记本、相机、急救包…" rows={3}
                  className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-none" />
              </div>

              {/* Background */}
              <div className="character-create__background-section mb-3">
                <div className="character-create__background-heading-row flex items-start justify-between gap-3 mb-1.5">
                  <h4 className="character-create__background-title font-semibold text-brass-dark tracking-[0.08em]">背景故事</h4>
                  <span className={`text-[11px] font-mono ${
                    serializedBackground.length > CHARACTER_BACKGROUND_MAX_LENGTH
                      ? 'text-[#c04040] font-semibold'
                      : 'text-text-muted'
                  }`}>
                    {serializedBackground.length}/{CHARACTER_BACKGROUND_MAX_LENGTH}
                  </span>
                </div>
                <p className="character-create__background-description text-[11px] leading-relaxed mb-3">
                  分项填写调查员的经历，所有内容均为选填。
                </p>
                <div className="space-y-2.5">
                  {BACKGROUND_SECTION_DEFINITIONS.map(section => {
                    const value = backgroundForm.sections[section.key]
                    return (
                      <div key={section.key} className="character-create__background-field">
                        <label htmlFor={`background-${section.key}`} className="block text-[13px] font-semibold text-text-primary mb-2">
                          {section.label}
                        </label>
                        <textarea
                          id={`background-${section.key}`}
                          aria-label={section.label}
                          value={value}
                          onChange={event => updateBackgroundSection(section.key, event.target.value)}
                          placeholder={BACKGROUND_PLACEHOLDERS[section.key]}
                          rows={2}
                          className="w-full px-3 py-2 rounded-[6px] bg-card border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-y"
                        />
                      </div>
                    )
                  })}

                  <div className="character-create__background-field">
                    <label htmlFor="background-other" className="block text-[13px] font-semibold text-text-primary mb-2">
                      其他
                    </label>
                    <textarea
                      id="background-other"
                      aria-label="其他"
                      value={backgroundForm.other}
                      onChange={event => setBackgroundForm(previous => ({ ...previous, other: event.target.value }))}
                      placeholder="未归类的背景补充；旧版背景故事也会显示在这里……"
                      rows={3}
                      className="w-full px-3 py-2 rounded-[6px] bg-card border border-border-light text-text-primary text-[14px] outline-none focus:border-brass resize-y"
                    />
                  </div>
                </div>
                {serializedBackground.length > CHARACTER_BACKGROUND_MAX_LENGTH && (
                  <p className="mt-2 text-[11px] text-[#c04040] font-medium">
                    背景故事不能超过 {CHARACTER_BACKGROUND_MAX_LENGTH} 个字符，请精简后再完成建卡。
                  </p>
                )}
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

          </div>

          {/* ═══════════════ Occupation Detail Modal ═══════════════ */}
          {detailOcc && (
            <>
              <div className="fixed inset-0 bg-black/50 z-30 animate-fade-in" onClick={() => setDetailOcc(null)} />
              <div className="fixed inset-x-0 bottom-0 z-40 animate-slide-up">
                <div className="character-create__occupation-detail bg-page border border-border-light rounded-t-xl px-5 pt-5 pb-8 max-h-[80vh] overflow-hidden">
                  <div className="character-create__occupation-detail-scroll">
                  <div className="character-create__occupation-detail-header flex items-start justify-between mb-5">
                    <div className="flex items-center gap-3">
                      <span className="character-create__occupation-icon text-[32px]">{occupationIcon(detailOcc)}</span>
                      <div>
                        <h3 className="text-[18px] font-bold text-text-primary">{detailOcc.name}</h3>
                        <p className="character-create__occupation-detail-description text-xs">{detailOcc.description}</p>
                      </div>
                    </div>
                    <button onClick={() => setDetailOcc(null)}
                      className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-text-muted active:bg-panel">
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="space-y-1.5">
                    <div className="character-create__occupation-detail-section bg-input border border-border-light rounded-[6px] p-3.5">
                      <div className="character-create__occupation-detail-section-title font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">基础信息</div>
                      <div className="grid grid-cols-2 gap-1.5 text-sm">
                        <div>
                          <span className="character-create__occupation-detail-meta-label block">信用范围</span>
                          <span className="character-create__occupation-detail-value character-create__number font-bold">{detailOcc.creditMin}-{detailOcc.creditMax}</span>
                        </div>
                        <div>
                          <span className="character-create__occupation-detail-meta-label block">技能点数</span>
                          <span className="character-create__occupation-detail-value font-bold font-mono">{detailOcc.skillPointsFormula}</span>
                        </div>
                      </div>
                    </div>

                    <div className="character-create__occupation-detail-section bg-input border border-border-light rounded-[6px] p-3.5">
                      <div className="character-create__occupation-detail-section-title font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">
                        职业技能 (<span className="character-create__number">{detailOcc.skillIds.length}</span>)
                      </div>
                      <div className="grid grid-cols-2 gap-1.5">
                        {detailOcc.skillIds.map(id => {
                          const skill = ruleset?.skills.find(s => s.id === id)
                          return (
                            <div key={id} className="character-create__occupation-detail-skill flex items-center gap-2 px-2.5 py-1.5 bg-card border border-border-light">
                              <div className="flex-1 min-w-0">
                                <div className="text-[12px] font-medium text-text-primary">{skill?.name || id}</div>
                              </div>
                              <div className="character-create__occupation-detail-percentage text-[10px] font-mono bg-panel px-1.5 py-0.5 rounded">
                                {skill && (typeof skill.base === 'number' ? skill.base + '%' : skill.base)}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => { selectOccupation(detailOcc.id); setDetailOcc(null) }}
                    className="mt-4 w-full flex items-center justify-center gap-2 py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all"
                  >
                    选择 {detailOcc.name}
                  </button>
                  </div>
                </div>
              </div>
            </>
          )}

          {showQuickGenerateConfirm && (
            <>
              <div
                className="fixed inset-0 bg-black/50 z-40 animate-fade-in"
                onClick={() => setShowQuickGenerateConfirm(false)}
              />
              <div className="fixed inset-x-5 top-1/2 z-50 mx-auto max-w-[390px] -translate-y-1/2 rounded-lg bg-page border border-border-light p-5 shadow-xl">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-full bg-[#fff2d8] flex items-center justify-center flex-shrink-0">
                    <Sparkles className="w-4 h-4 text-brass-dark" />
                  </div>
                  <div>
                    <h3 className="text-[16px] font-bold text-text-primary">覆盖当前草稿？</h3>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-text-muted">
                      一键生成会替换当前已填写的信息、属性、技能和背景，生成后仍可继续修改。这个操作不能恢复当前草稿。
                    </p>
                  </div>
                </div>
                <div className="flex gap-2.5 mt-5">
                  <button
                    type="button"
                    onClick={() => setShowQuickGenerateConfirm(false)}
                    className="flex-1 px-4 py-2.5 rounded-sm border border-border-mid bg-card text-sm font-semibold text-text-body"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={() => void runQuickGenerate()}
                    className="flex-1 px-4 py-2.5 rounded-sm bg-brass text-white text-sm font-semibold"
                  >
                    继续生成
                  </button>
                </div>
              </div>
            </>
          )}

          {quickGenerateError && (
            <>
              <div
                className="fixed inset-0 bg-black/50 z-40 animate-fade-in"
                onClick={() => setQuickGenerateError('')}
              />
              <div
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="quick-generate-error-title"
                className="fixed inset-x-5 top-1/2 z-50 mx-auto max-w-[360px] -translate-y-1/2 rounded-lg bg-page border border-border-light p-5 shadow-xl"
              >
                <h3 id="quick-generate-error-title" className="text-[16px] font-bold text-text-primary">
                  无法一键创建角色
                </h3>
                <p className="mt-2 text-[13px] leading-relaxed text-text-muted" role="alert">
                  {quickGenerateError}
                </p>
                <button
                  type="button"
                  autoFocus
                  onClick={() => setQuickGenerateError('')}
                  className="mt-5 w-full px-4 py-2.5 rounded-sm bg-brass text-white text-sm font-semibold"
                >
                  我知道了
                </button>
              </div>
            </>
          )}

          {activeChoiceSlot && choicePickerSlotIndex != null && (
            <>
              <div
                className="fixed inset-0 bg-black/50 z-40 animate-fade-in"
                onClick={() => setChoicePickerSlotIndex(null)}
              />
              <div className="character-create__choice-picker fixed inset-x-0 bottom-0 z-50 mx-auto max-w-[430px] px-5 pt-5 pb-8 max-h-[75vh] flex flex-col">
                <div className="character-create__choice-picker-header flex items-start justify-between gap-3 mb-3">
                  <div className="character-create__choice-picker-heading">
                    <h3 className="character-create__choice-picker-title font-bold text-text-primary">选择职业技能</h3>
                    <p className="character-create__choice-picker-description mt-0.5">{activeChoiceSlot.label}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setChoicePickerSlotIndex(null)}
                    className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-text-muted"
                    aria-label="关闭职业技能选择"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="relative mb-3">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
                  <input
                    value={choiceSkillSearch}
                    onChange={event => setChoiceSkillSearch(event.target.value)}
                    placeholder="搜索技能…"
                    aria-label="搜索职业自选技能"
                    className="character-create__choice-picker-search w-full pl-9 pr-3 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary outline-none focus:border-brass"
                  />
                </div>
                <div className="overflow-y-auto space-y-1.5">
                  {choiceCandidateSkills.map(skill => (
                    <button
                      key={skill.id}
                      type="button"
                      onClick={() => addOccupationChoice(choicePickerSlotIndex, skill.id)}
                      className="w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-[6px] bg-card border border-border-light text-left active:bg-panel"
                    >
                      <span className="min-w-0">
                        <span className="character-create__choice-skill-name block font-medium text-text-primary">{skill.name}</span>
                        <span className="character-create__choice-skill-subtitle block font-mono">{skill.nameEn}</span>
                      </span>
                      <Plus className="character-create__choice-skill-add w-4 h-4 flex-shrink-0" />
                    </button>
                  ))}
                  {choiceCandidateSkills.length === 0 && (
                    <p className="character-create__choice-picker-empty py-8 text-center">没有可选技能</p>
                  )}
                </div>
              </div>
            </>
          )}

          {/* ═══════════════ Bottom action bar ═══════════════ */}
          <div className="character-create__actions fixed bottom-0 left-0 right-0 px-5 py-3 max-w-[430px] mx-auto z-20">
            {(currentNavigationIssues[0] || (step === 3 ? submitError : '')) && (
              <p className="text-[11px] text-[#c04040] text-center mb-2">
                {currentNavigationIssues[0] || submitError}
              </p>
            )}
            <div className="flex gap-2.5">
              <button
                data-onboarding-page-back
                onClick={handlePreviousStep}
                className="character-create__action character-create__action--previous flex-1 flex items-center justify-center text-sm font-semibold transition-all active:scale-[0.97]">
                上一步
              </button>
              <button onClick={handlePrimaryAction}
                disabled={submitting}
                data-onboarding-target={step === 3 ? 'character-submit' : undefined}
                className="character-create__action character-create__action--next flex-1 flex items-center justify-center text-sm font-semibold transition-all active:scale-[0.97] disabled:opacity-60">
                {submitting ? '提交中…' : step === 3 ? '完成创建' : '下一步'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
