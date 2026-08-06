export interface CollisionVector {
  x: number
  y: number
  z: number
}

export interface CollisionBody {
  position: CollisionVector
  velocity: CollisionVector
  radius: number
}

export interface PlanarPoint {
  x: number
  z: number
}

export interface PlanarBounds {
  halfX: number
  halfZ: number
}

const EPSILON = 1e-6

/** Resolve one equal-mass sphere collision in place. */
export function resolveSphereCollision(
  first: CollisionBody,
  second: CollisionBody,
  restitution = 0.32,
): boolean {
  let dx = second.position.x - first.position.x
  let dy = second.position.y - first.position.y
  let dz = second.position.z - first.position.z
  let distance = Math.hypot(dx, dy, dz)
  const minimumDistance = first.radius + second.radius

  if (distance >= minimumDistance) return false

  if (distance < EPSILON) {
    const relativeX = second.velocity.x - first.velocity.x
    const relativeY = second.velocity.y - first.velocity.y
    const relativeZ = second.velocity.z - first.velocity.z
    const relativeLength = Math.hypot(relativeX, relativeY, relativeZ)
    if (relativeLength >= EPSILON) {
      dx = -relativeX / relativeLength
      dy = -relativeY / relativeLength
      dz = -relativeZ / relativeLength
    } else {
      dx = 1
      dy = 0
      dz = 0
    }
    distance = 0
  } else {
    dx /= distance
    dy /= distance
    dz /= distance
  }

  const correction = (minimumDistance - distance) / 2
  first.position.x -= dx * correction
  first.position.y -= dy * correction
  first.position.z -= dz * correction
  second.position.x += dx * correction
  second.position.y += dy * correction
  second.position.z += dz * correction

  const relativeSpeed =
    (second.velocity.x - first.velocity.x) * dx +
    (second.velocity.y - first.velocity.y) * dy +
    (second.velocity.z - first.velocity.z) * dz

  if (relativeSpeed < 0) {
    const impulse = (-(1 + restitution) * relativeSpeed) / 2
    first.velocity.x -= impulse * dx
    first.velocity.y -= impulse * dy
    first.velocity.z -= impulse * dz
    second.velocity.x += impulse * dx
    second.velocity.y += impulse * dy
    second.velocity.z += impulse * dz
  }

  return true
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

/**
 * Preserve natural resting positions when possible. Overlapping D100 dice are
 * arranged left-to-right so both percentile faces remain readable.
 */
export function separatePlanarTargets(
  first: PlanarPoint,
  second: PlanarPoint,
  minimumDistance: number,
  bounds: PlanarBounds,
): [PlanarPoint, PlanarPoint] {
  const distance = Math.hypot(second.x - first.x, second.z - first.z)
  if (distance >= minimumDistance) {
    return [
      {
        x: clamp(first.x, -bounds.halfX, bounds.halfX),
        z: clamp(first.z, -bounds.halfZ, bounds.halfZ),
      },
      {
        x: clamp(second.x, -bounds.halfX, bounds.halfX),
        z: clamp(second.z, -bounds.halfZ, bounds.halfZ),
      },
    ]
  }

  const halfGap = minimumDistance / 2
  const centerX = clamp(
    (first.x + second.x) / 2,
    -bounds.halfX + halfGap,
    bounds.halfX - halfGap,
  )
  const centerZ = clamp((first.z + second.z) / 2, -bounds.halfZ, bounds.halfZ)
  return [
    { x: centerX - halfGap, z: centerZ },
    { x: centerX + halfGap, z: centerZ },
  ]
}
