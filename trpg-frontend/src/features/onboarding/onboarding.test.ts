import { createElement } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { calculateSpotlightRect } from './geometry'
import { firstReplayStepForPath, firstStepForPath, stepsForAudience } from './steps'
import { useOnboardingController } from './controller'
import OnboardingLayer, { preparePreviousStepTarget } from './OnboardingLayer'
import {
  onboardingStorageKey,
  readOnboardingState,
  resetOnboardingState,
  writeOnboardingState,
} from './storage'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

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
    )

    expect(rect).toEqual({ left: 20, top: 156, width: 334, height: 438 })
  })

  it('highlights the full visible portion of a target that extends past the viewport', () => {
    const rect = calculateSpotlightRect(
      { left: 20, top: 100, width: 350, height: 900 },
      {
        left: 0,
        top: 0,
        width: 390,
        height: 820,
        borderLeft: 0,
        borderTop: 0,
        clientWidth: 390,
        clientHeight: 820,
      },
    )

    expect(rect).toEqual({ left: 20, top: 100, width: 350, height: 720 })
  })
})

describe('onboarding steps', () => {
  it('keeps the focused rules guide short for both room roles', () => {
    const hostSteps = stepsForAudience(true)
    const playerSteps = stepsForAudience(false)

    expect(hostSteps).toEqual(playerSteps)
    expect(hostSteps).toHaveLength(9)
    expect(hostSteps.some((step) => step.route === '/room/lobby')).toBe(false)
    expect(hostSteps.some((step) => step.id === 'start-game')).toBe(false)
  })

  it('finds the first step for a route after a saved position', () => {
    expect(firstStepForPath('/room/character', false)?.id).toBe('character-progress')
    expect(firstStepForPath('/room/ready', true)?.id).toBe('player-status')
    expect(firstStepForPath('/home', false)).toBeNull()
  })

  it('starts replay at the first target available on the current page', () => {
    const availableTargets = new Set(['character-progress', 'skill-editor'])

    expect(
      firstReplayStepForPath(
        '/room/character',
        false,
        (target) => availableTargets.has(target),
      )?.id,
    ).toBe('skill-editor')
  })

  it('waits silently for controls on later character-building stages', () => {
    const waitingStepIds = stepsForAudience(false)
      .filter((step) => step.waitForTarget)
      .map((step) => step.id)

    expect(waitingStepIds).toEqual([
      'attribute-editor',
      'skill-editor',
      'credit-rating',
      'character-submit',
    ])
  })

  it('explains COC credit rating as a separate guided rule', () => {
    const creditStep = stepsForAudience(false).find((step) => step.id === 'credit-rating')

    expect(creditStep?.target).toBe('credit-rating-editor')
    expect(creditStep?.description).toContain('职业技能点')
    expect(creditStep?.description).toContain('兴趣技能点')
    expect(creditStep?.description).toContain('社会地位')
  })

  it('explains the asymmetric COC skill point pools in beginner language', () => {
    const skillStep = stepsForAudience(false).find((step) => step.id === 'skill-editor')

    expect(skillStep?.description).toContain('两份建卡预算')
    expect(skillStep?.description).toContain('职业点用完后')
    expect(skillStep?.description).toContain('兴趣列表里的技能则只能花兴趣点')
  })

  it('points the attribute step at the inline COC attribute explanation', () => {
    const attributeStep = stepsForAudience(false).find((step) => step.id === 'attribute-editor')

    expect(attributeStep?.target).toBe('attribute-example-row')
    expect(attributeStep?.description).toContain('圆形说明按钮')
    expect(attributeStep?.description).toContain('幸运')
  })

  it('requests an immediate replay through the shared controller', () => {
    useOnboardingController.setState({ replayRequest: 0 })
    useOnboardingController.getState().requestReplay()

    expect(useOnboardingController.getState().replayRequest).toBe(1)
  })
})

