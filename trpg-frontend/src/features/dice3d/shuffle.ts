/**
 * Fisher–Yates 均匀洗牌（issue #217）。
 *
 * 为什么必须是均匀的：3D 骰子的结果取自「物理停下后朝上的那一面」，而点数是在
 * 掷骰前被洗到各个面上的。设物理落面为 F（分布可能有偏），面→点数的映射为独立
 * 的随机排列 V，则 P(V[F] = v) = 1/n 对任意 v 成立**当且仅当** V 是均匀排列。
 * 也就是说，结果的均匀性完全由这里保证，与物理是否有偏无关。
 *
 * 原型里用的是 `arr.sort(() => Math.random() - 0.5)`，那不是均匀排列——比较器
 * 返回随机值时，排序结果取决于具体排序算法的比较顺序，元素明显倾向于留在原位。
 * 对判定成败的检定骰来说这是正确性问题，不是风格问题。
 */
export function shuffle<T>(items: readonly T[], random: () => number = Math.random): T[] {
  const out = items.slice()
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1))
    const tmp = out[i]
    out[i] = out[j]
    out[j] = tmp
  }
  return out
}
