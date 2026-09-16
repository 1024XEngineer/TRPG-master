import { Group, Mesh, Quaternion, Texture, Vector3, type MeshPhysicalMaterial, type Scene } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createDiceStage, type DiceStage } from './engine'
import { faceNormal, polyhedronFaces } from './geometry'
import type { DiceKind } from './types'

const { rendered } = vi.hoisted(() => ({ rendered: vi.fn() }))

// Only the GPU and canvas texture drawing are stubbed: geometry, physics,
// quaternions, scene meshes and the animation loop all run unchanged.
vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof import('three')>()
  return {
    ...actual,
    WebGLRenderer: class {
      domElement = document.createElement('canvas')
      shadowMap = {}
      setPixelRatio() {}
      setSize() {}
      render = rendered
      dispose() {}
      forceContextLoss() {}
    },
  }
})

vi.mock('./textures', async (importOriginal) => ({
  ...await importOriginal<typeof import('./textures')>(),
  makeFaceTexture: (_palette: unknown, label: string, _uv: unknown, pips?: number) => {
    const texture = new Texture()
    texture.userData = { label, value: pips ?? Number(label) }
    return texture
  },
}))

interface FrameDie {
  position: Vector3
  quaternion: Quaternion
  maps: Texture[]
}

let now = 0
let raf: FrameRequestCallback | null = null
let frames: FrameDie[][] = []
let stages: DiceStage[] = []

function seedRandom(seed: number) {
  let state = seed
  vi.spyOn(Math, 'random').mockImplementation(() => {
    state = (1664525 * state + 1013904223) >>> 0
    return state / 2 ** 32
  })
}

function tick(ms = 1000 / 60) {
  now += ms
  const callback = raf
  raf = null
  callback?.(now)
}

function newStage(kind: DiceKind, onSettled = vi.fn(), onContextLost = vi.fn()) {
  const container = document.createElement('div')
  const stage = createDiceStage({ container, kind, onSettled, onContextLost })
  stages.push(stage)
  return { stage, container, onSettled, onContextLost }
}

function roll(kind: DiceKind, target?: number, seed = 535, frameMs = 1000 / 60) {
  seedRandom(seed)
  now = 0
  frames = []
  const { stage, onSettled } = newStage(kind)
  expect(stage.roll(target)).toBe(true)
  expect(onSettled).not.toHaveBeenCalled()
  const randomCalls = vi.mocked(Math.random).mock.calls.length
  for (let i = 0; i < 1000 && onSettled.mock.calls.length === 0; i += 1) tick(frameMs)
  expect(onSettled).toHaveBeenCalledTimes(1)
  expect(vi.mocked(Math.random).mock.calls.length).toBe(randomCalls)
  const resultFrames = frames.slice()
  tick(frameMs)
  expect(onSettled).toHaveBeenCalledTimes(1)
  stage.dispose()
  return { frames: resultFrames, value: onSettled.mock.calls[0][0] as number }
}

function topFace(kind: DiceKind, die: FrameDie) {
  const normals = polyhedronFaces(kind === 'd100' ? 'd10' : kind).map((vertices) => {
    const normal = faceNormal(vertices)
    if (normal.dot(vertices[0]) < 0) normal.negate()
    return normal.applyQuaternion(die.quaternion)
  })
  const index = normals.reduce((best, normal, i) => normal.y > normals[best].y ? i : best, 0)
  return { index, normal: normals[index], value: die.maps[index].userData.value as number }
}

beforeEach(() => {
  now = 0
  raf = null
  frames = []
  stages = []
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    raf = callback
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', () => { raf = null })
  rendered.mockImplementation((scene: Scene) => {
    frames.push(scene.children.filter((child): child is Group => child instanceof Group).map((group) => ({
      position: group.position.clone(),
      quaternion: group.quaternion.clone(),
      maps: group.children.filter((child): child is Mesh => child instanceof Mesh)
        .map((mesh) => (mesh.material as MeshPhysicalMaterial).map).filter((map): map is Texture => map !== null),
    })))
  })
})

