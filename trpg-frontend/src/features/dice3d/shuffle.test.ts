import { describe, expect, it } from 'vitest'

import { shuffle } from './shuffle'

/** 可复现的 LCG，避免用 Math.random 让统计断言变成 flaky 测试。 */
function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0x100000000
  }
}

describe('shuffle', () => {
  it('返回原集合的一个排列，且不改动入参', () => {
    const input = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
    const snapshot = [...input]

    const out = shuffle(input, seededRandom(1))

    expect(out).toHaveLength(input.length)
    expect([...out].sort((a, b) => a - b)).toEqual(snapshot)
    expect(input).toEqual(snapshot)
  })

  it('空数组与单元素数组不出错', () => {
    expect(shuffle([])).toEqual([])
    expect(shuffle([7])).toEqual([7])
  })

  /**
   * 这条是 issue #217 的硬性验收点。
   *
   * 3D 骰子的结果 = 物理停下后朝上那一面所带的点数，所以结果分布**完全**取决于
   * 「点数→面」这个排列是否均匀。原型里用的 `sort(() => Math.random() - 0.5)`
   * 不是均匀排列，会让检定骰的点数分布偏斜。
   */
  it('每个点数落到每个位置的频率都接近均匀', () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    const trials = 20000
    const random = seededRandom(20260804)
    // counts[position][value] = 出现次数
    const counts = Array.from({ length: values.length }, () =>
      new Array<number>(values.length).fill(0),
    )

    for (let t = 0; t < trials; t += 1) {
      const out = shuffle(values, random)
      out.forEach((value, position) => {
        counts[position][values.indexOf(value)] += 1
      })
    }

    const expected = trials / values.length
    // ±8% 相对偏差：均匀洗牌在 2 万次下远低于此，有偏洗牌（元素倾向留在原位）
    // 在对角线上会超出一大截。
    const tolerance = expected * 0.08
    for (const row of counts) {
      for (const observed of row) {
        expect(Math.abs(observed - expected)).toBeLessThan(tolerance)
      }
    }
  })
})
