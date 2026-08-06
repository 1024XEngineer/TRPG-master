import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RoomPreview } from 'trpg-sdk'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { sdk } from '@/services/api-client'
import { startStory } from '@/services/room'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import LobbyPage from './LobbyPage'

vi.mock('@/hooks/useRoomPlayers', () => ({ useRoomPlayers: vi.fn() }))

vi.mock('@/services/room', () => ({ startStory: vi.fn() }))

vi.mock('@/services/api-client', () => ({
  connectWebSocket: vi.fn(() => ({})),
  disconnectWebSocket: vi.fn(),
  friendlyErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
  onWsMessage: vi.fn(() => () => {}),
  waitForWsOpen: vi.fn(() => Promise.resolve()),
  sdk: {
    roomSocket: {
      joinRoom: vi.fn(),
      setReady: vi.fn(),
    },
  },
}))

function roomPreview(overrides: Partial<RoomPreview> = {}): RoomPreview {
  return {
    roomId: 'room-1',
    roomCode: 'FBSVKF',
    roomName: '周末冒险队',
    phase: 'Lobby',
    storyStarted: false,
    moduleId: 'paper-chase-zh-coc7',
    moduleTitle: '追书人',
    playerCount: 2,
    maxPlayers: 3,
    players: [
      { playerId: 'host-1', nickname: '皮卡丘', isHost: true, ready: false, hasCharacter: false },
      { playerId: 'guest-1', nickname: '妙蛙种子', isHost: false, ready: false, hasCharacter: false },
    ],
    ...overrides,
  }
}

function renderLobby() {
  return render(
    <MemoryRouter>
      <LobbyPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useRoomStore.getState().reset()
  useRoomStore.getState().setRoomIdentity({
    roomId: 'room-1',
    roomCode: 'FBSVKF',
    playerId: 'host-1',
    reconnectToken: 'reconnect-token',
  })
  useRoomStore.getState().setHost(true)
  useAuthStore.getState().login('token', 'user-1', '皮卡丘')
  vi.mocked(useRoomPlayers).mockReturnValue(roomPreview())
  vi.mocked(sdk.roomSocket.setReady).mockReturnValue(true)
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
  vi.clearAllMocks()
  useRoomStore.getState().reset()
  useAuthStore.getState().logout()
})

