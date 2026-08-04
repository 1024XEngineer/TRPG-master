/**
 * 骰子多面体几何（issue #217，移植自本地 Three.js 原型）。
 *
 * 逐面构建而不是直接用内置几何体：每个面要贴一张独立的、带数字的贴图，
 * 所以必须先把「面」这个概念从三角形汤里还原出来。
 */
import { IcosahedronGeometry, Vector3, type BufferGeometry } from 'three'

import type { PolyhedronKind } from './types'

/** Newell 法求面法线：对凹凸不敏感，比取前三点叉积稳。 */
export function faceNormal(verts: Vector3[]): Vector3 {
  const n = new Vector3()
  for (let i = 0; i < verts.length; i += 1) {
    const a = verts[i]
    const b = verts[(i + 1) % verts.length]
    n.x += (a.y - b.y) * (a.z + b.z)
    n.y += (a.z - b.z) * (a.x + b.x)
    n.z += (a.x - b.x) * (a.y + b.y)
  }
  return n.normalize()
}

/** 从内置几何体里按三角形提取面（二十面体每面就是一个三角形）。 */
export function extractTriangleFaces(geom: BufferGeometry): Vector3[][] {
  const pos = geom.attributes.position.array
  const faces: Vector3[][] = []
  for (let i = 0; i < pos.length; i += 9) {
    faces.push([
      new Vector3(pos[i], pos[i + 1], pos[i + 2]),
      new Vector3(pos[i + 3], pos[i + 4], pos[i + 5]),
      new Vector3(pos[i + 6], pos[i + 7], pos[i + 8]),
    ])
  }
  return faces
}

/** 立方体六个面，顶点按面内顺序给出。 */
export function cubeFaces(): Vector3[][] {
  const v = (x: number, y: number, z: number) => new Vector3(x, y, z)
  return [
    [v(-1, 1, -1), v(-1, 1, 1), v(1, 1, 1), v(1, 1, -1)], // 顶
    [v(-1, -1, -1), v(1, -1, -1), v(1, -1, 1), v(-1, -1, 1)], // 底
    [v(-1, -1, 1), v(1, -1, 1), v(1, 1, 1), v(-1, 1, 1)], // 前
    [v(1, -1, -1), v(-1, -1, -1), v(-1, 1, -1), v(1, 1, -1)], // 后
    [v(1, -1, 1), v(1, -1, -1), v(1, 1, -1), v(1, 1, 1)], // 右
    [v(-1, -1, -1), v(-1, -1, 1), v(-1, 1, 1), v(-1, 1, -1)], // 左
  ]
}

/**
 * 五角偏方面体——真实 D10 的形状，three 没有内置，手写。
 *
 * 上下各 5 个风筝形面：两圈交错的腰顶点（A/B，相位差 36°）分别与上下极点围成面。
 */
export function trapezohedronFaces(): Vector3[][] {
  const waistY = 0.42
  const apexY = 1.28
  const radius = 1
  const upper: Vector3[] = []
  const lower: Vector3[] = []
  for (let i = 0; i < 5; i += 1) {
    const a1 = ((i * 72) * Math.PI) / 180
    const a2 = ((i * 72 + 36) * Math.PI) / 180
    upper.push(new Vector3(Math.cos(a1) * radius, waistY, Math.sin(a1) * radius))
    lower.push(new Vector3(Math.cos(a2) * radius, -waistY, Math.sin(a2) * radius))
  }
  const top = new Vector3(0, apexY, 0)
  const bottom = new Vector3(0, -apexY, 0)
  const faces: Vector3[][] = []
  for (let j = 0; j < 5; j += 1) {
    const n = (j + 1) % 5
    faces.push([top, upper[j], lower[j], upper[n]])
    faces.push([bottom, lower[n], upper[n], lower[j]])
  }
  return faces
}

export function polyhedronFaces(kind: PolyhedronKind): Vector3[][] {
  switch (kind) {
    case 'd6':
      return cubeFaces()
    case 'd10':
      return trapezohedronFaces()
    case 'd20':
      return extractTriangleFaces(new IcosahedronGeometry(1.15))
  }
}
