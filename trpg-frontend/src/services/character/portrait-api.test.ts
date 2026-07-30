import { describe, expect, it } from 'vitest'
import { isCharacterPortraitEnabled } from './portrait-api'

describe('isCharacterPortraitEnabled', () => {
  it('只有显式设为 true 时才开启等待页生图入口', () => {
    expect(isCharacterPortraitEnabled('true')).toBe(true)
    expect(isCharacterPortraitEnabled(true)).toBe(true)
    expect(isCharacterPortraitEnabled('false')).toBe(false)
    expect(isCharacterPortraitEnabled(undefined)).toBe(false)
  })
})
