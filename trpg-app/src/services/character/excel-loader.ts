/**
 * Excel data loader — fetches and parses Excel files at runtime.
 *
 * Uses the SheetJS (xlsx) library to load `.xlsx` files from the
 * public/ directory and return typed data objects.
 *
 * This is a transitional approach: in production the same data would
 * come from a backend API, but while the backend isn't built yet,
 * editing the Excel file is much easier than editing TypeScript.
 */

import * as XLSX from 'xlsx'
import type { OccupationDefinition } from '@/data/occupations'

interface ExcelRow {
  id: number
  name: string
  creditRange: string
  skillPoints: string
  icon: string
  shortDesc: string
  skillIds: string
}

interface GroupRow {
  label: string
  icon: string
  ids: string
}

export interface OccupationGroup {
  label: string
  icon: string
  ids: number[]
}

/**
 * Fetch and parse the occupations Excel file from the public directory.
 * Returns the parsed occupations and groups, or throws on failure.
 */
export async function loadOccupationsFromExcel(): Promise<{
  occupations: OccupationDefinition[]
  groups: OccupationGroup[]
}> {
  const url = new URL('/data/occupations.xlsx', window.location.origin)
  const response = await fetch(url.toString())
  if (!response.ok) {
    throw new Error(`Failed to fetch occupations.xlsx: ${response.status} ${response.statusText}`)
  }

  const arrayBuffer = await response.arrayBuffer()
  const workbook = XLSX.read(arrayBuffer, { type: 'array' })

  // Sheet 1: 职业
  const occSheet = workbook.Sheets['职业']
  if (!occSheet) throw new Error('Excel file missing "职业" sheet')
  const rawRows: ExcelRow[] = XLSX.utils.sheet_to_json(occSheet)

  const occupations: OccupationDefinition[] = rawRows.map(row => ({
    id: row.id,
    name: row.name,
    creditRange: row.creditRange,
    skillPoints: row.skillPoints,
    icon: row.icon,
    shortDesc: row.shortDesc,
    skillIds: row.skillIds.split(',').map((s: string) => s.trim()),
  }))

  // Sheet 2: 分组
  const groupSheet = workbook.Sheets['分组']
  if (!groupSheet) throw new Error('Excel file missing "分组" sheet')
  const groupRows: GroupRow[] = XLSX.utils.sheet_to_json(groupSheet)

  const groups: OccupationGroup[] = groupRows.map(row => ({
    label: row.label,
    icon: row.icon,
    ids: row.ids.split(',').map((s: string) => parseInt(s.trim(), 10)),
  }))

  return { occupations, groups }
}
