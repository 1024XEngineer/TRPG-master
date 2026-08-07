import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AuthPageLayout from './AuthPageLayout'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderLoginLayout(onSubmit = vi.fn(), loading = false) {
  return render(
    <MemoryRouter initialEntries={['/auth/login']}>
      <Routes>
        <Route
          path="/auth/login"
          element={(
            <AuthPageLayout
              mode="login"
              loading={loading}
              error=""
              onSubmit={onSubmit}
            >
              <label>
                账号
                <input name="account" />
              </label>
            </AuthPageLayout>
          )}
        />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => cleanup())

describe('AuthPageLayout', () => {
  it('keeps the visual artwork and accessible brand/form headings together', () => {
    const { container } = renderLoginLayout()

    expect(screen.getByRole('heading', { name: 'AI跑团主持人' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '登录' })).toBeInTheDocument()
    expect(container.querySelector('.auth-scene--login')).toBeInTheDocument()
    expect(container.querySelector('.auth-panel__art')).toHaveAttribute(
      'src',
      '/assets/auth/login-panel.webp',
    )
  })

  it('submits through the form and blocks repeat submission while loading', () => {
    const onSubmit = vi.fn()
    const { container, rerender } = renderLoginLayout(onSubmit)

    fireEvent.submit(container.querySelector('form')!)
    expect(onSubmit).toHaveBeenCalledTimes(1)

    rerender(
      <MemoryRouter initialEntries={['/auth/login']}>
        <AuthPageLayout mode="login" loading error="" onSubmit={onSubmit}>
          <input aria-label="账号" />
        </AuthPageLayout>
      </MemoryRouter>,
    )
    fireEvent.submit(container.querySelector('form')!)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '登录中…' })).toBeDisabled()
  })

  it('switches to the sibling register route from the artwork tab', () => {
    renderLoginLayout()

    fireEvent.click(screen.getByRole('button', { name: '注册' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/auth/register')
  })
})
