export interface DerivedStatsView {
  hp: number
  san: number
  mp: number
  db: string
  /** 体格是整数；`null` 表示这份角色卡存的值无法解读，由渲染层显示占位符。 */
  build: number | null
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
  // 体格在修复前与伤害加值共用同一个值，所以已经建好的角色卡里可能存着
  // `+1D4` 这样的骰子表达式。解析不出整数就留空——0 是合法体格值，兜底成
  // 它只会让玩家看到一个看似正常的错误数字。
  const buildValue = (value: unknown) => {
    if (typeof value === 'number') return value
    if (typeof value === 'string' && /^[+-]?\d+$/.test(value.trim())) {
      return Number(value)
    }
    return null
  }
  return {
    hp: numberValue(derived?.HP),
    san: numberValue(derived?.SAN),
    mp: numberValue(derived?.MP),
    db: stringValue(derived?.DB),
    build: buildValue(derived?.Build),
    move: numberValue(derived?.MOV),
  }
}