describe('onboarding delayed target alignment', () => {
  it('scrolls a target into view when the next page stage mounts it later', async () => {
    const scrollIntoView = vi.fn()
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    useAuthStore.setState({ userId: 'user-a' })
    useRoomStore.setState({ roomId: 'room-a', isHost: false })
    writeOnboardingState('user-a', { status: 'active', stepId: 'attribute-editor' })

    const tree = (targetMounted: boolean) => createElement(
      MemoryRouter,
      { initialEntries: ['/room/character'] },
      createElement(
        'div',
        { id: 'root' },
        createElement(OnboardingLayer),
        targetMounted
          ? createElement('div', { 'data-onboarding-target': 'attribute-example-row' })
          : null,
      ),
    )
    const view = render(tree(false))

    expect(scrollIntoView).not.toHaveBeenCalled()
    view.rerender(tree(true))

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center', behavior: 'smooth' })
    })
  })
})

describe('onboarding character edit mode', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useOnboardingController.setState({ replayRequest: 0 })
    useAuthStore.setState({ userId: 'user-a' })
    useRoomStore.setState({ roomId: 'room-a', isHost: false })
  })

  it('does not automatically resume character-building steps when editing a completed character', async () => {
    writeOnboardingState('user-a', { status: 'active', stepId: 'skill-editor' })

    render(
      createElement(
        MemoryRouter,
        { initialEntries: [{ pathname: '/room/character', state: { fromCharacterReady: true } }] },
        createElement(
          'div',
          { id: 'root' },
          createElement(OnboardingLayer),
          createElement('div', { 'data-onboarding-target': 'skill-editor' }),
        ),
      ),
    )

    await waitFor(() => {
      expect(document.querySelector('[data-onboarding-highlight="true"]')).toBeNull()
    })
  })

  it('still allows the rules button to replay the guide while editing', async () => {
    writeOnboardingState('user-a', { status: 'completed', stepId: null })

    render(
      createElement(
        MemoryRouter,
        { initialEntries: [{ pathname: '/room/character', state: { fromCharacterReady: true } }] },
        createElement(
          'div',
          { id: 'root' },
          createElement(OnboardingLayer),
          createElement('div', { 'data-onboarding-target': 'skill-editor' }),
        ),
      ),
    )

    await act(async () => undefined)
    act(() => useOnboardingController.getState().requestReplay())

    await waitFor(() => {
      expect(readOnboardingState('user-a')).toEqual({ status: 'active', stepId: 'skill-editor' })
    })
  })
})

describe('onboarding previous-step navigation', () => {
  it('moves the character builder back when the previous target is on an earlier stage', () => {
    const pageBack = document.createElement('button')
    pageBack.setAttribute('data-onboarding-page-back', '')
    const click = vi.fn()
    pageBack.addEventListener('click', click)
    document.body.appendChild(pageBack)
    const attributeStep = stepsForAudience(false).find((step) => step.id === 'attribute-editor')!

    expect(preparePreviousStepTarget(attributeStep, '/room/character')).toBe(true)
    expect(click).toHaveBeenCalledOnce()
    pageBack.remove()
  })

  it('does not change page stage when the previous target is already mounted', () => {
    const pageBack = document.createElement('button')
    pageBack.setAttribute('data-onboarding-page-back', '')
    const click = vi.fn()
    pageBack.addEventListener('click', click)
    document.body.appendChild(pageBack)
    const target = document.createElement('div')
    target.setAttribute('data-onboarding-target', 'skill-editor')
    document.body.appendChild(target)
    const skillStep = stepsForAudience(false).find((step) => step.id === 'skill-editor')!

    expect(preparePreviousStepTarget(skillStep, '/room/character')).toBe(true)
    expect(click).not.toHaveBeenCalled()
    target.remove()
    pageBack.remove()
  })

  it('rejects a previous step that belongs to a different route', () => {
    const submitStep = stepsForAudience(false).find((step) => step.id === 'character-submit')!

    expect(preparePreviousStepTarget(submitStep, '/room/ready')).toBe(false)
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
