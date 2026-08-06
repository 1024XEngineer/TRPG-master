import { afterEach, describe, expect, it, vi } from 'vitest'

import { isWebGLAvailable, prefersReducedMotion, supports3DDice } from './support'

afterEach(() => {
  vi.restoreAllMocks()
  Reflect.deleteProperty(window, 'matchMedia')
})

describe('3D 骰子可用性探测', () => {
  it('取不到 WebGL context 时判定不可用', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)

    expect(isWebGLAvailable()).toBe(false)
    expect(supports3DDice()).toBe(false)
  })

  it('取 context 抛异常时也判定不可用，而不是让异常冒出去', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
      throw new Error('WebGL blocked')
    })

    expect(() => isWebGLAvailable()).not.toThrow()
    expect(isWebGLAvailable()).toBe(false)
  })

  it('用户要求减少动效时不走 3D，即使 WebGL 可用', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
      {} as unknown as RenderingContext,
    )
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (query: string) => ({ matches: query.includes('reduce') }) as MediaQueryList,
    })

    expect(isWebGLAvailable()).toBe(true)
    expect(prefersReducedMotion()).toBe(true)
    expect(supports3DDice()).toBe(false)
  })

  it('没有 matchMedia 的环境按"不要求减少动效"处理', () => {
    expect(prefersReducedMotion()).toBe(false)
  })
})
