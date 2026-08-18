import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { friendlyErrorMessage } from '@/services/api-client'
import { joinRoomByCode } from '@/services/room'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import JoinRoomPage from './JoinRoomPage'

vi.mock('@/services/room', () => ({
  joinRoomByCode: vi.fn(),
}))

vi.mock('@/services/api-client', () => ({
  friendlyErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
}))

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderJoinRoom() {
  return render(
    <MemoryRouter initialEntries={['/home/join']}>
      <Routes>
        <Route path="/home/join" element={<JoinRoomPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('JoinRoomPage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: 'token',
      userId: 'user-1',
      nickname: '调查员猫猫',
      isLoggedIn: true,
    })
    useRoomStore.getState().reset()
    vi.mocked(joinRoomByCode).mockReset()
    vi.mocked(friendlyErrorMessage).mockReset()
      .mockImplementation((_error: unknown, fallback = '操作失败，请稍后重试') => fallback)
  })

  afterEach(cleanup)

  it('renders the themed scene without the room-code explanation panel', () => {
    const { container } = renderJoinRoom()

    expect(screen.getByRole('heading', { name: '加入房间' })).toBeInTheDocument()
    expect(screen.queryByText('房间号是什么？')).not.toBeInTheDocument()
    expect(container.querySelector('.join-room-scene__background')).toHaveAttribute(
      'src',
      '/assets/rooms/join/background.webp',
    )
    expect(container.querySelector('.join-room-scene__poster')).toHaveAttribute(
      'src',
      '/assets/rooms/join/detective-poster.webp',
    )
    expect(container.querySelector('.join-room-scene__dossier-art')).toHaveAttribute(
      'src',
      '/assets/rooms/join/join-dossier.webp',
    )
    expect(screen.getByRole('button', { name: '创建房间' }).querySelector('img')).toHaveAttribute(
      'src',
      '/assets/rooms/join/create-room-button.webp',
    )
    expect(screen.getByRole('button', { name: '加入房间' })).toBeDisabled()
  })

  it('normalizes letters and numbers, filters other characters, and caps the code at six', () => {
    renderJoinRoom()
    const input = screen.getByLabelText('输入 6 位房间码')

    fireEvent.change(input, { target: { value: 'ab-12_cd34' } })

    expect(input).toHaveValue('AB12CD')
    expect(screen.getByRole('button', { name: '加入房间' })).toBeEnabled()
  })

  it('submits with Enter, persists the identity, and enters the lobby', async () => {
    vi.mocked(joinRoomByCode).mockResolvedValue({
      roomId: 'room-1',
      roomCode: 'AB12CD',
      playerId: 'player-1',
      reconnectToken: 'reconnect-1',
      characterId: null,
    })
    renderJoinRoom()

    const input = screen.getByLabelText('输入 6 位房间码')
    fireEvent.change(input, { target: { value: 'ab12cd' } })
    fireEvent.submit(input.closest('form')!)

    expect(screen.getByRole('button', { name: '加入中…' })).toBeDisabled()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/room/lobby'))
    expect(joinRoomByCode).toHaveBeenCalledWith('AB12CD', '调查员猫猫')
    expect(useRoomStore.getState()).toMatchObject({
      roomId: 'room-1',
      roomCode: 'AB12CD',
      playerId: 'player-1',
      reconnectToken: 'reconnect-1',
      isHost: false,
    })
  })

  it('prevents duplicate requests from rapid repeated submissions', async () => {
    let resolveJoin: ((value: {
      roomId: string
      roomCode: string
      playerId: string
      reconnectToken: string
    }) => void) | undefined
    vi.mocked(joinRoomByCode).mockImplementation(() => new Promise((resolve) => {
      resolveJoin = resolve
    }))
    renderJoinRoom()

    const input = screen.getByLabelText('输入 6 位房间码')
    const form = input.closest('form')!
    fireEvent.change(input, { target: { value: 'ABC123' } })
    fireEvent.submit(form)
    fireEvent.submit(form)

    expect(joinRoomByCode).toHaveBeenCalledTimes(1)
    resolveJoin?.({
      roomId: 'room-1',
      roomCode: 'ABC123',
      playerId: 'player-1',
      reconnectToken: 'reconnect-1',
    })
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/room/lobby'))
  })

  it('keeps the room code and announces an understandable service error', async () => {
    const serviceError = new Error('房间不存在')
    vi.mocked(joinRoomByCode).mockRejectedValue(serviceError)
    vi.mocked(friendlyErrorMessage).mockReturnValue('房间不存在，请向房主确认房间码')
    renderJoinRoom()

    const input = screen.getByLabelText('输入 6 位房间码')
    fireEvent.change(input, { target: { value: 'ABC123' } })
    fireEvent.click(screen.getByRole('button', { name: '加入房间' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('房间不存在，请向房主确认房间码')
    expect(input).toHaveValue('ABC123')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(friendlyErrorMessage).toHaveBeenCalledWith(serviceError, '加入房间失败，请稍后重试')

    fireEvent.change(input, { target: { value: 'ABC124' } })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps the home and create-room navigation paths', () => {
    const view = renderJoinRoom()

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home')

    view.unmount()
    renderJoinRoom()
    fireEvent.click(screen.getByRole('button', { name: '创建房间' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/create')
  })
})
