import { createRef } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Dice3DStage, type Dice3DHandle } from './Dice3DStage'

const { createdStages, mockDispose, mockStageRoll } = vi.hoisted(() => ({
  createdStages: [] as Array<{ onSettled: (value: number) => void }>,
  mockDispose: vi.fn(),
  mockStageRoll: vi.fn(() => true),
}))

vi.mock('./support', () => ({
  supports3DDice: () => true,
}))

vi.mock('./engine', () => ({
  createDiceStage: ({ onSettled }: { onSettled: (value: number) => void }) => {
    createdStages.push({ onSettled })
    return { roll: mockStageRoll, dispose: mockDispose }
  },
}))

describe('Dice3DStage', () => {
  beforeEach(() => {
    createdStages.length = 0
    mockDispose.mockReset()
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
})
