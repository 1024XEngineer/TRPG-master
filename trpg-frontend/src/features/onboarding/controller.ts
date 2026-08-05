import { create } from 'zustand'

interface OnboardingControllerState {
  replayRequest: number
  requestReplay: () => void
}

export const useOnboardingController = create<OnboardingControllerState>((set) => ({
  replayRequest: 0,
  requestReplay: () => set((state) => ({ replayRequest: state.replayRequest + 1 })),
}))
