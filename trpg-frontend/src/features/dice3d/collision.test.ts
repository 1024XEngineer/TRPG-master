import { describe, expect, it } from 'vitest'

import { resolveSphereCollision, separatePlanarTargets, type CollisionBody } from './collision'

function body(
  position: [number, number, number],
  velocity: [number, number, number] = [0, 0, 0],
): CollisionBody {
  return {
    position: { x: position[0], y: position[1], z: position[2] },
    velocity: { x: velocity[0], y: velocity[1], z: velocity[2] },
    radius: 1,
  }
}

describe('resolveSphereCollision', () => {
  it('separates overlapping dice and reflects their closing velocity', () => {
    const first = body([0, 0, 0], [1, 0, 0])
    const second = body([1.5, 0, 0], [-1, 0, 0])

    expect(resolveSphereCollision(first, second)).toBe(true)
    expect(
      Math.hypot(
        second.position.x - first.position.x,
        second.position.y - first.position.y,
        second.position.z - first.position.z,
      ),
    ).toBeCloseTo(2)
    expect(first.velocity.x).toBeLessThan(0)
    expect(second.velocity.x).toBeGreaterThan(0)
  })

  it('uses a stable finite direction when both centers coincide', () => {
    const first = body([0, 0, 0])
    const second = body([0, 0, 0])

    expect(resolveSphereCollision(first, second)).toBe(true)
    expect(first.position.x).toBe(-1)
    expect(second.position.x).toBe(1)
    expect(Object.values(first.position).every(Number.isFinite)).toBe(true)
    expect(Object.values(second.position).every(Number.isFinite)).toBe(true)
  })

  it('leaves separated dice unchanged', () => {
    const first = body([-2, 0, 0], [1, 0, 0])
    const second = body([2, 0, 0], [-1, 0, 0])

    expect(resolveSphereCollision(first, second)).toBe(false)
    expect(first.position).toEqual({ x: -2, y: 0, z: 0 })
    expect(second.position).toEqual({ x: 2, y: 0, z: 0 })
  })
})

describe('separatePlanarTargets', () => {
  it('lays overlapping percentile dice out left-to-right within the arena', () => {
    const [first, second] = separatePlanarTargets(
      { x: 2.7, z: 1.4 },
      { x: 2.8, z: 1.3 },
      2.2,
      { halfX: 2.65, halfZ: 1.1 },
    )

    expect(Math.hypot(second.x - first.x, second.z - first.z)).toBeCloseTo(2.2)
    expect(first.x).toBeGreaterThanOrEqual(-2.65)
    expect(second.x).toBeLessThanOrEqual(2.65)
    expect(first.z).toBe(1.1)
    expect(second.z).toBe(1.1)
  })

  it('preserves already separated natural targets', () => {
    expect(
      separatePlanarTargets(
        { x: -1.5, z: -0.2 },
        { x: 1.5, z: 0.3 },
        2.2,
        { halfX: 2.65, halfZ: 1.1 },
      ),
    ).toEqual([
      { x: -1.5, z: -0.2 },
      { x: 1.5, z: 0.3 },
    ])
  })
})
