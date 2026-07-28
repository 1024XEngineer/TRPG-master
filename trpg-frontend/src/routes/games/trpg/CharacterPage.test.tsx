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
      { id: 'credit-rating', name: '信用评级', nameEn: 'credit-rating', base: 0, category: 'special' },
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
      },
    ],
  }

  const mockPreviewCharacter = vi.fn(async ({ occupationId, skills }: { occupationId: number | null; skills: Record<string, number> }) => {
    const accounting = skills.accounting ?? 0
    const stealth = skills.stealth ?? 0
    const credit = skills['credit-rating'] ?? 0
    const creditMin = occupationId === 1 ? 0 : 0
    return {
      derivedStats: { HP: 10, SAN: 50, MP: 10, DB: '0', MOV: 8 },
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
      validation: [],
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
})
