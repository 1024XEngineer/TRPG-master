import { Quaternion, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'

import { faceNormal, polyhedronFaces } from './geometry'

const EPSILON = 1e-6

function vertexKey(vertex: Vector3): string {
  return vertex.toArray().map((value) => Math.round(value / EPSILON)).join(',')
}

function uniqueVertices(faces: Vector3[][]): Vector3[] {
  return [...new Map(faces.flat().map((vertex) => [vertexKey(vertex), vertex])).values()]
}

function outwardNormal(face: Vector3[]): Vector3 {
  const normal = faceNormal(face)
  if (normal.dot(face[0]) < 0) normal.negate()
  return normal
}

describe('D10 geometry', () => {
  it('forms a closed shell with 10 quadrilateral faces, 12 vertices and 20 shared edges', () => {
    const faces = polyhedronFaces('d10')
    expect(faces).toHaveLength(10)
    expect(uniqueVertices(faces)).toHaveLength(12)
    const edges = new Map<string, number>()
    for (const face of faces) {
      expect(face).toHaveLength(4)
      expect(new Set(face.map(vertexKey)).size).toBe(4)
      for (let i = 0; i < face.length; i += 1) {
        const key = [vertexKey(face[i]), vertexKey(face[(i + 1) % face.length])].sort().join('|')
        edges.set(key, (edges.get(key) ?? 0) + 1)
      }
    }
    expect(edges.size).toBe(20)
    expect([...edges.values()].every((uses) => uses === 2)).toBe(true)
  })

  it('keeps each numeric face planar with identical normals across its rendered triangles', () => {
    for (const face of polyhedronFaces('d10')) {
      // Match the renderer's fan diagonal (0, 2), without relying on Newell's
      // averaged normal: an averaged normal can hide a folded quadrilateral.
      const first = new Vector3().subVectors(face[1], face[0])
        .cross(new Vector3().subVectors(face[2], face[0]))
      const second = new Vector3().subVectors(face[2], face[0])
        .cross(new Vector3().subVectors(face[3], face[0]))
      expect(first.length()).toBeGreaterThan(EPSILON)
      expect(second.length()).toBeGreaterThan(EPSILON)
      first.normalize()
      second.normalize()
      expect(Math.abs(first.dot(face[3].clone().sub(face[0])))).toBeLessThan(EPSILON)
      expect(first.dot(second)).toBeCloseTo(1, 10)
      expect(first.dot(faceNormal(face))).toBeCloseTo(1, 10)
    }
  })

  it('is convex: every vertex lies on or behind each outward face plane', () => {
    const faces = polyhedronFaces('d10')
    const vertices = uniqueVertices(faces)
    for (const face of faces) {
      const normal = outwardNormal(face)
      const distance = normal.dot(face[0])
      expect(distance).toBeGreaterThan(0)
      for (const vertex of vertices) {
        expect(normal.dot(vertex) - distance).toBeLessThan(EPSILON)
      }
    }
  })

  it('has ten congruent kite faces with two equal adjacent pairs of sides', () => {
    const faces = polyhedronFaces('d10')
    const distances = (face: Vector3[]) => face.flatMap((a, i) =>
      face.slice(i + 1).map((b) => a.distanceTo(b))).sort((a, b) => a - b)
    const reference = distances(faces[0])
    for (const face of faces) {
      const sides = face.map((vertex, i) => vertex.distanceTo(face[(i + 1) % 4]))
      expect(sides[0]).toBeCloseTo(sides[3], 10)
      expect(sides[1]).toBeCloseTo(sides[2], 10)
      expect(sides[0]).toBeGreaterThan(sides[1])
      const longDiagonal = face[2].clone().sub(face[0])
      const shortDiagonal = face[3].clone().sub(face[1])
      expect(longDiagonal.dot(shortDiagonal)).toBeCloseTo(0, 10)
      distances(face).forEach((distance, i) => expect(distance).toBeCloseTo(reference[i], 10))
    }
  })

  it('rests on a complete opposite face without penetrating the floor for every upward face', () => {
    const faces = polyhedronFaces('d10')
    const vertices = uniqueVertices(faces)
    // Use the same center-to-face height as the renderer, then independently
    // check actual vertices against the floor instead of trusting that height.
    const distances = faces.map((face) => {
      const centroid = face.reduce((sum, vertex) => sum.add(vertex), new Vector3()).divideScalar(4)
      return Math.abs(centroid.dot(outwardNormal(face)))
    })
    const restY = Math.min(...distances)
    distances.forEach((distance) => expect(distance).toBeCloseTo(restY, 10))
    for (const face of faces) {
      const rotation = new Quaternion().setFromUnitVectors(outwardNormal(face), new Vector3(0, 1, 0))
      const heights = vertices.map((vertex) => vertex.clone().applyQuaternion(rotation).y + restY)
      expect(Math.min(...heights)).toBeGreaterThan(-EPSILON)
      expect(heights.filter((height) => Math.abs(height) < EPSILON)).toHaveLength(4)
      for (const vertex of face) {
        expect(vertex.clone().applyQuaternion(rotation).y).toBeCloseTo(restY, 10)
      }
    }
  })
})
