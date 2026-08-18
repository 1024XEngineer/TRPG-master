import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchCharacter } from '@/services/character/character-api'
import CharacterReadyPage from './CharacterReadyPage'
import { usePortraitGenerationStore } from '@/stores/portrait-generation-store'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  deleteCharacterTemplate: vi.fn(),
  createCharacterTemplate: vi.fn(),
  room: {
    roomId: 'room-1',
    roomCode: 'ABC123',
    isHost: true,
    playerId: 'player-self',
    reconnectToken: 'token-1',
    characterId: null as string | null,
  },
  character: {
    info: {
      name: '林默',
      playerName: '',
      age: '28',
      gender: '男',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupationId: 'accountant',
    },
    attr: { STR: 50 },
    skillAlloc: {},
    skillFinalValues: { accounting: 60 },
    occupationChoiceSkillIds: [],
    equipment: '笔记本',
    background: '旧日经历',
    notes: '',
    derived: { hp: 10, san: 50, mp: 10 },
  },
  players: [
    { playerId: 'player-self', nickname: '测试玩家', hasCharacter: true, hasPortrait: false },
    { playerId: 'player-two', nickname: '队友', hasCharacter: true, hasPortrait: false },
  ],
}))

vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate }))
vi.mock('@/stores/room-store', () => ({
  useRoomStore: (selector: (state: typeof mocks.room) => unknown) => selector(mocks.room),
}))
vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (state: { nickname: string }) => unknown) => selector({ nickname: '测试玩家' }),
}))
vi.mock('@/stores/character-store', () => ({
  useCharacterStore: (selector: (state: { getForRoom: (roomId: string) => typeof mocks.character | null }) => unknown) => (
    selector({ getForRoom: (roomId: string) => roomId === 'room-1' ? mocks.character : null })
  ),
}))
vi.mock('@/hooks/useRoomPlayers', () => ({
  useRoomPlayers: () => ({ players: mocks.players, maxPlayers: 4, phase: 'Building' }),
}))
vi.mock('@/hooks/usePlayerPortraits', () => ({ usePlayerPortraits: () => ({}) }))
vi.mock('@/hooks/useRuleset', () => ({
  useRuleset: () => ({
    ruleset: {
      occupations: [{ id: 'accountant', name: '会计师' }],
      attributes: [{ key: 'STR', label: '力量' }],
      skills: [{ id: 'accounting', name: '会计' }],
    },
  }),
}))
vi.mock('@/services/character/character-api', () => ({ fetchCharacter: vi.fn() }))
vi.mock('@/services/character/template-api', () => ({
  createCharacterTemplate: mocks.createCharacterTemplate,
  deleteCharacterTemplate: mocks.deleteCharacterTemplate,
  templateDataFromBuilt: vi.fn((value: unknown) => value),
}))
vi.mock('@/services/api-client', () => ({
  connectWebSocket: vi.fn(),
  disconnectWebSocket: vi.fn(),
  waitForWsOpen: vi.fn(),
  sdk: { roomSocket: { joinRoom: vi.fn(), startGame: vi.fn() } },
}))
vi.mock('@/features/onboarding', () => ({ OnboardingTrigger: () => <button>规则指引</button> }))
vi.mock('@/features/portrait/PortraitImage', () => ({ PortraitImage: () => <img alt="角色头像" /> }))
vi.mock('./PortraitGenerationModal', () => ({ PortraitGenerationModal: () => null }))

describe('CharacterReadyPage', () => {
  beforeEach(() => {
    mocks.navigate.mockReset()
    mocks.room.roomId = 'room-1'
    mocks.room.characterId = null
    vi.mocked(fetchCharacter).mockReset()
    mocks.deleteCharacterTemplate.mockReset()
    mocks.createCharacterTemplate.mockReset()
    usePortraitGenerationStore.setState({ tasks: {}, cancelling: {}, notices: [], portraitVersions: {} })
  })
  afterEach(cleanup)

  it('使用档案布局展示房间和玩家建卡状态', () => {
    render(<CharacterReadyPage />)

    expect(screen.getByRole('heading', { name: '房间码 ABC123' })).toBeInTheDocument()
    expect(screen.getByText('测试玩家（你）')).toBeInTheDocument()
    expect(screen.getByText('调查员：林默')).toBeInTheDocument()
    expect(screen.getByText('队友')).toBeInTheDocument()
    expect(screen.getByText('已建卡')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始游戏' })).toBeEnabled()
  })

  it('生图任务进行中仍可开始游戏，跳转不会清除任务', async () => {
    usePortraitGenerationStore.getState().setTask('room-1', 'character-1', {
      generationId: 'generation-1', status: 'generating', cancelRequested: false,
      style: 'realistic', size: '1024x1024', createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    })
    render(<CharacterReadyPage />)
    fireEvent.click(screen.getByRole('button', { name: '开始游戏' }))
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/room/play'))
    expect(usePortraitGenerationStore.getState().tasks['room-1/character-1']?.status).toBe('generating')
  })

  it('本人可以打开主题化角色卡并进入编辑页面', () => {
    render(<CharacterReadyPage />)

    fireEvent.click(screen.getByRole('button', { name: '查看' }))
    expect(screen.getByRole('heading', { name: '调查员 · 林默' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    expect(mocks.navigate).toHaveBeenCalledWith('/room/character', { state: { fromCharacterReady: true } })
  })

  it('从卡库播种的房间角色不会在准备页删除源卡', async () => {
    mocks.room.characterId = 'character-1'
    vi.mocked(fetchCharacter).mockResolvedValue({
      id: 'character-1',
      status: 'Completed',
      generationMethod: 'manual',
      name: '林默',
      age: 28,
      gender: '男',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupation: '会计师',
      attributes: { STR: 55 },
      skills: { accounting: 65 },
      occupationChoiceSkillIds: [],
      equipment: [],
      background: '',
      notes: '',
      derivedStats: { hp: 10, san: 50, mp: 10 },
      basedOnTemplateId: 'template-1',
    } as Awaited<ReturnType<typeof fetchCharacter>>)
    render(<CharacterReadyPage />)

    const libraryStatus = await screen.findByRole('button', {
      name: '这张调查员已在我的角色卡库',
    })
    expect(libraryStatus).toBeDisabled()
    fireEvent.click(libraryStatus)
    expect(mocks.deleteCharacterTemplate).not.toHaveBeenCalled()
  })

  it('切换到没有角色的房间时不会保留上一房间的远程角色', async () => {
    mocks.room.characterId = 'character-1'
    vi.mocked(fetchCharacter).mockResolvedValue({
      id: 'character-1',
      status: 'Completed',
      generationMethod: 'manual',
      name: '远程调查员',
      age: 31,
      gender: '女',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupation: '会计师',
      attributes: { STR: 55 },
      skills: { accounting: 65 },
      occupationChoiceSkillIds: [],
      equipment: [],
      background: '',
      notes: '',
      derivedStats: { hp: 10, san: 50, mp: 10 },
    } as Awaited<ReturnType<typeof fetchCharacter>>)

    const view = render(<CharacterReadyPage />)
    expect(await screen.findByText('调查员：远程调查员')).toBeInTheDocument()

    mocks.room.roomId = 'room-2'
    mocks.room.characterId = null
    view.rerender(<CharacterReadyPage />)

    await waitFor(() => {
      expect(screen.queryByText('调查员：远程调查员')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: '创建人物卡' })).toBeInTheDocument()
    })
  })
})
