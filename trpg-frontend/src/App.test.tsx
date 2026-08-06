import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import App from './App'
import { listModules } from '@/services/room'

vi.mock('@/services/room', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/room')>()
  return { ...actual, listModules: vi.fn() }
})

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('legacy create-flow routes', () => {
  it.each([
    '/home/create/games',
    '/home/create/games/trpg',
    '/home/create/games/trpg/scenarios/legacy-system',
  ])('redirects %s to the fixed COC7 module catalog', async (legacyPath) => {
    vi.mocked(listModules).mockResolvedValue([])

    render(
      <MemoryRouter initialEntries={[legacyPath]}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '选择模组' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '选择游戏' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '选择规则系统' })).not.toBeInTheDocument()
  })
})
