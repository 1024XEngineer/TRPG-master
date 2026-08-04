export type OnboardingStatus = 'active' | 'skipped' | 'completed'

export interface OnboardingState {
  status: OnboardingStatus
  stepId: string | null
}

const STORAGE_PREFIX = 'trpg-onboarding-v1'

export function onboardingStorageKey(userId: string): string {
  return `${STORAGE_PREFIX}:${userId}`
}

export function readOnboardingState(userId: string): OnboardingState | null {
  try {
    const raw = window.localStorage.getItem(onboardingStorageKey(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<OnboardingState>
    if (
      (parsed.status !== 'active' &&
        parsed.status !== 'skipped' &&
        parsed.status !== 'completed') ||
      (parsed.stepId !== null && typeof parsed.stepId !== 'string')
    ) {
      return null
    }
    return { status: parsed.status, stepId: parsed.stepId ?? null }
  } catch {
    return null
  }
}

export function writeOnboardingState(userId: string, state: OnboardingState): void {
  try {
    window.localStorage.setItem(onboardingStorageKey(userId), JSON.stringify(state))
  } catch {
    // A blocked storage implementation must not prevent a player from entering a game.
  }
}
