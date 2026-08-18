import { beforeEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import HomePage from './HomePage'
import { useAuthStore } from '@/stores/auth-store'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderHome(initialEntry = '/home') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/home" element={<HomePage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HomePage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: 'token',
      userId: 'user-1',
      nickname: 'Detective_007',
      isLoggedIn: true,
    })
    cleanup()
  })

  it('keeps the profile entry and all three home navigation paths', async () => {
    renderHome()

    expect(screen.getByText('Detective_007')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '加入房间' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建房间' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '我的游戏' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '我的角色卡' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '加入房间' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/join')

    cleanup()
    renderHome()
    fireEvent.click(screen.getByRole('button', { name: '创建房间' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/create')

    cleanup()
    renderHome()
    fireEvent.click(screen.getByRole('button', { name: '我的游戏' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/my-rooms')

    cleanup()
    renderHome()
    fireEvent.click(screen.getByRole('button', { name: /打开个人信息/ }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/profile')
  })

  it('redirects unauthenticated visitors to login', async () => {
    useAuthStore.setState({
      token: null,
      userId: null,
      nickname: null,
      isLoggedIn: false,
    })
    renderHome()

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/auth/login')
    })
  })
})
