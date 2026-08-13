import { createRef } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Dice3DStage, type Dice3DHandle } from './Dice3DStage'

const { createdStages, mockDispose, mockStageRoll, mockSetKind } = vi.hoisted(() => ({
  createdStages: [] as Array<{
    onSettled: (value: number) => void
    onContextLost?: () => void
  }>,
  mockDispose: vi.fn(),
  mockStageRoll: vi.fn(() => true),
  mockSetKind: vi.fn(),
}))

vi.mock('./support', () => ({
  supports3DDice: () => true,
}))

vi.mock('./engine', () => ({
  createDiceStage: ({
    onSettled,
    onContextLost,
  }: {
    onSettled: (value: number) => void
    onContextLost?: () => void
  }) => {
    createdStages.push({ onSettled, onContextLost })
    return { roll: mockStageRoll, dispose: mockDispose, setKind: mockSetKind }
  },
}))

describe('Dice3DStage', () => {
  beforeEach(() => {
    createdStages.length = 0
    mockDispose.mockReset()
    mockSetKind.mockReset()
    mockStageRoll.mockReset()
    mockStageRoll.mockReturnValue(true)
  })

  afterEach(cleanup)

  it('returns the accepted roll token when the physical animation settles', async () => {
    const ref = createRef<Dice3DHandle>()
    const onSettled = vi.fn()
    render(<Dice3DStage ref={ref} kind="d100" onSettled={onSettled} />)
    await waitFor(() => expect(createdStages).toHaveLength(1))

    expect(ref.current?.roll('check-a:1')).toBe(true)
    expect(mockStageRoll).toHaveBeenCalledTimes(1)
    expect(ref.current?.roll('check-b:2')).toBe(false)

    act(() => createdStages[0].onSettled(23))
    expect(onSettled).toHaveBeenCalledWith(23, 'check-a:1')

    expect(ref.current?.roll('check-b:2')).toBe(true)
    act(() => createdStages[0].onSettled(41))
    expect(onSettled).toHaveBeenLastCalledWith(41, 'check-b:2')
  })

  it('drops the active token when the stage is unmounted', async () => {
    const ref = createRef<Dice3DHandle>()
    const onSettled = vi.fn()
    const view = render(<Dice3DStage ref={ref} kind="d100" onSettled={onSettled} />)
    await waitFor(() => expect(createdStages).toHaveLength(1))

    expect(ref.current?.roll('check-a:1')).toBe(true)
    view.unmount()
    expect(mockDispose).toHaveBeenCalledTimes(1)

    act(() => createdStages[0].onSettled(23))
    expect(onSettled).not.toHaveBeenCalled()
  })

  // 浏览器回收 context、GPU 进程重启都是可恢复的偶发事件。走 onRollAbandoned
  // 是为了只丢掉这一次掷骰——用 onUnsupported 会把 use3D 永久翻成 false，之后
  // 每次检定都只剩数字版（issue #320）。
  it('abandons only the current roll when the WebGL context is lost', async () => {
    const ref = createRef<Dice3DHandle>()
    const onSettled = vi.fn()
    const onUnsupported = vi.fn()
    const onRollAbandoned = vi.fn()
    render(
      <Dice3DStage
        ref={ref}
        kind="d100"
        onSettled={onSettled}
        onUnsupported={onUnsupported}
        onRollAbandoned={onRollAbandoned}
      />,
    )
    await waitFor(() => expect(createdStages).toHaveLength(1))

    expect(ref.current?.roll('check-a:1')).toBe(true)
    act(() => createdStages[0].onContextLost?.())

    expect(onRollAbandoned).toHaveBeenCalledWith('check-a:1')
    expect(onUnsupported).not.toHaveBeenCalled()

    // 这一次被放弃后，槽位要腾出来，下一次检定还能继续用 3D。
    expect(ref.current?.roll('check-b:2')).toBe(true)
  })

  // 每重建一次舞台就多一个 WebGLRenderer，顶穿浏览器的 context 上限。切骰型
  // 只该换骰子，renderer / 相机 / 光照 / 地面都不用动（issue #320）。
  it('reuses the stage across dice kinds instead of rebuilding the renderer', async () => {
    const ref = createRef<Dice3DHandle>()
    const onRollAbandoned = vi.fn()
    const view = render(
      <Dice3DStage
        ref={ref}
        kind="d100"
        onSettled={vi.fn()}
        onRollAbandoned={onRollAbandoned}
      />,
    )
    await waitFor(() => expect(createdStages).toHaveLength(1))

    expect(ref.current?.roll('check-a:1')).toBe(true)
    view.rerender(
      <Dice3DStage
        ref={ref}
        kind="d20"
        onSettled={vi.fn()}
        onRollAbandoned={onRollAbandoned}
      />,
    )

    expect(mockSetKind).toHaveBeenCalledWith('d20')
    expect(createdStages).toHaveLength(1)
    expect(mockDispose).not.toHaveBeenCalled()
    // 换型丢掉了上一副骰子，那次掷骰要按「这一次没了」交还，否则 rolling 不清。
    expect(onRollAbandoned).toHaveBeenCalledWith('check-a:1')
    expect(ref.current?.roll('check-b:2')).toBe(true)
  })
})
