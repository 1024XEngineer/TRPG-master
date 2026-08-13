import { describe, expect, it } from 'vitest'
import { DERIVED_STAT_DEFINITIONS, normalizeDerivedStats } from './derived-stats'

describe('derived stats display', () => {
  it('normalizes all server derived stat keys', () => {
    expect(normalizeDerivedStats({
      HP: 12,
      SAN: 55,
      MP: 11,
      DB: '+1D4',
      Build: 1,
      MOV: 8,
    })).toEqual({
      hp: 12,
      san: 55,
      mp: 11,
      db: '+1D4',
      build: 1,
      move: 8,
    })
  })

  it('reads integer build values stored as strings', () => {
    // 修复前后端把体格也存成字符串；前三档的值本身是对的，照常读出来。
    expect(normalizeDerivedStats({ Build: '0' }).build).toBe(0)
    expect(normalizeDerivedStats({ Build: '-2' }).build).toBe(-2)
  })

  it('leaves build empty when the stored value is a damage-bonus expression', () => {
    // 修复前体格与伤害加值共用一个值，已建的角色卡里存着骰子表达式。
    // 兜底成 0 会让玩家看到一个看似正常的错误体格，所以显式留空。
    expect(normalizeDerivedStats({ Build: '+1D4' }).build).toBeNull()
    expect(normalizeDerivedStats({ Build: '+1D8' }).build).toBeNull()
    expect(normalizeDerivedStats(undefined).build).toBeNull()
  })

  it('defines six Chinese-first labels in display order', () => {
    expect(DERIVED_STAT_DEFINITIONS.map(item => [item.label, item.abbreviation])).toEqual([
      ['生命值', 'HP'],
      ['理智值', 'SAN'],
      ['魔法值', 'MP'],
      ['伤害加值', 'DB'],
      ['体格', 'Build'],
      ['移动力', 'MOV'],
    ])
  })
})
