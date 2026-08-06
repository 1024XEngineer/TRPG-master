import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ModuleDetail, ModuleSummary } from 'trpg-sdk'
import { getModuleDetail, listModules } from '@/services/room'
import ScenarioSelectionPage from './ScenarioSelectionPage'
import { FIXED_TRPG } from '@/config/games'
import { useGameStore } from '@/stores/game-store'
import CreateRoomPage, { clampPlayerCount } from '@/routes/create/CreateRoomPage'
import { useRoomStore } from '@/stores/room-store'

vi.mock('@/services/room', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/room')>()
  return { ...actual, getModuleDetail: vi.fn(), listModules: vi.fn() }
})

const moduleSummary: ModuleSummary = {
  id: 'paper-chase-zh-coc7',
  gameSystemId: FIXED_TRPG.systemId,
  gameSystemName: FIXED_TRPG.systemCatalogName,
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
  cleanup()
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

  it('keeps game and system identities in fixed config instead of selection state', () => {
    useGameStore.getState().setScene('legacy-module')

    useGameStore.getState().reset()

    expect(FIXED_TRPG.gameId).toBe('trpg')
    expect(FIXED_TRPG.systemId).toBe('00000000-0000-0000-0000-000000000002')
    expect(useGameStore.getState().sceneId).toBeNull()
    expect(useGameStore.getState()).not.toHaveProperty('setGame')
  })

  it('renders only COC7 module metadata without placeholder fallbacks', async () => {
    const otherSystemModule: ModuleSummary = {
      ...moduleSummary,
      id: 'other-system-module',
      gameSystemId: 'other-system',
      title: '其他规则模组',
    }
    vi.mocked(listModules).mockResolvedValue([otherSystemModule, moduleSummary])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <Routes>
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '选择模组' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Paper Chase')).toBeInTheDocument())
    expect(screen.getByText('禁酒令时期的阿诺兹堡，五本珍藏旧书失窃。')).toBeInTheDocument()
    expect(screen.getByText('1 人')).toBeInTheDocument()
    expect(screen.getByText('1-2 小时')).toBeInTheDocument()
    expect(screen.queryByText('其他规则模组')).not.toBeInTheDocument()
    expect(screen.queryByText(/MS1 骨架联调/)).not.toBeInTheDocument()
  })

  it('stores the selected module and returns to create-room', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <Routes>
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
          <Route path="/home/create" element={<p>创建房间页面</p>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /追书人/ }))

    expect(await screen.findByText('创建房间页面')).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBe(moduleSummary.id)
  })

  it('returns from the module catalog without changing the fixed game system', async () => {
    vi.mocked(listModules).mockResolvedValue([])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <Routes>
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
          <Route path="/home/create" element={<p>创建房间页面</p>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: '返回创建房间' }))

    expect(await screen.findByText('创建房间页面')).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBeNull()
  })

  it('opens the module catalog directly and preserves the create-room form', async () => {
    render(
      <MemoryRouter initialEntries={['/home/create']}>
        <Routes>
          <Route path="/home/create" element={<CreateRoomPage />} />
          <Route path="/home/create/modules" element={<p>模组目录页面</p>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByRole('textbox', { name: '房间名称' }), {
      target: { value: '阿卡姆调查团' },
    })
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '6' } })
    expect(screen.getByText(FIXED_TRPG.gameName)).toBeInTheDocument()
    expect(screen.getByText(FIXED_TRPG.systemCatalogName)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '选择模组' }))

    expect(await screen.findByText('模组目录页面')).toBeInTheDocument()
    expect(useRoomStore.getState()).toMatchObject({
      createFormRoomName: '阿卡姆调查团',
      createFormMaxPlayers: 6,
    })
    expect(useGameStore.getState().sceneId).toBeNull()
  })

  it('locks the create-room player control to the selected module range', async () => {
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
