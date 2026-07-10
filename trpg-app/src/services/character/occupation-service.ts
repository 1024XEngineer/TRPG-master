import { ALL_OCCUPATIONS, OCCUPATION_GROUPS, getOccupationById, type OccupationDefinition, type OccupationGroup } from '@/data/occupations'

/**
 * OccupationService — Mock service for fetching occupation data.
 *
 * In production, replace the mock delay and direct data access with
 * a real API call:
 *
 *   async getOccupations(): Promise<OccupationDefinition[]> {
 *     const res = await fetch('/api/occupations')
 *     return res.json()
 *   }
 *
 * The return type stays the same, so the UI never needs to change.
 */

const MOCK_DELAY = 200 // simulate network latency

export async function fetchOccupations(): Promise<OccupationDefinition[]> {
  // Simulate API call
  await new Promise(r => setTimeout(r, MOCK_DELAY))
  return ALL_OCCUPATIONS
}

export async function fetchOccupationGroups(): Promise<OccupationGroup[]> {
  await new Promise(r => setTimeout(r, MOCK_DELAY))
  return OCCUPATION_GROUPS
}

export async function fetchOccupationById(id: number): Promise<OccupationDefinition | null> {
  await new Promise(r => setTimeout(r, MOCK_DELAY))
  return getOccupationById(id) ?? null
}
