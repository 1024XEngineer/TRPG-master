import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import {
  firstStepForPath,
  stepsForAudience,
  type OnboardingStep,
} from './steps'
import {
  readOnboardingState,
  writeOnboardingState,
  type OnboardingState,
} from './storage'
import { calculateSpotlightRect, type Rect } from './geometry'

const GUIDE_ROUTES = new Set(['/room/lobby', '/room/story', '/room/character', '/room/ready', '/room/play'])
const SPOTLIGHT_GAP = 12
const SPOTLIGHT_PADDING = 4
const MAX_SPOTLIGHT_HEIGHT = 280
const TOOLTIP_ESTIMATED_HEIGHT = 180
const TARGET_SETTLE_DELAY = 900

function isGuideRoute(pathname: string): boolean {
  return GUIDE_ROUTES.has(pathname)
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max))
}

function toRootRect(element: Element): Rect | null {
  const root = document.querySelector<HTMLElement>('#root')
  if (!root) return null
  const targetRect = element.getBoundingClientRect()
  const rootRect = root.getBoundingClientRect()

  // Fixed children use the transformed root's inner border edge as their
  // coordinate origin. getBoundingClientRect() returns the outer border edge.
  return calculateSpotlightRect(
    targetRect,
    {
      left: rootRect.left,
      top: rootRect.top,
      width: rootRect.width,
      height: rootRect.height,
      borderLeft: root.clientLeft,
      borderTop: root.clientTop,
      clientWidth: root.clientWidth,
      clientHeight: root.clientHeight,
    },
    MAX_SPOTLIGHT_HEIGHT,
  )
}

function findStepIndex(steps: OnboardingStep[], stepId: string | null): number {
  if (!stepId) return 0
  const index = steps.findIndex((step) => step.id === stepId)
  return index >= 0 ? index : 0
}

function useTargetRect(target: string | null, pathname: string): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null)

  const measure = useCallback(() => {
    if (!target) {
      setRect(null)
      return
    }
    const element = document.querySelector(`[data-onboarding-target="${target}"]`)
    if (!element) {
      setRect(null)
      return
    }
    setRect(toRootRect(element))
  }, [target])

  useEffect(() => {
    setRect(null)
    if (!target) return
    const element = document.querySelector(`[data-onboarding-target="${target}"]`)
    if (element) {
      const root = document.querySelector<HTMLElement>('#root')
      const block = root && element.getBoundingClientRect().height > root.clientHeight * 0.55
        ? 'start'
        : 'center'
      element.scrollIntoView({ block, behavior: 'smooth' })
    }
    const retry = window.setTimeout(measure, 120)
    const observer = element && typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(measure)
      : null
    const mutationObserver = new MutationObserver(measure)
    if (element) observer?.observe(element)
    mutationObserver.observe(document.body, { childList: true, subtree: true })
    window.addEventListener('resize', measure)
    document.addEventListener('scroll', measure, true)
    return () => {
      window.clearTimeout(retry)
      observer?.disconnect()
      mutationObserver.disconnect()
      window.removeEventListener('resize', measure)
      document.removeEventListener('scroll', measure, true)
    }
  }, [measure, pathname, target])

  return rect
}

function useDelayedFallback(enabled: boolean, delayMs = 1200): boolean {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    setVisible(false)
    if (!enabled) return
    const timer = window.setTimeout(() => setVisible(true), delayMs)
    return () => window.clearTimeout(timer)
  }, [delayMs, enabled])

  return visible
}

function IntroDialog({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-5 pointer-events-auto">
      <div className="absolute inset-0 bg-black/65" />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-intro-title"
        className="relative w-full max-w-[340px] rounded-lg border border-brass/50 bg-card p-5 shadow-2xl"
      >
        <div className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-brass-dark">
          新手指引
        </div>
        <h2 id="onboarding-intro-title" className="text-lg font-bold text-text-primary">
          一起完成第一次游戏
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-text-body">
          接下来会带你完成创建调查员、准备房间和进入游戏的关键步骤，整个过程可以随时跳过。
        </p>
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="flex-1 rounded-sm border border-border-light bg-panel px-3 py-2.5 text-xs font-semibold text-text-muted"
          >
            暂时跳过
          </button>
          <button
            type="button"
            onClick={onStart}
            className="flex-1 rounded-sm bg-brass px-3 py-2.5 text-xs font-semibold text-white active:bg-brass-dark"
          >
            开始指引
          </button>
        </div>
      </section>
    </div>
  )
}

function MissingTargetCard({ step, onDismiss, onSkip }: { step: OnboardingStep; onDismiss: () => void; onSkip: () => void }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-5 pointer-events-none">
      <section className="relative w-full max-w-[340px] rounded-lg border border-border-light bg-card p-5 shadow-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-brass-dark">{step.title}</p>
        <p className="mt-2 text-sm leading-relaxed text-text-body">{step.description}</p>
        <p className="mt-2 text-[11px] text-text-muted">请先完成当前页面的必要操作，目标出现后指引会自动继续。</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button type="button" onClick={onSkip} className="pointer-events-auto text-xs text-text-muted underline">
            跳过
          </button>
          <button type="button" onClick={onDismiss} className="pointer-events-auto rounded-sm bg-brass px-4 py-2 text-xs font-semibold text-white">
            继续操作
          </button>
        </div>
      </section>
    </div>
  )
}