afterEach(() => {
  stages.forEach((stage) => stage.dispose())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('dice trajectory and visible results', () => {
  it.each(['d6', 'd20', 'd100'] as const)('shows every authoritative %s result with fixed face textures', (kind) => {
    const sides = kind === 'd100' ? 100 : kind === 'd20' ? 20 : 6
    for (let target = 1; target <= sides; target += 1) {
      const result = roll(kind, target, target * 535, 1000 / 30)
      const first = result.frames[0]
      const last = result.frames.at(-1)!
      const values = last.map((die) => topFace(kind, die).value)
      expect(result.value).toBe(target)
      expect(kind === 'd100' ? (values[0] + values[1] || 100) : values[0]).toBe(target)
      last.forEach((die) => expect(topFace(kind, die).normal.y).toBeCloseTo(1, 6))
      for (const frame of result.frames) {
        frame.forEach((die, index) => {
          expect(die.maps).toEqual(first[index].maps)
          expect(new Set(die.maps.map((map) => map.userData.value)).size).toBe(die.maps.length)
        })
      }
    }
  })

  it.each(['d6', 'd20', 'd100'] as const)('keeps the same %s motion for free rolls and different requested results', (kind) => {
    const reference = roll(kind)
    for (const target of [1, kind === 'd100' ? 100 : kind === 'd20' ? 20 : 6]) {
      const result = roll(kind, target)
      expect(result.frames.length).toBe(reference.frames.length)
      result.frames.forEach((frame, i) => frame.forEach((die, j) => {
        expect(die.position.distanceTo(reference.frames[i][j].position)).toBeLessThan(1e-10)
        expect(Math.abs(die.quaternion.dot(reference.frames[i][j].quaternion))).toBeCloseTo(1, 10)
      }))
    }
    const values = reference.frames.at(-1)!.map((die) => topFace(kind, die).value)
    expect(reference.value).toBe(kind === 'd100' ? (values[0] + values[1] || 100) : values[0])
  })

  it.each(['d6', 'd20', 'd100'] as const)('settles %s by the shortest tilt without changing the upper face or resetting yaw', (kind) => {
    for (const seed of [1, 42, 535, 2026]) {
      const result = roll(kind, 1, seed)
      // The last 0.5s is wholly within the 0.55s settling phase.
      const settling = result.frames.slice(-30)
      const last = settling.at(-1)!
      settling.forEach((frame) => frame.forEach((die, index) => {
        const top = topFace(kind, die)
        expect(top.index).toBe(topFace(kind, last[index]).index)
        const expectedTilt = Math.acos(Math.min(1, top.normal.y))
        expect(die.quaternion.angleTo(last[index].quaternion)).toBeCloseTo(expectedTilt, 5)
      }))
      // Smooth easing must not snap when entering/leaving the settled pose.
      for (let i = 1; i < settling.length; i += 1) {
        settling[i].forEach((die, j) => {
          expect(die.quaternion.angleTo(settling[i - 1][j].quaternion)).toBeLessThan(0.09)
          expect(die.position.distanceTo(settling[i - 1][j].position)).toBeLessThan(0.1)
        })
      }
    }
  })

  it.each([1000 / 30, 1000 / 60, 1000 / 144, 250])('preserves the planned landing at a %sms frame interval', (frameMs) => {
    const result = roll('d100', 100, 535, frameMs)
    expect(result.value).toBe(100)
    expect(result.frames.at(-1)!.map((die) => topFace('d100', die).value)).toEqual([0, 0])
    expect(result.frames.at(-1)![0].maps.some((map) => map.userData.label === '00')).toBe(true)
  })

  it('handles a first rAF timestamp slightly earlier than roll preparation without reading a negative sample', () => {
    seedRandom(535)
    const { stage, onSettled } = newStage('d100')
    stage.roll(23)
    tick(-5)
    expect(frames[0]).toHaveLength(2)
    expect(frames[0].every((die) => die.position.y > 3)).toBe(true)
    for (let i = 0; i < 400; i += 1) tick()
    expect(onSettled).toHaveBeenCalledExactlyOnceWith(23)
  })

  it('rejects overlapping rolls and can roll again after completing or changing kind', () => {
    seedRandom(535)
    const { stage, onSettled } = newStage('d100')
    expect(stage.roll(100)).toBe(true)
    expect(stage.roll(1)).toBe(false)
    for (let i = 0; i < 400; i += 1) tick()
    expect(onSettled).toHaveBeenCalledExactlyOnceWith(100)
    expect(stage.roll(23)).toBe(true)
    tick()
    stage.setKind('d6')
    expect(stage.roll(6)).toBe(true)
    for (let i = 0; i < 400; i += 1) tick()
    expect(onSettled.mock.calls.map(([value]) => value)).toEqual([100, 6])
  })

  it.each(['dispose', 'context loss'] as const)('does not complete a recorded roll after %s', (interruption) => {
    seedRandom(535)
    const { stage, container, onSettled, onContextLost } = newStage('d100')
    stage.roll(100)
    tick()
    if (interruption === 'dispose') stage.dispose()
    else container.querySelector('canvas')!.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
    for (let i = 0; i < 400; i += 1) tick()
    expect(onSettled).not.toHaveBeenCalled()
    expect(stage.roll(1)).toBe(false)
    expect(onContextLost).toHaveBeenCalledTimes(interruption === 'context loss' ? 1 : 0)
  })
})
