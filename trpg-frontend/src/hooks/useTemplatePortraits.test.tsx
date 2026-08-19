import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import type { CharacterTemplate } from '@/services/character/template-api'
import { getCharacterTemplatePortrait } from '@/services/character/template-api'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTemplatePortraits } from './useTemplatePortraits'

vi.mock('@/services/character/template-api', () => ({
  getCharacterTemplatePortrait: vi.fn(),
}))

const template = (version: string): CharacterTemplate => ({
  templateId: 'template-1',
  name: '陈探员',
  systemId: 'system-1',
  data: {},
  hasPortrait: true,
  portraitVersion: version,
  createdAt: '2026-08-18T00:00:00Z',
  updatedAt: '2026-08-18T00:00:00Z',
})

describe('useTemplatePortraits', () => {
  const createObjectURL = vi.fn<(blob: Blob) => string>()
  const revokeObjectURL = vi.fn<(url: string) => void>()

  beforeEach(() => {
    vi.mocked(getCharacterTemplatePortrait).mockReset()
    createObjectURL.mockReset()
    revokeObjectURL.mockReset()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('按版本加载头像，更新和卸载时释放 Object URL', async () => {
    vi.mocked(getCharacterTemplatePortrait)
      .mockResolvedValueOnce(new Blob(['one'], { type: 'image/png' }))
      .mockResolvedValueOnce(new Blob(['two'], { type: 'image/png' }))
    createObjectURL.mockReturnValueOnce('blob:one').mockReturnValueOnce('blob:two')
    const firstTemplates = [template('version-1')]
    const { result, rerender, unmount } = renderHook(
      ({ templates }) => useTemplatePortraits(templates),
      { initialProps: { templates: firstTemplates } },
    )

    await waitFor(() => expect(result.current['template-1']).toBe('blob:one'))
    rerender({ templates: firstTemplates })
    expect(getCharacterTemplatePortrait).toHaveBeenCalledTimes(1)

    await act(async () => rerender({ templates: [template('version-2')] }))
    await waitFor(() => expect(result.current['template-1']).toBe('blob:two'))
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:one')

    unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:two')
  })

  it('加载失败时保留占位状态且不抛出错误', async () => {
    vi.mocked(getCharacterTemplatePortrait).mockRejectedValue(new TypeError('offline'))
    const { result } = renderHook(() => useTemplatePortraits([template('version-1')]))

    await waitFor(() => expect(getCharacterTemplatePortrait).toHaveBeenCalledOnce())
    expect(result.current).toEqual({})
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it('请求未完成时模板被移除，不会让旧响应重新写回头像', async () => {
    let resolvePortrait: ((blob: Blob) => void) | undefined
    vi.mocked(getCharacterTemplatePortrait).mockImplementation(
      () => new Promise((resolve) => { resolvePortrait = resolve }),
    )
    const { result, rerender } = renderHook(
      ({ templates }) => useTemplatePortraits(templates),
      { initialProps: { templates: [template('version-1')] } },
    )
    await waitFor(() => expect(getCharacterTemplatePortrait).toHaveBeenCalledOnce())
    const signal = vi.mocked(getCharacterTemplatePortrait).mock.calls[0]?.[2]

    await act(async () => rerender({ templates: [] }))
    expect(signal?.aborted).toBe(true)

    await act(async () => {
      resolvePortrait?.(new Blob(['stale'], { type: 'image/png' }))
      await Promise.resolve()
    })
    expect(result.current).toEqual({})
    expect(createObjectURL).not.toHaveBeenCalled()
  })
})
