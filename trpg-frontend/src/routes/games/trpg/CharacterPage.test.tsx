import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Ruleset } from 'trpg-sdk'
import CharacterPage from './CharacterPage'
import { useRoomStore } from '@/stores/room-store'
import { useCharacterStore } from '@/stores/character-store'

const { mockRuleset, mockPreviewCharacter, mockCharacterApi } = vi.hoisted(() => {
  const mockRuleset: Ruleset = {
    attributes: [
      { key: 'STR', label: '力量', generation: '3d6*5', pointBuy: true },
      { key: 'CON', label: '体质', generation: '3d6*5', pointBuy: true },
      { key: 'POW', label: '意志', generation: '3d6*5', pointBuy: true },
      { key: 'DEX', label: '敏捷', generation: '3d6*5', pointBuy: true },
      { key: 'APP', label: '外貌', generation: '3d6*5', pointBuy: true },
      { key: 'SIZ', label: '体型', generation: '2d6+6*5', pointBuy: true },
      { key: 'INT', label: '智力', generation: '2d6+6*5', pointBuy: true },
      { key: 'EDU', label: '教育', generation: '2d6+6*5', pointBuy: true },
      { key: 'LUCK', label: '幸运', generation: '3d6*5', pointBuy: false },
    ],
    attributePointBuy: { budget: 480, minValue: 10, maxValue: 90, defaultValue: 50 },
    ageRange: { minValue: 15, maxValue: 89 },
    skills: [
      { id: 'accounting', name: '会计', nameEn: 'accounting', base: 0, category: 'occupation' },
      { id: 'stealth', name: '潜行', nameEn: 'stealth', base: 0, category: 'interest' },
      { id: 'charm', name: '取悦', nameEn: 'charm', base: 0, category: 'social' },
      { id: 'climb', name: '攀爬', nameEn: 'climb', base: 0, category: 'physical' },
      { id: 'cthulhu-mythos', name: '克苏鲁神话', nameEn: 'cthulhu mythos', base: 0, category: 'special' },
      { id: 'credit-rating', name: '信用评级', nameEn: 'credit-rating', base: 0, category: 'special' },
    ],
    occupationCategories: [
      { label: '法律金融', icon: '⚖️' },
      { label: '犯罪边缘', icon: '🕶️' },
    ],
    occupations: [
      {
        id: 1,
        name: '会计师',
        creditMin: 0,
        creditMax: 70,
        skillPointsFormula: 'EDU*4',
        skillIds: ['accounting'],
        description: '测试用职业',
        icon: '📊',
        categories: ['法律金融'],
      },
      {
        id: 2,
        name: '记者',
        creditMin: 0,
        creditMax: 70,
        skillPointsFormula: 'EDU*4',
        skillIds: ['accounting'],
        choiceSlots: [
          { count: 1, candidateSkillIds: ['charm'], label: '一项社交技能' },
          { count: 1, candidateSkillIds: null, label: '任意一项其他技能' },
        ],
        description: '带职业自选槽的测试职业',
        icon: '📰',
        categories: ['法律金融'],
      },
      {
        id: 31,
        name: '罪犯-欺诈师',
        creditMin: 10,
        creditMax: 65,
        skillPointsFormula: 'EDU*2+APP*2',
        skillIds: ['stealth'],
        description: 'id 大于旧图标表范围的测试职业',
        icon: '🕶️',
        categories: ['犯罪边缘'],
      },
    ],
  }

  const mockPreviewCharacter = vi.fn(async ({
    occupationId,
    skills,
    occupationChoiceSkillIds,
  }: {
    occupationId: number | null
    skills: Record<string, number>
    occupationChoiceSkillIds?: string[] | null
  }) => {
    const accounting = skills.accounting ?? 0
    const stealth = skills.stealth ?? 0
    const credit = skills['credit-rating'] ?? 0
    const creditMin = occupationId === 1 ? 0 : 0
    return {
      derivedStats: { HP: 10, SAN: 50, MP: 10, DB: '0', Build: '0', MOV: 8 },
      occupationSkillPoints: {
        budget: 2,
        spent: accounting + creditMin,
        remaining: 2 - accounting - creditMin,
      },
      interestSkillPoints: {
        budget: 2,
        spent: stealth + Math.max(0, credit - creditMin),
        remaining: 2 - stealth - Math.max(0, credit - creditMin),
      },
      skillView: mockRuleset.skills.map((skill) => ({
        id: skill.id,
        base: 0,
        allocated: skills[skill.id] ?? 0,
        current: skills[skill.id] ?? 0,
        cap: skill.id === 'credit-rating' ? 70 : 99,
      })),
      resolvedOccupationChoiceSkillIds: occupationChoiceSkillIds ?? [],
      validation: occupationId === 2 && (occupationChoiceSkillIds?.length ?? 0) < 2
        ? [{
            code: 'OCCUPATION_CHOICES_INCOMPLETE',
            field: 'occupationChoiceSkillIds',
            message: '职业自选技能需要选择 2 项',
          }]
        : [],
    }
  })

  const mockCharacterApi = {
    createCharacterDraft: vi.fn().mockResolvedValue('draft-1'),
    saveCharacter: vi.fn().mockResolvedValue(undefined),
    completeCharacter: vi.fn().mockResolvedValue(undefined),
    fetchCharacter: vi.fn().mockResolvedValue({ attributes: {}, skills: {} }),
  }

  return { mockRuleset, mockPreviewCharacter, mockCharacterApi }
})

