import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CharacterReadyPage from './CharacterReadyPage'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
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
  useCharacterStore: (selector: (state: { getForRoom: () => typeof mocks.character }) => unknown) => (
    selector({ getForRoom: () => mocks.character })
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
  beforeEach(() => mocks.navigate.mockReset())
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

  it('本人可以打开主题化角色卡并进入编辑页面', () => {
    render(<CharacterReadyPage />)

    fireEvent.click(screen.getByRole('button', { name: '查看' }))
    expect(screen.getByRole('heading', { name: '调查员 · 林默' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    expect(mocks.navigate).toHaveBeenCalledWith('/room/character', { state: { fromCharacterReady: true } })
  })
})
