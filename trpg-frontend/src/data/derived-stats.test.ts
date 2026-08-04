import { describe, expect, it } from 'vitest'
import { DERIVED_STAT_DEFINITIONS, normalizeDerivedStats } from './derived-stats'

describe('derived stats display', () => {
  it('normalizes all server derived stat keys', () => {
    expect(normalizeDerivedStats({
      HP: 12,
      SAN: 55,
      MP: 11,
      DB: '+1D4',
      Build: '+1D4',
      MOV: 8,
    })).toEqual({
      hp: 12,
      san: 55,
      mp: 11,
      db: '+1D4',
      build: '+1D4',
      move: 8,
    })
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
