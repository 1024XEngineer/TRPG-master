/** 验证后台生图弹窗的关闭、创建和终止交互。 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { PortraitGenerationTaskRead } from 'trpg-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createCharacterPortrait, cancelCharacterPortrait } from '@/services/character/portrait-api'
import { usePortraitGenerationStore } from '@/stores/portrait-generation-store'
import { PortraitGenerationModal } from './PortraitGenerationModal'

vi.mock('@/services/character/portrait-api', () => ({ createCharacterPortrait: vi.fn(), cancelCharacterPortrait: vi.fn() }))
const task = (status: PortraitGenerationTaskRead['status']): PortraitGenerationTaskRead => ({
  generationId: 'generation-1', status, cancelRequested: status === 'cancelling', style: 'realistic',
  size: '1024x1024', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
})
const props = { roomId: 'room-1', characterId: 'character-1', characterName: '陈探员', onClose: vi.fn() }

describe('PortraitGenerationModal', () => {
  beforeEach(() => { usePortraitGenerationStore.setState({ tasks: {}, cancelling: {}, notices: [], portraitVersions: {} }); vi.clearAllMocks() })
  afterEach(cleanup)

  it('创建接口返回后台任务快照', async () => {
    vi.mocked(createCharacterPortrait).mockResolvedValue(task('queued'))
    render(<PortraitGenerationModal {...props} />)
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '终止生成' })).toBeEnabled())
  })

  it('生成中仍可关闭弹窗且不会隐式取消', () => {
    usePortraitGenerationStore.getState().setTask('room-1', 'character-1', task('generating'))
    render(<PortraitGenerationModal {...props} />)
    expect(screen.getByText('关闭窗口不会终止任务，进入游戏后仍会继续生成')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭窗口，生成将在后台继续' }))
    expect(props.onClose).toHaveBeenCalledOnce()
    expect(cancelCharacterPortrait).not.toHaveBeenCalled()
  })

  it('遮罩和 Esc 也只关闭窗口，不终止生成', () => {
    usePortraitGenerationStore.getState().setTask('room-1', 'character-1', task('generating'))
    const { container } = render(<PortraitGenerationModal {...props} />)
    fireEvent.click(container.querySelector('[aria-hidden="true"]') as Element)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(props.onClose).toHaveBeenCalledTimes(2)
    expect(cancelCharacterPortrait).not.toHaveBeenCalled()
  })

  it('终止生成防止重复提交并显示终止中', async () => {
    usePortraitGenerationStore.getState().setTask('room-1', 'character-1', task('generating'))
    vi.mocked(cancelCharacterPortrait).mockResolvedValue(task('cancelling'))
    render(<PortraitGenerationModal {...props} />)
    fireEvent.click(screen.getByRole('button', { name: '终止生成' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '终止中…' })).toBeDisabled())
    expect(cancelCharacterPortrait).toHaveBeenCalledOnce()
  })
})
