import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Game, GameSystem, ModuleDetail, ModuleSummary } from 'trpg-sdk'
import { getModuleDetail, listModules } from '@/services/room'
import SystemSelectionPage from './SystemSelectionPage'
import ScenarioSelectionPage from './ScenarioSelectionPage'
import { sdk } from '@/services/api-client'
import { useGameStore } from '@/stores/game-store'
import CreateRoomPage, { clampPlayerCount } from '@/routes/create/CreateRoomPage'
import { useRoomStore } from '@/stores/room-store'

vi.mock('@/services/room', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/room')>()
  return { ...actual, getModuleDetail: vi.fn(), listModules: vi.fn() }
})

const game: Game = {
  id: 'coc-game',
  name: '克苏鲁的呼唤',
  description: '调查员通过走访与检索接触宇宙恐怖。',
  tags: ['1920年代', '调查悬疑', '宇宙恐怖'],
}

const system: GameSystem = {
  id: 'coc-system',
  gameId: game.id,
  worldRef: 'coc-7e',
  name: 'COC7',
  version: '7th',
}

const moduleSummary: ModuleSummary = {
  id: 'paper-chase-zh-coc7',
  gameSystemId: system.id,
  gameSystemName: system.name,
  title: '追书人',
  nameEn: 'Paper Chase',
  version: '1.0.1',
  status: 'ready',
  authors: [],
  playersMin: 1,
  playersMax: 1,
  difficulty: 1,
  estimatedDuration: '1-2 小时',
  synopsis: '禁酒令时期的阿诺兹堡，五本珍藏旧书失窃。',
}

const moduleDetail: ModuleDetail = {
  ...moduleSummary,
  storyLabel: 'PAPER CHASE',
  subtitle: '五本失窃藏书与一年前的失踪案',
  storyPages: [
    { title: '调查委托', content: '托马斯请你调查失窃藏书与叔叔的失踪。' },
  ],
}

afterEach(() => {
  vi.restoreAllMocks()
  useGameStore.getState().reset()
  useRoomStore.getState().reset()
})

describe('content selection pages', () => {
  it('clamps room size to the published module range', () => {
    expect(clampPlayerCount(4, 1, 1)).toBe(1)
    expect(clampPlayerCount(0, 1, 4)).toBe(1)
    expect(clampPlayerCount(3, 1, 4)).toBe(3)
  })

  it('labels the system page correctly and shows world context', async () => {
    useGameStore.getState().setReturnFromGameSelect(true)
    vi.spyOn(sdk.games, 'list').mockResolvedValue([game])
    vi.spyOn(sdk.games, 'listSystems').mockResolvedValue([system])

    render(
      <MemoryRouter initialEntries={['/home/create/games/trpg']}>
        <Routes>
          <Route path="/home/create/games/:gameId" element={<SystemSelectionPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '选择规则系统' })).toBeInTheDocument()
    expect(screen.getByText(game.description!)).toBeInTheDocument()
    expect(screen.getByText('1920年代')).toBeInTheDocument()
    expect(screen.getByText('适用规则：COC7 7th')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '选择世界' })).not.toBeInTheDocument()
  })

  it('renders published module metadata without placeholder fallbacks', async () => {
    useGameStore.getState().setReturnFromGameSelect(true)
    vi.mocked(listModules).mockResolvedValue([moduleSummary])

    render(
      <MemoryRouter initialEntries={[`/home/create/games/trpg/scenarios/${system.id}`]}>
        <Routes>
          <Route
            path="/home/create/games/:gameId/scenarios/:systemId"
            element={<ScenarioSelectionPage />}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '选择模组' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Paper Chase')).toBeInTheDocument())
    expect(screen.getByText('禁酒令时期的阿诺兹堡，五本珍藏旧书失窃。')).toBeInTheDocument()
    expect(screen.getByText('1 人')).toBeInTheDocument()
    expect(screen.getByText('1-2 小时')).toBeInTheDocument()
    expect(screen.queryByText(/MS1 骨架联调/)).not.toBeInTheDocument()
  })

  it('locks the create-room player control to the selected module range', async () => {
    useGameStore.getState().setGame('trpg', system.id)
    useGameStore.getState().setScene(moduleSummary.id)
    useRoomStore.getState().setCreateForm({ roomName: '单人调查', maxPlayers: 4 })
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter>
        <CreateRoomPage />
      </MemoryRouter>,
    )

    const createButton = screen.getByRole('button', { name: '创建房间' })
    expect(screen.getByRole('textbox', { name: '房间名称' })).toHaveAttribute('maxLength', '200')
    expect(createButton).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('spinbutton')).toHaveValue(1))
    expect(screen.getByText('本模组要求 1 人')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '减少人数' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '增加人数' })).toBeDisabled()
    expect(createButton).toBeEnabled()
  })
})
