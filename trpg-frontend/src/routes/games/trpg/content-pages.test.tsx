import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    { title: '调查员准备', content: '擅长交涉、侦查或图书馆使用会更容易推进调查。' },
  ],
}

const replacementModuleSummary: ModuleSummary = {
  ...moduleSummary,
  id: 'arkham-files-coc7',
  title: '阿卡姆档案',
  nameEn: 'Arkham Files',
  playersMin: 2,
  playersMax: 4,
  synopsis: '一份没有专属封面的测试模组。',
}

const replacementModuleDetail: ModuleDetail = {
  ...moduleDetail,
  ...replacementModuleSummary,
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
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
    const moduleWithoutCover: ModuleSummary = {
      ...moduleSummary,
      id: 'another-coc7-module',
      title: '未配置封面',
      nameEn: 'Unknown Cover',
      playersMin: 2,
      playersMax: 4,
      estimatedDuration: '3 小时',
      synopsis: '用于验证默认模组封面的测试数据。',
    }
    vi.mocked(listModules).mockResolvedValue([otherSystemModule, moduleSummary, moduleWithoutCover])

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
    expect(screen.getByAltText('未配置封面模组封面')).toHaveAttribute(
      'src',
      '/assets/rooms/scenarios/cover-default.webp',
    )
    expect(screen.queryByText('其他规则模组')).not.toBeInTheDocument()
    expect(screen.queryByText(/MS1 骨架联调/)).not.toBeInTheDocument()
  })

  it('shows a themed catalog error and retries the request', async () => {
    vi.mocked(listModules)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce([moduleSummary])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '模组档案读取失败' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('Paper Chase')).toBeInTheDocument()
    expect(listModules).toHaveBeenCalledTimes(2)
  })

  it('marks the module stored in the create flow as selected', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    vi.mocked(listModules).mockResolvedValue([moduleSummary])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('已选择')).toBeInTheDocument()
  })

  it('opens player-safe details before selecting the module and returns to create-room', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <Routes>
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
          <Route path="/home/create" element={<p>创建房间页面</p>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '查看模组 追书人 详情' }))

    expect(await screen.findByRole('dialog', { name: '追书人' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '故事简介' })).toBeInTheDocument()
    expect(screen.getByText('托马斯请你调查失窃藏书与叔叔的失踪。')).toBeInTheDocument()
    expect(screen.getByText('擅长交涉、侦查或图书馆使用会更容易推进调查。')).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '选择此模组' }))

    expect(await screen.findByText('创建房间页面')).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBe(moduleSummary.id)
  })

  it('uses the module layout instead of title keywords to group detail pages', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])
    vi.mocked(getModuleDetail).mockResolvedValue({
      ...moduleDetail,
      storyPages: [
        { title: '开局前准备', content: '这页仍然属于开局提示。' },
        { title: '调查员须知', content: '这页属于调查员准备。' },
      ],
    })

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '查看模组 追书人 详情' }))

    const openingSection = (await screen.findByRole('heading', { name: '开局提示' })).closest('section')
    const preparationSection = (await screen.findByRole('heading', { name: '调查员须知' })).closest('section')
    expect(openingSection).not.toBeNull()
    expect(preparationSection).not.toBeNull()
    expect(within(openingSection as HTMLElement).getByText('这页仍然属于开局提示。')).toBeInTheDocument()
    expect(within(preparationSection as HTMLElement).getByText('这页属于调查员准备。')).toBeInTheDocument()
  })

  it('reuses loaded module details when reopening the same card', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    const card = await screen.findByRole('button', { name: '查看模组 追书人 详情' })
    fireEvent.click(card)
    expect(await screen.findByText('调查员准备')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭模组详情' }))
    fireEvent.click(card)
    expect(await screen.findByText('调查员准备')).toBeInTheDocument()
    expect(getModuleDetail).toHaveBeenCalledTimes(1)
  })

  it('traps focus inside module details and restores it after closing', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    const trigger = await screen.findByRole('button', { name: '查看模组 追书人 详情' })
    fireEvent.click(trigger)

    const dialog = await screen.findByRole('dialog', { name: '追书人' })
    const closeButton = screen.getByRole('button', { name: '关闭模组详情' })
    const selectButton = await screen.findByRole('button', { name: '选择此模组' })
    await waitFor(() => expect(selectButton).toBeEnabled())

    expect(closeButton).toHaveFocus()
    expect(screen.getByRole('main', { name: 'COC7 模组目录' })).toHaveAttribute('inert')

    selectButton.focus()
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(closeButton).toHaveFocus()

    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
    expect(selectButton).toHaveFocus()

    const backgroundButton = screen.getByRole('button', { name: '返回创建房间' })
    backgroundButton.focus()
    expect(closeButton).toHaveFocus()
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    fireEvent.click(closeButton)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('adds one removable in-memory parsing card for a valid local file', async () => {
    vi.mocked(listModules).mockResolvedValue([moduleSummary])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    await screen.findByText('Paper Chase')
    const input = screen.getByLabelText('选择 PDF 或 DOCX 模组文件')
    const file = new File(['module'], '阿卡姆档案.pdf', { type: 'application/pdf' })
    fireEvent.change(input, { target: { files: [file] } })

    expect(screen.getByRole('heading', { name: '阿卡姆档案' })).toBeInTheDocument()
    expect(screen.getByText('解析中')).toBeInTheDocument()
    expect(screen.getByText('文件已加入队列，解析服务尚未接入。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '已有模组正在解析，请先删除后再导入' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '删除正在解析的模组 阿卡姆档案' }))
    expect(screen.queryByRole('heading', { name: '阿卡姆档案' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '导入 PDF 或 DOCX 模组' })).toBeEnabled()
  })

  it('rejects unsupported and oversized import files', async () => {
    vi.mocked(listModules).mockResolvedValue([])

    render(
      <MemoryRouter initialEntries={['/home/create/modules']}>
        <ScenarioSelectionPage />
      </MemoryRouter>,
    )

    await screen.findByText('暂无可用模组')
    const input = screen.getByLabelText('选择 PDF 或 DOCX 模组文件')
    fireEvent.change(input, {
      target: { files: [new File(['text'], '错误格式.txt', { type: 'text/plain' })] },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('仅支持 PDF 或 DOCX 文件')

    const oversized = new File(['pdf'], '超大模组.pdf', { type: 'application/pdf' })
    Object.defineProperty(oversized, 'size', { value: 20 * 1024 * 1024 + 1 })
    fireEvent.change(input, { target: { files: [oversized] } })
    expect(screen.getByRole('alert')).toHaveTextContent('文件不能超过 20 MB')
    expect(screen.queryByRole('heading', { name: '超大模组' })).not.toBeInTheDocument()
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

  it('shows the selected module cover, name, and change action on the create-room stamp', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter initialEntries={['/home/create']}>
        <CreateRoomPage />
      </MemoryRouter>,
    )

    const stamp = await screen.findByRole('button', { name: '更改模组：追书人' })
    expect(within(stamp).getByText('追书人')).toBeVisible()
    expect(within(stamp).getByText('更改模组')).toBeVisible()
    expect(within(stamp).getByAltText('追书人模组封面')).toHaveAttribute(
      'src',
      '/assets/rooms/scenarios/cover-paper-chase.webp',
    )
  })

  it('keeps the current module when opening the catalog and returning directly', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    vi.mocked(listModules).mockResolvedValue([moduleSummary, replacementModuleSummary])
    vi.mocked(getModuleDetail).mockImplementation(async (moduleId) => (
      moduleId === moduleSummary.id ? moduleDetail : replacementModuleDetail
    ))

    render(
      <MemoryRouter initialEntries={['/home/create']}>
        <Routes>
          <Route path="/home/create" element={<CreateRoomPage />} />
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '更改模组：追书人' }))
    expect(await screen.findByText('已选择')).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBe(moduleSummary.id)

    fireEvent.click(screen.getByRole('button', { name: '返回创建房间' }))
    expect(await screen.findByRole('button', { name: '更改模组：追书人' })).toBeInTheDocument()
    expect(useGameStore.getState().sceneId).toBe(moduleSummary.id)
  })

  it('replaces the current module only after another module is confirmed', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    vi.mocked(listModules).mockResolvedValue([moduleSummary, replacementModuleSummary])
    vi.mocked(getModuleDetail).mockImplementation(async (moduleId) => (
      moduleId === moduleSummary.id ? moduleDetail : replacementModuleDetail
    ))

    render(
      <MemoryRouter initialEntries={['/home/create']}>
        <Routes>
          <Route path="/home/create" element={<CreateRoomPage />} />
          <Route path="/home/create/modules" element={<ScenarioSelectionPage />} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '更改模组：追书人' }))
    fireEvent.click(await screen.findByRole('button', { name: '查看模组 阿卡姆档案 详情' }))
    expect(useGameStore.getState().sceneId).toBe(moduleSummary.id)

    fireEvent.click(await screen.findByRole('button', { name: '选择此模组' }))

    const stamp = await screen.findByRole('button', { name: '更改模组：阿卡姆档案' })
    expect(useGameStore.getState().sceneId).toBe(replacementModuleSummary.id)
    expect(within(stamp).getByAltText('阿卡姆档案模组封面')).toHaveAttribute(
      'src',
      '/assets/rooms/scenarios/cover-default.webp',
    )
  })

  it('falls back to the default cover when a dedicated image fails to load', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    vi.mocked(getModuleDetail).mockResolvedValue(moduleDetail)

    render(
      <MemoryRouter>
        <CreateRoomPage />
      </MemoryRouter>,
    )

    const cover = await screen.findByAltText('追书人模组封面')
    fireEvent.error(cover)
    expect(cover).toHaveAttribute('src', '/assets/rooms/scenarios/cover-default.webp')
  })

  it('shows explicit loading and error states for the selected module', async () => {
    useGameStore.getState().setScene(moduleSummary.id)
    let rejectDetail!: (reason: Error) => void
    vi.mocked(getModuleDetail).mockReturnValue(new Promise((_, reject) => {
      rejectDetail = reject
    }))

    render(
      <MemoryRouter>
        <CreateRoomPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('正在加载模组')).toBeVisible()
    rejectDetail(new Error('network unavailable'))
    expect(await screen.findByText('模组加载失败')).toBeVisible()
    expect(screen.getByText('前往更改模组')).toBeVisible()
    expect(screen.queryByText('选择模组')).not.toBeInTheDocument()
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
