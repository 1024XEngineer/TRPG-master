import { ALL_OCCUPATIONS, OCCUPATION_GROUPS, type OccupationDefinition } from '@/data/occupations'
import { loadOccupationsFromExcel, type OccupationGroup } from './excel-loader'

/**
 * OccupationService — loads occupation data from Excel at runtime,
 * with a fallback to the hardcoded TypeScript data.
 *
 * When the backend is ready, replace this with real API calls. The
 * return types stay the same so the UI never needs to change.
 *
 * Usage:
 *   const occs = await fetchOccupations()
 *   const occ  = await fetchOccupationById(5)
 */

// ── Cached data ──
let cachedOccupations: OccupationDefinition[] | null = null
let cachedGroups: OccupationGroup[] | null = null
let excelLoadAttempted = false

async function ensureLoaded(): Promise<void> {
  if (cachedOccupations) return
  if (excelLoadAttempted) {
    // Already tried and failed; use hardcoded fallback
    cachedOccupations = ALL_OCCUPATIONS
    cachedGroups = OCCUPATION_GROUPS.map(g => ({ label: g.label, icon: g.icon, ids: g.ids }))
    return
  }

  excelLoadAttempted = true

  try {
    const data = await loadOccupationsFromExcel()
    cachedOccupations = data.occupations
    cachedGroups = data.groups
    console.log(`[OccupationService] Loaded ${data.occupations.length} occupations from Excel`)
  } catch (err) {
    console.warn('[OccupationService] Excel load failed, using hardcoded fallback:', err)
    cachedOccupations = ALL_OCCUPATIONS
    cachedGroups = OCCUPATION_GROUPS.map(g => ({ label: g.label, icon: g.icon, ids: g.ids }))
  }
}

export async function fetchOccupations(): Promise<OccupationDefinition[]> {
  await ensureLoaded()
  return cachedOccupations!
}

export async function fetchOccupationById(id: number): Promise<OccupationDefinition | null> {
  await ensureLoaded()
  return cachedOccupations!.find(o => o.id === id) ?? null
}

export async function fetchOccupationGroups(): Promise<OccupationGroup[]> {
  await ensureLoaded()
  return cachedGroups!
}

/** Force a reload from Excel (e.g. if the file was updated) */
export function clearOccupationCache(): void {
  cachedOccupations = null
  cachedGroups = null
  excelLoadAttempted = false
}
