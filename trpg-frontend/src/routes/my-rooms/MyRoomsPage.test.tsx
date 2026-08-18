import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { MyRoomSummary } from '@/services/room'
import { getRoomInfo, joinRoomByCode, listMyRooms } from '@/services/room'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { archiveNumber } from '@/utils/archive-number'
import MyRoomsPage, { roomScene } from './MyRoomsPage'

vi.mock('@/services/room', () => ({
  getRoomInfo: vi.fn(),
  joinRoomByCode: vi.fn(),
  listMyRooms: vi.fn(),
}))

vi.mock('@/services/api-client', () => ({
  friendlyErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
}))

const rooms: MyRoomSummary[] = [
  {
    roomId: 'room-in-game',
    roomCode: 'PLAY01',
    roomName: '书店疑云',
    phase: 'InGame',
    moduleTitle: '追书人',
    playerCount: 3,
    maxPlayers: 4,
    updatedAt: '2026-08-15T12:00:00Z',
  },
  {
    roomId: 'room-completed',
    roomCode: 'ENDED1',
    roomName: '旧案归档',
    phase: 'Completed',
    moduleTitle: '追书人',
    playerCount: 4,
    maxPlayers: 4,
    updatedAt: '2026-08-14T12:00:00Z',
  },
]

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/home/my-rooms']}>
      <Routes>
        <Route path="/home/my-rooms" element={<MyRoomsPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MyRoomsPage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: 'account-token',
      userId: 'user-1',
      nickname: 'badada',
      isLoggedIn: true,
    })
    useRoomStore.getState().reset()
    vi.mocked(listMyRooms).mockReset().mockResolvedValue(rooms)
    vi.mocked(joinRoomByCode).mockReset().mockResolvedValue({
      roomId: 'room-in-game',
      roomCode: 'PLAY01',
      reconnectToken: 'reconnect-token',
      playerId: 'player-1',
    })
    vi.mocked(getRoomInfo).mockReset().mockResolvedValue({
      roomId: 'room-in-game',
      roomCode: 'PLAY01',
      roomName: '书店疑云',
      phase: 'InGame',
      storyStarted: true,
      moduleId: 'paper-chase',
      moduleTitle: '追书人',
      playerCount: 3,
      maxPlayers: 4,
      players: [{
        playerId: 'player-1',
        nickname: 'badada',
        isHost: true,
        ready: true,
        hasCharacter: true,
      }],
    })
  })

  afterEach(cleanup)

  it('renders the supplied artwork, stable identity, and real room records', async () => {
    const { container } = renderPage()

    expect(screen.getByRole('heading', { name: '我的游戏' })).toBeInTheDocument()
    expect(container.querySelector('.my-games-scene__background')).toHaveAttribute(
      'src',
      '/assets/rooms/my-games/background.webp',
    )
    expect(container.querySelector('.my-games-scene__case-note')).toHaveAttribute(
      'src',
      '/assets/rooms/my-games/cat-poster.webp',
    )
    expect(screen.getByAltText('当前玩家头像')).toHaveAttribute(
      'src',
      '/assets/rooms/my-games/cat-avatar.webp',
    )
    expect(screen.getByText('badada')).toBeInTheDocument()
    expect(screen.getByText(archiveNumber('user-1'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '个人档案' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '角色卡管理' })).toBeEnabled()

    expect(await screen.findByRole('heading', { name: '书店疑云' })).toBeInTheDocument()
    expect(screen.getAllByText('追书人')).toHaveLength(2)
    expect(screen.getByText('游戏进行中')).toBeInTheDocument()
    expect(screen.getByText('游戏已完成')).toBeInTheDocument()
    expect(screen.getByText('已加载全部记录')).toBeInTheDocument()
    expect(container.querySelector('.my-games-scene__thumbnail img')).toHaveAttribute(
      'src',
      roomScene('room-in-game'),
    )
  })

  it('keeps home, profile, character-library, and completed-game navigation available', async () => {
    const firstView = renderPage()
    await screen.findByRole('heading', { name: '旧案归档' })

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home')

    firstView.unmount()
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: '个人档案' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/profile')

    cleanup()
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: '角色卡管理' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/characters')

    cleanup()
    renderPage()
    await screen.findByRole('button', { name: '查看旧案归档的复盘' })
    fireEvent.click(screen.getByRole('button', { name: '查看旧案归档的复盘' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/my-rooms/review/ENDED1')
    expect(joinRoomByCode).not.toHaveBeenCalled()
  })

  it.each([
    ['Lobby', '/room/lobby'],
    ['Building', '/room/ready'],
    ['InGame', '/room/play'],
    ['Suspended', '/room/play'],
  ])('resumes a %s room at %s and restores its identity', async (phase, destination) => {
    vi.mocked(listMyRooms).mockResolvedValue([{ ...rooms[0], phase }])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '继续书店疑云' }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(destination))
    expect(joinRoomByCode).toHaveBeenCalledWith('PLAY01', 'badada')
    expect(getRoomInfo).toHaveBeenCalledWith('PLAY01')
    expect(useRoomStore.getState()).toMatchObject({
      roomId: 'room-in-game',
      roomCode: 'PLAY01',
      playerId: 'player-1',
      reconnectToken: 'reconnect-token',
      moduleId: 'paper-chase',
      isHost: true,
    })
  })

  it('prevents a second resume while the first request is pending', async () => {
    let resolveJoin: ((value: Awaited<ReturnType<typeof joinRoomByCode>>) => void) | undefined
    vi.mocked(listMyRooms).mockResolvedValue([
      rooms[0],
      { ...rooms[0], roomId: 'room-two', roomCode: 'PLAY02', roomName: '第二现场' },
    ])
    vi.mocked(joinRoomByCode).mockImplementation(() => new Promise((resolve) => {
      resolveJoin = resolve
    }))
    renderPage()

    const firstButton = await screen.findByRole('button', { name: '继续书店疑云' })
    const secondButton = screen.getByRole('button', { name: '继续第二现场' })
    fireEvent.click(firstButton)

    expect(await screen.findByRole('button', { name: '继续第二现场' })).toBeDisabled()
    fireEvent.click(secondButton)
    expect(joinRoomByCode).toHaveBeenCalledTimes(1)

    resolveJoin?.({
      roomId: 'room-in-game',
      roomCode: 'PLAY01',
      reconnectToken: 'reconnect-token',
      playerId: 'player-1',
    })
  })

  it('shows themed empty actions and a retryable load error', async () => {
    vi.mocked(listMyRooms).mockResolvedValueOnce([])
    const emptyView = renderPage()

    expect(await screen.findByText('档案中还没有游戏记录')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '创建房间' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/create')

    emptyView.unmount()
    vi.mocked(listMyRooms).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(rooms)
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('加载房间列表失败')

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('heading', { name: '书店疑云' })).toBeInTheDocument()
    expect(listMyRooms).toHaveBeenCalledTimes(3)
  })
})