vi.mock('@/hooks/useRuleset', () => ({
  useRuleset: () => ({ ruleset: mockRuleset, loading: false, error: '' }),
}))

vi.mock('@/services/character/ruleset-api', async () => {
  const actual = await vi.importActual<typeof import('@/services/character/ruleset-api')>('@/services/character/ruleset-api')
  return {
    ...actual,
    previewCharacter: mockPreviewCharacter,
  }
})

vi.mock('@/services/character/character-api', () => mockCharacterApi)

describe('CharacterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCharacterApi.createCharacterDraft.mockResolvedValue('draft-1')
    mockCharacterApi.saveCharacter.mockResolvedValue(undefined)
    mockCharacterApi.completeCharacter.mockResolvedValue(undefined)
    mockCharacterApi.fetchCharacter.mockResolvedValue({ attributes: {}, skills: {} })
    useRoomStore.getState().reset()
    useCharacterStore.getState().clear()
    useRoomStore.setState({
      roomId: 'room-1',
      roomCode: 'ROOM-1',
      playerId: 'player-1',
      reconnectToken: 'token-1',
      moduleId: 'module-1',
      characterId: null,
    })
  })

  afterEach(() => {
    cleanup()
  })

  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/room/character']}>
        <Routes>
          <Route path="/room/character" element={<CharacterPage />} />
        </Routes>
      </MemoryRouter>
    )
  }

  async function waitForPreviewWithSkill(skillId: string, value: number) {
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(
        expect.objectContaining({ skills: expect.objectContaining({ [skillId]: value }) })
      )
    })
  }

  async function advanceToAttributesAfterOccupationPreview() {
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(expect.objectContaining({ occupationId: 1 }))
    })
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
      expect(screen.getByText('属性分配')).toBeInTheDocument()
    })
  }

  async function advanceToBackgroundStep() {
    fireEvent.change(screen.getByPlaceholderText('角色姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('会计师'))
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    await advanceToAttributesAfterOccupationPreview()

    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(await screen.findByLabelText('信用评级')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(await screen.findByText('背景故事')).toBeInTheDocument()
  }

  async function advanceToReporterSkills() {
    fireEvent.change(screen.getByPlaceholderText('角色姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('记者'))
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(expect.objectContaining({ occupationId: 2 }))
    })
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
      expect(screen.getByText('属性分配')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(await screen.findByTestId('occupation-choice-panel')).toBeInTheDocument()
  }

  it('blocks advancing until name and occupation are filled', async () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(screen.getAllByText('角色姓名不能为空').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByPlaceholderText('角色姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(screen.getAllByText('请选择职业后再继续').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByText('会计师'))
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))

    await advanceToAttributesAfterOccupationPreview()
  })

  it('renders occupation icons and filters from backend ruleset metadata', () => {
    renderPage()

    expect(screen.getByText('📊')).toBeInTheDocument()
    expect(screen.getByText('🕶️')).toBeInTheDocument()
    expect(screen.queryByText('❔')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /全部分类/ }))
    fireEvent.click(screen.getByRole('button', { name: /犯罪边缘/ }))

    expect(screen.getByText('罪犯-欺诈师')).toBeInTheDocument()
    expect(screen.queryByText('会计师')).not.toBeInTheDocument()
  })

  it('shows occupation skills first and keeps descriptions in detail view', () => {
    renderPage()

    expect(screen.queryByText('测试用职业')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('会计师'))

    expect(screen.getByText('会计')).toBeInTheDocument()
    expect(screen.queryByText('测试用职业')).not.toBeInTheDocument()
    expect(screen.getByText(/信用 0-70/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '详情' }))

    expect(screen.getByText('测试用职业')).toBeInTheDocument()
  })

  it('renders all six derived stats in a three-column grid', async () => {
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('角色姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('会计师'))
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    await advanceToAttributesAfterOccupationPreview()

    const grid = screen.getByTestId('derived-stats-grid')
    expect(grid).toHaveClass('grid-cols-3')
    for (const label of ['生命值', '理智值', '魔法值', '伤害加值', '体格', '移动力']) {
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
    }
  })

  it('selects, submits, and caches explicit occupation choice skills', async () => {
    renderPage()
    await advanceToReporterSkills()

    fireEvent.click(screen.getAllByRole('button', { name: /选择技能/ })[0])
    fireEvent.click(screen.getByRole('button', { name: /取悦/ }))
    fireEvent.click(screen.getByRole('button', { name: /选择技能/ }))
    expect(screen.queryByText('克苏鲁神话')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /攀爬/ }))

    expect(screen.getByLabelText('取悦 技能点')).toBeInTheDocument()
    expect(screen.getByLabelText('攀爬 技能点')).toBeInTheDocument()
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(expect.objectContaining({
        occupationChoiceSkillIds: ['charm', 'climb'],
      }))
    })
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
      expect(screen.getByText('背景故事')).toBeInTheDocument()
    })
    expect(await screen.findByText('背景故事')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /完成创建/ }))

    await waitFor(() => {
      expect(mockCharacterApi.saveCharacter).toHaveBeenCalledWith(
        'room-1',
        'draft-1',
        expect.objectContaining({ occupationChoiceSkillIds: ['charm', 'climb'] }),
      )
    })
    expect(useCharacterStore.getState().getForRoom('room-1')?.occupationChoiceSkillIds)
      .toEqual(['charm', 'climb'])
  })

  it('hydrates legacy automatic choices from the preview result', async () => {
    const inferredPreview = await mockPreviewCharacter({
      occupationId: 2,
      skills: { charm: 40, climb: 30 },
      occupationChoiceSkillIds: ['charm', 'climb'],
    })
    mockPreviewCharacter.mockClear()
    mockPreviewCharacter.mockResolvedValueOnce({
      ...inferredPreview,
      resolvedOccupationChoiceSkillIds: ['charm', 'climb'],
      validation: [],
    })
    useRoomStore.setState({ characterId: 'legacy-character' })
    mockCharacterApi.fetchCharacter.mockResolvedValue({
      name: '旧卡调查员',
      age: 30,
      gender: '男',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupation: '记者',
      attributes: Object.fromEntries(mockRuleset.attributes.map(attribute => [attribute.key, 50])),
      derivedStats: { HP: 10, SAN: 50, MP: 10 },
      skills: { charm: 40, climb: 30 },
      occupationChoiceSkillIds: null,
      equipment: [],
      background: '',
      notes: '',
    })

    renderPage()
    await waitFor(() => expect(screen.getByPlaceholderText('角色姓名')).toHaveValue('旧卡调查员'))
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(expect.objectContaining({
        occupationId: 2,
        occupationChoiceSkillIds: null,
      }))
    })
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
      expect(screen.getByText('属性分配')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))

    expect(await screen.findByLabelText('取消职业自选技能 取悦')).toBeInTheDocument()
    expect(screen.getByLabelText('取消职业自选技能 攀爬')).toBeInTheDocument()
  })

  it('requires allocated occupation choice skills to be cleared before removal', async () => {
    renderPage()
    await advanceToReporterSkills()
    fireEvent.click(screen.getAllByRole('button', { name: /选择技能/ })[0])
    fireEvent.click(screen.getByRole('button', { name: /取悦/ }))

    fireEvent.click(screen.getByLabelText('取悦 增加技能点'))
    fireEvent.click(screen.getByLabelText('取消职业自选技能 取悦'))
    expect(screen.getByText('请先将「取悦」的加点清零')).toBeInTheDocument()
    expect(screen.getByLabelText('取消职业自选技能 取悦')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('取悦 减少技能点'))
    fireEvent.click(screen.getByLabelText('取消职业自选技能 取悦'))
    expect(screen.queryByLabelText('取消职业自选技能 取悦')).not.toBeInTheDocument()
  })

  it('lets credit be typed directly and keeps occupation and interest pools separate', async () => {
    renderPage()

    fireEvent.change(screen.getByPlaceholderText('角色姓名'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('会计师'))
    await advanceToAttributesAfterOccupationPreview()

    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(await screen.findByLabelText('信用评级')).toBeInTheDocument()

    const creditInput = screen.getByLabelText('信用评级')
    fireEvent.change(creditInput, { target: { value: '66' } })
    fireEvent.blur(creditInput)
    await waitForPreviewWithSkill('credit-rating', 66)
    expect(screen.getByLabelText('信用评级')).toHaveValue(66)

    fireEvent.change(creditInput, { target: { value: '999' } })
    fireEvent.blur(creditInput)
    await waitForPreviewWithSkill('credit-rating', 70)
    expect(screen.getByLabelText('信用评级')).toHaveValue(70)

    fireEvent.click(screen.getByRole('button', { name: /兴趣技能/ }))
    expect(screen.getByLabelText('潜行 增加技能点')).toBeDisabled()
    expect(screen.getByLabelText('潜行 技能点')).toHaveValue(0)

    fireEvent.click(screen.getByRole('button', { name: /职业技能/ }))
    const occPlus = screen.getByLabelText('会计 增加技能点')
    fireEvent.click(occPlus)
    expect(screen.getByLabelText('会计 技能点')).toHaveValue(1)

    fireEvent.click(occPlus)
    expect(screen.getByLabelText('会计 技能点')).toHaveValue(2)
    expect(occPlus).toBeDisabled()
  })

  it('renders all categorized background fields', async () => {
    renderPage()
    await advanceToBackgroundStep()

    expect(screen.getByLabelText('形象描述')).toBeInTheDocument()
    expect(screen.getByLabelText('恐惧症和躁狂症')).toBeInTheDocument()
    expect(screen.getByLabelText('其他')).toBeInTheDocument()
    expect(screen.queryByText('关键联结')).not.toBeInTheDocument()
  })

  it('submits and caches the same prefixed background string', async () => {
    renderPage()
    await advanceToBackgroundStep()

    fireEvent.change(screen.getByLabelText('形象描述'), { target: { value: '穿着旧风衣' } })
    fireEvent.change(screen.getByLabelText('重要之人'), { target: { value: '导师亨利' } })
    fireEvent.change(screen.getByLabelText('其他'), { target: { value: '随身携带笔记本' } })
    fireEvent.click(screen.getByRole('button', { name: /完成创建/ }))

    const expectedBackground = [
      '形象描述：穿着旧风衣',
      '重要之人：导师亨利',
      '其他：随身携带笔记本',
    ].join('\n')
    await waitFor(() => {
      expect(mockCharacterApi.saveCharacter).toHaveBeenCalledWith(
        'room-1',
        'draft-1',
        expect.objectContaining({ background: expectedBackground })
      )
    })
    await waitFor(() => {
      expect(useCharacterStore.getState().getForRoom('room-1')?.background).toBe(expectedBackground)
    })
  })

  it('loads a legacy background into other and blocks an overlong submission', async () => {
    useCharacterStore.getState().setCharacter(
      {
        info: {
          name: '', playerName: '', age: '28', gender: '男',
          residence: '阿卡姆', birthplace: '阿卡姆', occupationId: null,
        },
        attr: {},
        skillAlloc: {},
        skillFinalValues: {},
        equipment: '',
        background: '没有分类前缀的旧背景',
        notes: '',
        derived: { hp: 0, san: 0, mp: 0, db: '0', move: 0 },
      },
      'room-1'
    )

    renderPage()
    await advanceToBackgroundStep()
    expect(screen.getByLabelText('其他')).toHaveValue('没有分类前缀的旧背景')

    fireEvent.change(screen.getByLabelText('其他'), { target: { value: '字'.repeat(4000) } })
    expect(screen.getByText(/背景故事不能超过 4000 个字符/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /完成创建/ }))
    expect(mockCharacterApi.saveCharacter).not.toHaveBeenCalled()
  })

  it('hydrates categorized background fields from the backend character', async () => {
    useRoomStore.setState({ characterId: 'character-1' })
    mockCharacterApi.fetchCharacter.mockResolvedValue({
      name: '后端调查员',
      age: 30,
      gender: '女',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupation: '会计师',
      attributes: Object.fromEntries(mockRuleset.attributes.map(attribute => [attribute.key, 50])),
      derivedStats: { HP: 10, SAN: 50, MP: 10, DB: '0', MOV: 8 },
      skills: {},
      equipment: [],
      background: '思想与信念：真相总会留下痕迹\n其他：来自旧报社',
      notes: '',
    })

    renderPage()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('角色姓名')).toHaveValue('后端调查员')
    })
    await waitFor(() => {
      expect(mockPreviewCharacter).toHaveBeenCalledWith(expect.objectContaining({ occupationId: 1 }))
    })

    await advanceToAttributesAfterOccupationPreview()
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))
    expect(await screen.findByLabelText('信用评级')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }))

    expect(await screen.findByLabelText('思想与信念')).toHaveValue('真相总会留下痕迹')
    expect(screen.getByLabelText('其他')).toHaveValue('来自旧报社')
  })
})
