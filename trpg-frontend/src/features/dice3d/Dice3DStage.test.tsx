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
  mockStageRoll: vi.fn((): boolean => true),
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
    // 贴着真实引擎的行为建模：context 一丢，这个舞台就永久拒绝后续掷骰
    // （engine.ts 的 `roll()` 里 `if (disposed || contextLost) return false`）。
    // 之前 mock 的 roll 恒为 true，于是「丢失后还能继续掷」这条断言是假绿的。
    let contextLost = false
    const entry = {
      onSettled,
      onContextLost: () => {
        contextLost = true
        onContextLost?.()
      },
    }
    createdStages.push(entry)
    return {
      roll: () => (contextLost ? false : mockStageRoll()),
      dispose: mockDispose,
      setKind: mockSetKind,
    }
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

    // 丢失的 context 救不回来，必须换一个新舞台，否则之后每次掷骰都被静默拒绝
    // ——玩家点「掷骰」按钮，rolling 清掉了，什么都没发生（#324 review 指出）。
    await waitFor(() => expect(createdStages).toHaveLength(2))
    expect(mockDispose).toHaveBeenCalled()

    expect(ref.current?.roll('check-b:2')).toBe(true)
    act(() => createdStages[1].onSettled(41))
    expect(onSettled).toHaveBeenCalledWith(41, 'check-b:2')
    expect(onUnsupported).not.toHaveBeenCalled()
  })

  // 换新舞台也救不回来时（GPU 反复崩），不能无限重建：有限次之后老实退回 2D。
  it('gives up on 3D after repeated context losses instead of rebuilding forever', async () => {
    const ref = createRef<Dice3DHandle>()
    const onUnsupported = vi.fn()
    render(
      <Dice3DStage
        ref={ref}
        kind="d100"
        onSettled={vi.fn()}
        onUnsupported={onUnsupported}
        onRollAbandoned={vi.fn()}
      />,
    )
    await waitFor(() => expect(createdStages).toHaveLength(1))

    for (let i = 0; i < 5; i += 1) {
      const stage = createdStages.at(-1)
      act(() => stage?.onContextLost?.())
      await waitFor(() => expect(onUnsupported.mock.calls.length + createdStages.length).toBeGreaterThan(i + 1))
      if (onUnsupported.mock.calls.length > 0) break
    }

    expect(onUnsupported).toHaveBeenCalled()
    expect(createdStages.length).toBeLessThanOrEqual(4)
    expect(ref.current?.roll('check-after-giveup:1')).toBe(false)
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