describe('LobbyPage', () => {
  it('renders real room data and only the remaining dynamic seats', () => {
    renderLobby()

    expect(screen.getByRole('heading', { name: '房间码 FBSVKF' })).toHaveTextContent('FBSVKF')
    expect(screen.getByText('皮卡丘（你）')).toBeInTheDocument()
    expect(screen.getByText('妙蛙种子')).toBeInTheDocument()
    expect(screen.getByText('房主')).toBeInTheDocument()
    expect(screen.getByText('未就绪')).toBeInTheDocument()
    expect(screen.getAllByTestId('lobby-empty-seat')).toHaveLength(1)
    expect(screen.getByRole('button', { name: '开始游戏' })).toBeDisabled()
  })

  it('does not leave baked empty seats in a full one-player room', () => {
    vi.mocked(useRoomPlayers).mockReturnValue(roomPreview({
      playerCount: 1,
      maxPlayers: 1,
      players: [
        { playerId: 'host-1', nickname: '皮卡丘', isHost: true, ready: false, hasCharacter: false },
      ],
    }))

    renderLobby()

    expect(screen.queryByTestId('lobby-empty-seat')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始游戏' })).toBeEnabled()
  })

  it('keeps an optimistic ready state until a fresh poll confirms it', async () => {
    useRoomStore.getState().setRoomIdentity({
      roomId: 'room-1',
      roomCode: 'FBSVKF',
      playerId: 'guest-1',
      reconnectToken: 'guest-token',
    })
    useRoomStore.getState().setHost(false)
    let preview = roomPreview()
    vi.mocked(useRoomPlayers).mockImplementation(() => preview)

    const { rerender } = renderLobby()

    const readyButton = await screen.findByRole('button', { name: '标记为已就绪' })
    fireEvent.click(readyButton)

    expect(sdk.roomSocket.setReady).toHaveBeenCalledWith('guest-1', { ready: true })
    expect(screen.getByRole('button', { name: '同步中…' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '同步中…' })).toBeDisabled()

    // 下一轮轮询仍是旧值时，不能把用户刚才的操作拍回去。
    preview = roomPreview()
    rerender(
      <MemoryRouter>
        <LobbyPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: '同步中…' })).toHaveAttribute('aria-pressed', 'true')

    preview = roomPreview({
      players: [
        { playerId: 'host-1', nickname: '皮卡丘', isHost: true, ready: false, hasCharacter: false },
        { playerId: 'guest-1', nickname: '妙蛙种子', isHost: false, ready: true, hasCharacter: false },
      ],
    })
    rerender(
      <MemoryRouter>
        <LobbyPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: '取消就绪' })).toBeEnabled())
    expect(screen.getByText('你已就绪，等待房主开始游戏')).toBeInTheDocument()
  })

  it('does not allow a ready action before the server state is hydrated', () => {
    useRoomStore.getState().setRoomIdentity({
      roomId: 'room-1',
      roomCode: 'FBSVKF',
      playerId: 'guest-1',
      reconnectToken: 'guest-token',
    })
    useRoomStore.getState().setHost(false)
    vi.mocked(useRoomPlayers).mockReturnValue(null)

    renderLobby()

    const readyButton = screen.getByRole('button', { name: '正在同步状态…' })
    expect(readyButton).toBeDisabled()
    fireEvent.click(readyButton)
    expect(sdk.roomSocket.setReady).not.toHaveBeenCalled()
  })

  it('rolls back immediately when the ready command cannot be sent', () => {
    useRoomStore.getState().setRoomIdentity({
      roomId: 'room-1',
      roomCode: 'FBSVKF',
      playerId: 'guest-1',
      reconnectToken: 'guest-token',
    })
    useRoomStore.getState().setHost(false)
    vi.mocked(sdk.roomSocket.setReady).mockReturnValueOnce(false)

    renderLobby()
    fireEvent.click(screen.getByRole('button', { name: '标记为已就绪' }))

    expect(screen.getByRole('button', { name: '标记为已就绪' })).toBeEnabled()
    expect(screen.getByRole('alert')).toHaveTextContent('就绪状态发送失败')
  })

  it('rolls back when no server confirmation arrives before the timeout', () => {
    vi.useFakeTimers()
    useRoomStore.getState().setRoomIdentity({
      roomId: 'room-1',
      roomCode: 'FBSVKF',
      playerId: 'guest-1',
      reconnectToken: 'guest-token',
    })
    useRoomStore.getState().setHost(false)

    renderLobby()
    fireEvent.click(screen.getByRole('button', { name: '标记为已就绪' }))
    act(() => vi.advanceTimersByTime(7_000))

    expect(screen.getByRole('button', { name: '标记为已就绪' })).toBeEnabled()
    expect(screen.getByRole('alert')).toHaveTextContent('就绪状态同步超时')
  })

  it('shows a themed start error and keeps the host in the lobby', async () => {
    vi.mocked(useRoomPlayers).mockReturnValue(roomPreview({
      players: [
        { playerId: 'host-1', nickname: '皮卡丘', isHost: true, ready: false, hasCharacter: false },
        { playerId: 'guest-1', nickname: '妙蛙种子', isHost: false, ready: true, hasCharacter: false },
      ],
    }))
    vi.mocked(startStory).mockRejectedValue(new Error('network unavailable'))

    renderLobby()
    fireEvent.click(screen.getByRole('button', { name: '开始游戏' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('开始游戏失败')
    await waitFor(() => expect(screen.getByRole('button', { name: '开始游戏' })).toBeEnabled())
  })

  it('opens the themed leave confirmation and closes it with Escape', async () => {
    renderLobby()

    fireEvent.click(screen.getByRole('button', { name: '离开房间' }))

    expect(screen.getByRole('dialog', { name: '解散冒险队？' })).toBeInTheDocument()
    expect(screen.getByText('所有成员将被移出当前房间。')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '继续等待' })).toHaveFocus())

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
