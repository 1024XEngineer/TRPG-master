import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { CharacterTemplate } from '@/services/character/template-api'
import {
  createCharacterTemplate,
  deleteCharacterTemplate,
  listCharacterTemplates,
} from '@/services/character/template-api'
import CharacterLibraryPage from './CharacterLibraryPage'

vi.mock('@/services/character/template-api', () => ({
  createCharacterTemplate: vi.fn(),
  deleteCharacterTemplate: vi.fn(),
  listCharacterTemplates: vi.fn(),
}))

vi.mock('@/hooks/useTemplatePortraits', () => ({
  useTemplatePortraits: () => ({ 'template-1': 'blob:portrait-1' }),
}))

vi.mock('@/services/api-client', () => ({
  friendlyErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
}))

const templates: CharacterTemplate[] = [
  {
    templateId: 'template-1',
    name: '林探员',
    systemId: 'coc7',
    data: { attributes: { str: 50 }, occupation: '事务所侦探' },
    hasPortrait: true,
    portraitVersion: 'portrait-1',
    createdAt: '2026-08-18T00:00:00Z',
    updatedAt: '2026-08-18T00:00:00Z',
  },
  {
    templateId: 'template-2',
    name: '未命名调查员',
    systemId: 'coc7',
    data: {},
    hasPortrait: false,
    portraitVersion: null,
    createdAt: '2026-08-18T00:00:00Z',
    updatedAt: '2026-08-18T00:00:00Z',
  },
]

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/home/characters']}>
      <Routes>
        <Route path="/home/characters" element={<CharacterLibraryPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CharacterLibraryPage', () => {
  beforeEach(() => {
    vi.mocked(listCharacterTemplates).mockReset().mockResolvedValue(templates)
    vi.mocked(createCharacterTemplate).mockReset().mockResolvedValue({
      ...templates[0],
      templateId: 'template-new',
      name: '未命名调查员 2',
    })
    vi.mocked(deleteCharacterTemplate).mockReset().mockResolvedValue(null)
  })

  afterEach(cleanup)

  it('renders the themed artwork, real cards, portrait, and empty slot', async () => {
    const { container } = renderPage()

    expect(screen.getByRole('heading', { name: '我的角色卡' })).toBeInTheDocument()
    expect(container.querySelector('.character-library-scene__background')).toHaveAttribute(
      'src',
      '/assets/characters/library/background.webp',
    )
    expect(await screen.findByRole('button', { name: '打开 林探员 的角色卡' })).toBeInTheDocument()
    expect(screen.getByAltText('林探员的人物图片')).toHaveAttribute('src', 'blob:portrait-1')
    expect(screen.getByText('事务所侦探')).toBeInTheDocument()
    expect(screen.getByText('尚未开始建卡')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '从空白卡新建角色卡' })).toBeEnabled()
  })

  it('navigates home, opens a card, and protects creation from duplicate clicks', async () => {
    renderPage()
    await screen.findByRole('button', { name: '打开 林探员 的角色卡' })

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home')

    cleanup()
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '打开 林探员 的角色卡' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/home/characters/template-1')

    cleanup()
    renderPage()
    const createButton = await screen.findByRole('button', { name: '从空白卡新建角色卡' })
    let resolveCreate: ((template: CharacterTemplate) => void) | undefined
    vi.mocked(createCharacterTemplate).mockImplementation(
      () => new Promise((resolve) => { resolveCreate = resolve }),
    )
    fireEvent.click(createButton)
    fireEvent.click(createButton)
    expect(createCharacterTemplate).toHaveBeenCalledTimes(1)
    resolveCreate?.({ ...templates[0], templateId: 'template-new' })
  })

  it('confirms deletion and keeps the card when deletion fails', async () => {
    renderPage()
    const deleteButton = await screen.findByRole('button', { name: '删除 林探员' })
    fireEvent.click(deleteButton)
    expect(screen.getByRole('group', { name: '确认删除 林探员' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(deleteCharacterTemplate).toHaveBeenCalledWith('template-1'))
    expect(screen.queryByRole('button', { name: '打开 林探员 的角色卡' })).not.toBeInTheDocument()

    vi.mocked(deleteCharacterTemplate).mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(await screen.findByRole('button', { name: '删除 未命名调查员' }))
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('删除角色卡失败')
    expect(screen.getByRole('button', { name: '打开 未命名调查员 的角色卡' })).toBeInTheDocument()
  })

  it('offers a retry after the initial list request fails', async () => {
    vi.mocked(listCharacterTemplates).mockRejectedValueOnce(new Error('offline'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('加载角色卡库失败')
    fireEvent.click(screen.getByRole('button', { name: '重试加载角色卡' }))
    expect(await screen.findByRole('button', { name: '打开 林探员 的角色卡' })).toBeInTheDocument()
    expect(listCharacterTemplates).toHaveBeenCalledTimes(2)
  })
})