function ConfirmSkipDialog({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center px-5 pointer-events-auto">
      <div className="absolute inset-0 bg-black/65" onClick={onCancel} />
      <section role="alertdialog" aria-modal="true" aria-labelledby="onboarding-skip-title" className="relative w-full max-w-[320px] rounded-lg border border-border-light bg-card p-5 shadow-2xl">
        <h2 id="onboarding-skip-title" className="text-base font-bold text-text-primary">跳过新手指引？</h2>
        <p className="mt-2 text-sm leading-relaxed text-text-body">跳过后，本账号之后不会再自动显示这套指引。</p>
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={onCancel} className="flex-1 rounded-sm border border-border-light bg-panel px-3 py-2.5 text-xs font-semibold text-text-muted">继续指引</button>
          <button type="button" onClick={onConfirm} className="flex-1 rounded-sm bg-[#c04040] px-3 py-2.5 text-xs font-semibold text-white">确认跳过</button>
        </div>
      </section>
    </div>
  )
}

function CompletionDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center px-5 pointer-events-auto">
      <div className="absolute inset-0 bg-black/65" />
      <section role="dialog" aria-modal="true" aria-labelledby="onboarding-complete-title" className="relative w-full max-w-[320px] rounded-lg border border-brass/50 bg-card p-5 text-center shadow-2xl">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-brass/10 text-xl">✓</div>
        <h2 id="onboarding-complete-title" className="mt-3 text-base font-bold text-text-primary">新手指引已完成</h2>
        <p className="mt-2 text-sm leading-relaxed text-text-body">现在可以阅读主持人的叙事，并用自己的方式展开调查了。</p>
        <button type="button" autoFocus onClick={onClose} className="mt-5 w-full rounded-sm bg-brass px-4 py-2.5 text-xs font-semibold text-white active:bg-brass-dark">开始调查</button>
      </section>
    </div>
  )
}

