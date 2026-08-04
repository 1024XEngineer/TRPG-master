export interface DerivedStatsView {
  hp: number
  san: number
  mp: number
  db: string
  build?: string
  move: number
}

export type DerivedStatKey = keyof DerivedStatsView

export const DERIVED_STAT_DEFINITIONS: ReadonlyArray<{
  key: DerivedStatKey
  label: string
  abbreviation: string
  color: string
}> = [
  { key: 'hp', label: '生命值', abbreviation: 'HP', color: '#4a8a4a' },
  { key: 'san', label: '理智值', abbreviation: 'SAN', color: '#7050a0' },
  { key: 'mp', label: '魔法值', abbreviation: 'MP', color: '#4a7098' },
  { key: 'db', label: '伤害加值', abbreviation: 'DB', color: '#6a6050' },
  { key: 'build', label: '体格', abbreviation: 'Build', color: '#b8976a' },
  { key: 'move', label: '移动力', abbreviation: 'MOV', color: '#c08050' },
]

export function normalizeDerivedStats(
  derived: Record<string, number | string> | undefined,
): DerivedStatsView {
  const numberValue = (value: unknown) => (typeof value === 'number' ? value : 0)
  const stringValue = (value: unknown) => (value == null ? '0' : String(value))
  return {
    hp: numberValue(derived?.HP),
    san: numberValue(derived?.SAN),
    mp: numberValue(derived?.MP),
    db: stringValue(derived?.DB),
    build: stringValue(derived?.Build),
    move: numberValue(derived?.MOV),
  }
}
