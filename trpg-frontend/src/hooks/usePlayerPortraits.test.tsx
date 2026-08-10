/** 验证持久化头像 Hook 的请求去重、版本替换和 Object URL 生命周期。 */
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import type { RoomPlayerSummary } from 'trpg-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sdk } from '@/services/api-client'
import { usePlayerPortraits } from './usePlayerPortraits'

vi.mock('@/services/api-client', () => ({
  sdk: { characters: { getPlayerPortrait: vi.fn() } },
}))

const player = (version: string): RoomPlayerSummary => ({
  playerId: 'player-1',
  nickname: '玩家一',
  isHost: false,
  ready: true,
  hasCharacter: true,
  hasPortrait: true,
  portraitVersion: version,
})

describe('usePlayerPortraits', () => {
  const createObjectURL = vi.fn<(blob: Blob) => string>()
  const revokeObjectURL = vi.fn<(url: string) => void>()

  beforeEach(() => {
    vi.mocked(sdk.characters.getPlayerPortrait).mockReset()
    createObjectURL.mockReset()
    revokeObjectURL.mockReset()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('按版本请求一次，版本变化后替换并在卸载时释放 URL', async () => {
    vi.mocked(sdk.characters.getPlayerPortrait)
      .mockResolvedValueOnce(new Blob(['one'], { type: 'image/png' }))
      .mockResolvedValueOnce(new Blob(['two'], { type: 'image/png' }))
    createObjectURL.mockReturnValueOnce('blob:one').mockReturnValueOnce('blob:two')
    const firstPlayers = [player('version-1')]
    const { result, rerender, unmount } = renderHook(
      ({ players }) => usePlayerPortraits('room-1', 'token-1', players),
      { initialProps: { players: firstPlayers } },
    )

    await waitFor(() => expect(result.current['player-1']).toBe('blob:one'))
    rerender({ players: firstPlayers })
    expect(sdk.characters.getPlayerPortrait).toHaveBeenCalledTimes(1)

    await act(async () => rerender({ players: [player('version-2')] }))
    await waitFor(() => expect(result.current['player-1']).toBe('blob:two'))
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:one')

    unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:two')
  })
})
