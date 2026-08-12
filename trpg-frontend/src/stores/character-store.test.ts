import { describe, expect, it } from 'vitest'
import { CHARACTER_STORE_VERSION, migrateCharacterState } from './character-store'

const legacyState = (build: unknown) => ({
  roomId: 'room-1',
  character: {
    info: {},
    attr: {},
    skillAlloc: {},
    skillFinalValues: {},
    equipment: '',
    background: '',
    notes: '',
    derived: { hp: 12, san: 55, mp: 11, db: '+1D4', build, move: 8 },
  },
})

describe('character store migration', () => {
  it('clears a build that was stored as a damage-bonus expression', () => {
    // #284 之前体格与伤害加值共用一个值，localStorage 里存着骰子表达式。
    const migrated = migrateCharacterState(legacyState('+1D4'), 0) as ReturnType<
      typeof legacyState
    >
    expect(migrated.character.derived.build).toBeNull()
  })

  it('keeps integer builds that were stored as strings', () => {
    const migrated = migrateCharacterState(legacyState('-2'), 0) as ReturnType<typeof legacyState>
    expect(migrated.character.derived.build).toBe(-2)
  })

  it('leaves already-migrated state untouched', () => {
    const current = legacyState(3)
    expect(migrateCharacterState(current, CHARACTER_STORE_VERSION)).toBe(current)
  })

  it('tolerates an empty store', () => {
    expect(migrateCharacterState({ roomId: null, character: null }, 0)).toEqual({
      roomId: null,
      character: null,
    })
  })
})
