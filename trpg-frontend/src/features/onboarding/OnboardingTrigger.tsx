import { CircleHelp } from 'lucide-react'
import { useRoomStore } from '@/stores/room-store'
import { useOnboardingController } from './controller'

interface OnboardingTriggerProps {
  className?: string
}

export default function OnboardingTrigger({ className = '' }: OnboardingTriggerProps) {
  const roomId = useRoomStore((state) => state.roomId)
  const requestReplay = useOnboardingController((state) => state.requestReplay)

  if (!roomId) return null

  return (
    <button
      type="button"
      onClick={requestReplay}
      aria-label="重新观看 COC 规则指引"
      title="重新观看 COC 规则指引"
      className={`h-8 flex-shrink-0 rounded-full border border-border-light bg-card px-2.5 text-[11px] font-semibold text-text-muted flex items-center justify-center gap-1.5 active:bg-panel active:scale-[0.96] transition-all ${className}`}
    >
      <CircleHelp className="h-4 w-4" strokeWidth={2.25} />
      <span>规则指引</span>
    </button>
  )
}
