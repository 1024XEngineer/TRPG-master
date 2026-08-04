/**
 * 程序化骰面贴图（issue #217，移植自本地 Three.js 原型）。
 *
 * 每个面一张 Canvas 贴图：大理石纹底 + 棱线 + 凹刻数字（D6 用点数）。
 * 走程序化而不是美术图，是为了不往仓库塞二进制资源，也方便按骰型换配色。
 */
import { CanvasTexture, SRGBColorSpace } from 'three'

export interface Palette {
  /** 底色 */
  base: string
  /** 浅色纹理，"r,g,b" */
  light: string
  /** 深色纹理，"r,g,b" */
  dark: string
}

export const PALETTES = {
  d6: { base: '#6e7d8f', light: '200,215,230', dark: '22,30,40' },
  d20: { base: '#157a55', light: '120,230,190', dark: '2,40,26' },
  /** D100 十位骰 */
  d100tens: { base: '#96231a', light: '255,150,130', dark: '48,6,4' },
  /** D100 个位骰 */
  d100units: { base: '#c04331', light: '255,180,160', dark: '70,14,8' },
} as const satisfies Record<string, Palette>

export type PaletteKey = keyof typeof PALETTES

const SIZE = 256

/** D6 的点数面。 */
function drawPips(ctx: CanvasRenderingContext2D, cx: number, cy: number, count: number): void {
  const off = SIZE * 0.16
  const r = SIZE * 0.055
  const layouts: Record<number, [number, number][]> = {
    1: [[0, 0]],
    2: [[-1, -1], [1, 1]],
    3: [[-1, -1], [0, 0], [1, 1]],
    4: [[-1, -1], [1, -1], [-1, 1], [1, 1]],
    5: [[-1, -1], [1, -1], [0, 0], [-1, 1], [1, 1]],
    6: [[-1, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [1, 1]],
  }
  const spots = layouts[count] ?? layouts[1]
  for (const [sx, sy] of spots) {
    const px = cx + sx * off
    const py = cy + sy * off
    // 先画错位的深色再画白色，做出凹刻的错觉。
    ctx.beginPath()
    ctx.arc(px, py + 2, r, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(0,0,0,0.5)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(px, py, r, 0, Math.PI * 2)
    ctx.fillStyle = '#f4f6f2'
    ctx.fill()
  }
}

/**
 * 生成一张骰面贴图。
 *
 * @param uvPoly 该面在贴图空间里的多边形轮廓（0–1），用来画棱线并定位数字。
 * @param pips   传了就画点数（D6），否则画 label 数字。
 */
export function makeFaceTexture(
  palette: Palette,
  label: string,
  uvPoly: [number, number][],
  pips?: number,
): CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法获取 2D 绘图上下文，骰面贴图生成失败')

  ctx.fillStyle = palette.base
  ctx.fillRect(0, 0, SIZE, SIZE)

  // 大理石纹：十几块半透明模糊椭圆叠出来的随机纹理。
  for (let i = 0; i < 12; i += 1) {
    const tint = i % 2 === 0 ? palette.light : palette.dark
    ctx.fillStyle = `rgba(${tint},${(0.1 + Math.random() * 0.14).toFixed(2)})`
    // filter 在个别浏览器不支持，纹理会略平，不影响可用性。
    try {
      ctx.filter = `blur(${SIZE / 16}px)`
    } catch {
      ctx.filter = 'none'
    }
    ctx.beginPath()
    ctx.ellipse(
      Math.random() * SIZE,
      Math.random() * SIZE,
      SIZE * (0.14 + Math.random() * 0.3),
      SIZE * (0.06 + Math.random() * 0.18),
      Math.random() * Math.PI,
      0,
      Math.PI * 2,
    )
    ctx.fill()
  }
  try {
    ctx.filter = 'none'
  } catch {
    // 同上，忽略。
  }

  // 左上柔光。
  const grad = ctx.createRadialGradient(
    SIZE * 0.3, SIZE * 0.24, SIZE * 0.05,
    SIZE * 0.3, SIZE * 0.24, SIZE * 0.9,
  )
  grad.addColorStop(0, 'rgba(255,255,255,0.16)')
  grad.addColorStop(0.5, 'rgba(255,255,255,0.02)')
  grad.addColorStop(1, 'rgba(0,0,0,0.20)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, SIZE, SIZE)

  const tracePoly = () => {
    ctx.beginPath()
    uvPoly.forEach(([ux, uy], idx) => {
      const px = ux * SIZE
      const py = (1 - uy) * SIZE
      if (idx === 0) ctx.moveTo(px, py)
      else ctx.lineTo(px, py)
    })
    ctx.closePath()
  }

  // 棱线：外圈暗、内圈亮。
  ctx.lineJoin = 'round'
  tracePoly()
  ctx.strokeStyle = 'rgba(0,0,0,0.32)'
  ctx.lineWidth = SIZE * 0.05
  ctx.stroke()
  tracePoly()
  ctx.strokeStyle = 'rgba(255,255,255,0.10)'
  ctx.lineWidth = SIZE * 0.02
  ctx.stroke()

  // 质心 = 数字落点。
  let cx = 0
  let cy = 0
  for (const [ux, uy] of uvPoly) {
    cx += ux
    cy += uy
  }
  cx = (cx / uvPoly.length) * SIZE
  cy = (1 - cy / uvPoly.length) * SIZE

  if (pips !== undefined) {
    drawPips(ctx, cx, cy, pips)
  } else {
    const fontSize = SIZE * (label.length >= 2 ? 0.34 : 0.44)
    ctx.font = `900 ${fontSize}px Georgia, serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = 'rgba(0,0,0,0.5)'
    ctx.fillText(label, cx, cy + SIZE * 0.018)
    ctx.fillStyle = '#f4f6f2'
    ctx.fillText(label, cx, cy)
    // 6 和 9 加下划线——真实骰子的惯例，否则倒过来看会读错。
    if (label === '6' || label === '9') {
      const w = ctx.measureText(label).width
      ctx.fillStyle = 'rgba(0,0,0,0.5)'
      ctx.fillRect(cx - w * 0.32, cy + fontSize * 0.52 + 2, w * 0.64, SIZE * 0.02)
      ctx.fillStyle = '#f4f6f2'
      ctx.fillRect(cx - w * 0.32, cy + fontSize * 0.52, w * 0.64, SIZE * 0.02)
    }
  }

  const tex = new CanvasTexture(canvas)
  tex.anisotropy = 4
  // 原型用的是 r128 的 tex.encoding = sRGBEncoding，新版本改成了 colorSpace。
  tex.colorSpace = SRGBColorSpace
  return tex
}