function Tooltip({
  step,
  index,
  total,
  rect,
  onPrevious,
  onNext,
  onSkip,
}: {
  step: OnboardingStep
  index: number
  total: number
  rect: Rect
  onPrevious: () => void
  onNext: () => void
  onSkip: () => void
}) {
  const root = document.querySelector<HTMLElement>('#root')
  const rootWidth = root?.clientWidth ?? 390
  const rootHeight = root?.clientHeight ?? 820
  const tooltipWidth = Math.min(300, rootWidth - 24)
  const left = clamp(rect.left + rect.width / 2 - tooltipWidth / 2, 12, rootWidth - tooltipWidth - 12)
  const spaceAbove = rect.top
  const spaceBelow = rootHeight - rect.top - rect.height
  const below = spaceBelow >= TOOLTIP_ESTIMATED_HEIGHT + SPOTLIGHT_GAP || spaceBelow >= spaceAbove
  const top = below ? rect.top + rect.height + SPOTLIGHT_GAP : undefined
  const bottom = below ? undefined : rootHeight - rect.top + SPOTLIGHT_GAP
  const arrowLeft = clamp(rect.left + rect.width / 2 - left - 7, 16, tooltipWidth - 20)

  return (
    <div
      role="dialog"
      aria-label="新手指引"
      aria-live="polite"
      className="fixed z-[102] pointer-events-auto"
      style={{ left, top, bottom, width: tooltipWidth }}
    >
      <div
        className={`absolute -top-2 h-4 w-4 rotate-45 border-l border-t border-brass/50 bg-card ${below ? '' : 'top-auto -bottom-2 rotate-[225deg]'}`}
        style={{ left: arrowLeft }}
      />
      <div className="relative rounded-lg border border-brass/50 bg-card p-4 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-brass-dark">
              第 {index + 1} 步 / 共 {total} 步
            </p>
            <h2 className="mt-1 text-sm font-bold text-text-primary">{step.title}</h2>
          </div>
          <button type="button" onClick={onSkip} aria-label="跳过新手指引" className="text-text-muted">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-text-body">{step.description}</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button type="button" onClick={onPrevious} disabled={index === 0} className="flex items-center gap-1 text-xs text-text-muted disabled:opacity-35">
            <ChevronLeft className="h-3.5 w-3.5" /> 上一步
          </button>
          <button type="button" onClick={onNext} className="flex items-center gap-1 rounded-sm bg-brass px-3 py-2 text-xs font-semibold text-white active:bg-brass-dark">
            {index === total - 1 ? '完成' : '下一步'} <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function OnboardingLayer() {
  const { pathname } = useLocation()
  const userId = useAuthStore((state) => state.userId)
  const roomId = useRoomStore((state) => state.roomId)
  const isHost = useRoomStore((state) => state.isHost)
  const [state, setState] = useState<OnboardingState | null>(null)
  const [introOpen, setIntroOpen] = useState(false)
  const [confirmSkipOpen, setConfirmSkipOpen] = useState(false)
  const [completionOpen, setCompletionOpen] = useState(false)
  const [dismissedFallbackStep, setDismissedFallbackStep] = useState<string | null>(null)

  const steps = useMemo(() => stepsForAudience(isHost), [isHost])
  const activeIndex = findStepIndex(steps, state?.stepId ?? null)
  const activeStep = state?.status === 'active' ? steps[activeIndex] ?? null : null
  const targetRect = useTargetRect(activeStep?.route === pathname ? activeStep.target : null, pathname)
  const fallbackVisible = useDelayedFallback(Boolean(activeStep && activeStep.route === pathname && !targetRect))

  useEffect(() => {
    if (!userId || !roomId || !isGuideRoute(pathname)) {
      setState(null)
      setIntroOpen(false)
      setConfirmSkipOpen(false)
      return
    }
    const stored = readOnboardingState(userId)
    if (stored?.status === 'skipped' || stored?.status === 'completed') {
      setState(stored)
      setIntroOpen(false)
      return
    }
    if (stored?.status === 'active') {
      setState(stored)
      setIntroOpen(false)
      return
    }
    setState(null)
    setIntroOpen(true)
  }, [isHost, pathname, roomId, userId])

  useEffect(() => {
    if (!userId || state?.status !== 'active' || !activeStep) return
    if (activeStep.route === pathname) return
    const next = firstStepForPath(pathname, isHost, activeIndex)
    if (!next) return
    const nextState = { status: 'active' as const, stepId: next.id }
    setState(nextState)
    writeOnboardingState(userId, nextState)
    setDismissedFallbackStep(null)
  }, [activeIndex, activeStep, isHost, pathname, state?.status, userId])

  useEffect(() => {
    if (
      !userId ||
      state?.status !== 'active' ||
      !activeStep ||
      activeStep.route !== pathname ||
      targetRect
    ) {
      return
    }

    const timer = window.setTimeout(() => {
      const nextIndex = steps.findIndex(
        (step, index) =>
          index > activeIndex &&
          step.route === pathname &&
          document.querySelector(`[data-onboarding-target="${step.target}"]`),
      )
      if (nextIndex < 0) return
      const nextState = { status: 'active' as const, stepId: steps[nextIndex].id }
      setState(nextState)
      writeOnboardingState(userId, nextState)
      setDismissedFallbackStep(null)
    }, TARGET_SETTLE_DELAY)

    return () => window.clearTimeout(timer)
  }, [activeIndex, activeStep, pathname, state?.status, steps, targetRect, userId])

  const start = () => {
    if (!userId) return
    const first = firstStepForPath(pathname, isHost) ?? steps[0]
    if (!first) return
    const nextState = { status: 'active' as const, stepId: first.id }
    setState(nextState)
    writeOnboardingState(userId, nextState)
    setIntroOpen(false)
  }

  const skip = () => {
    if (userId) writeOnboardingState(userId, { status: 'skipped', stepId: null })
    setState({ status: 'skipped', stepId: null })
    setIntroOpen(false)
    setConfirmSkipOpen(false)
  }

  const move = (delta: number) => {
    if (!userId || state?.status !== 'active') return
    const nextIndex = activeIndex + delta
    if (nextIndex >= steps.length) {
      writeOnboardingState(userId, { status: 'completed', stepId: null })
      setState({ status: 'completed', stepId: null })
      setCompletionOpen(true)
      return
    }
    const nextState = { status: 'active' as const, stepId: steps[Math.max(0, nextIndex)].id }
    setState(nextState)
    writeOnboardingState(userId, nextState)
    setDismissedFallbackStep(null)
  }

  if (confirmSkipOpen) return <ConfirmSkipDialog onCancel={() => setConfirmSkipOpen(false)} onConfirm={skip} />
  if (completionOpen) return <CompletionDialog onClose={() => setCompletionOpen(false)} />
  if (introOpen) return <IntroDialog onStart={start} onSkip={() => setConfirmSkipOpen(true)} />
  if (!activeStep || activeStep.route !== pathname) return null
  if (!targetRect) {
    if (!fallbackVisible || dismissedFallbackStep === activeStep.id) return null
    return (
      <MissingTargetCard
        step={activeStep}
        onDismiss={() => setDismissedFallbackStep(activeStep.id)}
        onSkip={() => setConfirmSkipOpen(true)}
      />
    )
  }

  return (
    <>
      <div
        data-onboarding-highlight="true"
        aria-hidden="true"
        className="fixed z-[101] rounded-md border-2 border-brass pointer-events-none shadow-[0_0_0_9999px_rgba(10,8,6,0.58)]"
        style={{
          left: targetRect.left - SPOTLIGHT_PADDING,
          top: targetRect.top - SPOTLIGHT_PADDING,
          width: targetRect.width + SPOTLIGHT_PADDING * 2,
          height: targetRect.height + SPOTLIGHT_PADDING * 2,
        }}
      />
      <Tooltip
        step={activeStep}
        index={activeIndex}
        total={steps.length}
        rect={targetRect}
        onPrevious={() => move(-1)}
        onNext={() => move(1)}
        onSkip={() => setConfirmSkipOpen(true)}
      />
    </>
  )
}
