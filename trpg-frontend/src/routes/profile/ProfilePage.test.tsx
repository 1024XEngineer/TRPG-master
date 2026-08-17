import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { fetchMe, logout, updateProfile } from '@/services/auth'
import { useAuthStore } from '@/stores/auth-store'
import ProfilePage, { archiveNumber } from './ProfilePage'

const storeMocks = vi.hoisted(() => ({
  resetRoom: vi.fn(),
  clearCharacter: vi.fn(),
}))

vi.mock('@/services/auth', () => ({
  fetchMe: vi.fn(),
  logout: vi.fn(),
  updateProfile: vi.fn(),
}))

vi.mock('@/services/api-client', () => ({
  friendlyErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
}))

vi.mock('@/stores/room-store', () => ({
  useRoomStore: (selector: (state: { reset: () => void }) => unknown) => (
    selector({ reset: storeMocks.resetRoom })
  ),
}))

vi.mock('@/stores/character-store', () => ({
  useCharacterStore: (selector: (state: { clear: () => void }) => unknown) => (
    selector({ clear: storeMocks.clearCharacter })
  ),
}))

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={['/home/profile']}>
      <Routes>
        <Route path="/home/profile" element={<ProfilePage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProfilePage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: 'token',
      userId: 'user-1',
      nickname: '旧昵称',
      isLoggedIn: true,
    })
    storeMocks.resetRoom.mockReset()
    storeMocks.clearCharacter.mockReset()
    vi.mocked(fetchMe).mockReset().mockResolvedValue({
      userId: 'user-1',
      account: 'detective@example.com',
      nickname: '旧昵称',
    })
    vi.mocked(updateProfile).mockReset()
    vi.mocked(logout).mockReset().mockResolvedValue(undefined)
  })

  afterEach(cleanup)

  it('loads the account into the themed dossier and derives a stable archive number', async () => {
    const { container } = renderProfile()

    expect(screen.getByRole('heading', { name: '个人档案' })).toBeInTheDocument()
    expect(container.querySelector('.profile-scene__background')).toHaveAttribute(
      'src',
      '/assets/profile/background.webp',
    )
    expect(container.querySelector('.profile-scene__dossier')).toHaveAttribute(
      'src',
      '/assets/profile/dossier.webp',
    )
    expect(await screen.findByLabelText('昵称')).toHaveValue('旧昵称')
    expect(screen.getByLabelText('账号')).toHaveValue('detective@example.com')
    expect(screen.getByLabelText('账号')).toHaveAttribute('readonly')
    const archiveNumberElement = screen.getByText(archiveNumber('user-1'))
    expect(archiveNumberElement).toHaveClass('profile-scene__archive-number')
    expect(archiveNumberElement.parentElement).toHaveTextContent(
      `DM 档案库编号： ${archiveNumber('user-1')}`,
    )
    expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled()
  })

  it('shows a read error when the profile service returns no user', async () => {
    vi.mocked(fetchMe).mockResolvedValue(null)
    renderProfile()

    expect(await screen.findByText('档案读取失败，请稍后重试')).toBeInTheDocument()
    expect(screen.getByLabelText('账号')).toHaveValue('')
    expect(screen.getByLabelText('账号')).toHaveAttribute('placeholder', '暂无账号信息')
  })

  it('saves a changed nickname and updates the global identity', async () => {
    vi.mocked(updateProfile).mockResolvedValue({
      userId: 'user-1',
      account: 'detective@example.com',
      nickname: '新昵称',
    })
    renderProfile()

    const nicknameInput = await screen.findByLabelText('昵称')
    fireEvent.change(nicknameInput, { target: { value: '  新昵称  ' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }))

    await waitFor(() => expect(updateProfile).toHaveBeenCalledWith('新昵称'))
    expect(await screen.findByText('修改已保存')).toBeInTheDocument()
    expect(nicknameInput).toHaveValue('新昵称')
    expect(useAuthStore.getState().nickname).toBe('新昵称')
    expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled()
  })

  it('keeps the draft and shows an understandable error when saving fails', async () => {
    vi.mocked(updateProfile).mockRejectedValue(new Error('network'))
    renderProfile()

    const nicknameInput = await screen.findByLabelText('昵称')
    fireEvent.change(nicknameInput, { target: { value: '未保存昵称' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }))

    expect(await screen.findByText('保存失败，请稍后重试')).toBeInTheDocument()
    expect(nicknameInput).toHaveValue('未保存昵称')
    expect(useAuthStore.getState().nickname).toBe('旧昵称')
  })

  it('returns home and clears all local session state when logging out', async () => {
    const view = renderProfile()
    await screen.findByDisplayValue('detective@example.com')

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home')

    view.unmount()
    renderProfile()
    await screen.findByDisplayValue('detective@example.com')
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/auth/login'))
    expect(logout).toHaveBeenCalledTimes(1)
    expect(storeMocks.resetRoom).toHaveBeenCalledTimes(1)
    expect(storeMocks.clearCharacter).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().isLoggedIn).toBe(false)
  })
})
