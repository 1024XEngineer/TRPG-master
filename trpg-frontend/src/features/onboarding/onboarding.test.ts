import { describe, expect, it, beforeEach } from 'vitest'
import { calculateSpotlightRect } from './geometry'
import { firstStepForPath, stepsForAudience } from './steps'
import {
  onboardingStorageKey,
  readOnboardingState,
  resetOnboardingState,
  writeOnboardingState,
} from './storage'

describe('onboarding geometry', () => {
  it('uses the inner border edge as the fixed-position coordinate origin', () => {
    const rect = calculateSpotlightRect(
      { left: 233, top: 184, width: 334, height: 438 },
      {
        left: 205,
        top: 20,
        width: 390,
        height: 820,
        borderLeft: 8,
        borderTop: 8,
        clientWidth: 374,
        clientHeight: 804,
      },
      280,
    )

    expect(rect).toEqual({ left: 20, top: 156, width: 334, height: 280 })
  })
})

describe('onboarding steps', () => {
  it('filters host-only and player-only steps by room role', () => {
    const hostSteps = stepsForAudience(true)
    const playerSteps = stepsForAudience(false)

    expect(hostSteps.some((step) => step.id === 'lobby-start-story')).toBe(true)
    expect(hostSteps.some((step) => step.id === 'lobby-ready')).toBe(false)
    expect(playerSteps.some((step) => step.id === 'lobby-ready')).toBe(true)
    expect(playerSteps.some((step) => step.id === 'start-game')).toBe(false)
  })

  it('finds the first step for a route after a saved position', () => {
    expect(firstStepForPath('/room/character', false)?.id).toBe('character-progress')
    expect(firstStepForPath('/room/ready', true)?.id).toBe('character-summary')
    expect(firstStepForPath('/home', false)).toBeNull()
  })
})

describe('onboarding storage', () => {
  beforeEach(() => window.localStorage.clear())

  it('isolates state by account and round-trips valid state', () => {
    const state = { status: 'active' as const, stepId: 'character-info' }
    writeOnboardingState('user-a', state)

    expect(window.localStorage.getItem(onboardingStorageKey('user-a'))).not.toBeNull()
    expect(readOnboardingState('user-a')).toEqual(state)
    expect(readOnboardingState('user-b')).toBeNull()
  })

  it('ignores malformed persisted data', () => {
    window.localStorage.setItem(onboardingStorageKey('user-a'), '{"status":"broken"}')
    expect(readOnboardingState('user-a')).toBeNull()
  })

  it('resets only the current account so the guide can be replayed', () => {
    writeOnboardingState('user-a', { status: 'completed', stepId: null })
    writeOnboardingState('user-b', { status: 'skipped', stepId: null })

    expect(resetOnboardingState('user-a')).toBe(true)
    expect(readOnboardingState('user-a')).toBeNull()
    expect(readOnboardingState('user-b')).toEqual({ status: 'skipped', stepId: null })
  })
})
