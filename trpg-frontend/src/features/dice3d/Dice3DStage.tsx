/**
 * 3D 骰子的 React 封装（issue #217）。
 *
 * three 走**动态 import**：只有真的要渲染 3D 骰子时才加载，不进首屏包。
 * 因此这里对引擎只能用 `import type`，任何值层面的引用都必须在 `import()` 之后。
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

import type { DiceStage } from './engine'
import { supports3DDice } from './support'
import type { DiceKind, DiceRollToken } from './types'

export interface Dice3DHandle {
  /** 返回 false 表示舞台仍在处理上一轮，未接受本次请求。 */
  roll: (token: DiceRollToken, targetValue?: number) => boolean
}

interface Dice3DStageProps {
  kind: DiceKind
  /** 骰子停稳、结果可读时调用一次。 */
  onSettled: (value: number, token: DiceRollToken) => void
  /** 环境不支持 3D（无 WebGL / 用户要求减少动效）时调用，调用方据此回退 2D。 */
  onUnsupported?: (token: DiceRollToken | null) => void
  className?: string
}

export const Dice3DStage = forwardRef<Dice3DHandle, Dice3DStageProps>(function Dice3DStage(
  { kind, onSettled, onUnsupported, className },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<DiceStage | null>(null)
  // 引擎异步加载期间收到的掷骰请求先记下来，加载完补上——否则首次点击会丢。
  const pendingRollRef = useRef<{
    token: DiceRollToken
    targetValue?: number
  } | null>(null)
  const activeRollRef = useRef<DiceRollToken | null>(null)
  const [failed, setFailed] = useState(false)

  // 回调放进 ref：它们的引用变化不应该触发引擎重建（重建会丢掉画面上的骰子）。
  const onSettledRef = useRef(onSettled)
  onSettledRef.current = onSettled
  const onUnsupportedRef = useRef(onUnsupported)
  onUnsupportedRef.current = onUnsupported

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    if (!supports3DDice()) {
      setFailed(true)
      onUnsupportedRef.current?.(null)
      return
    }

    let cancelled = false
    void import('./engine')
      .then(({ createDiceStage }) => {
        if (cancelled) return
        const stage = createDiceStage({
          container,
          kind,
          onSettled: (value) => {
            const token = activeRollRef.current
            activeRollRef.current = null
            if (token !== null) onSettledRef.current(value, token)
          },
        })
        stageRef.current = stage
        const pending = pendingRollRef.current
        if (pending !== null) {
          pendingRollRef.current = null
          activeRollRef.current = pending.token
          if (!stage.roll(pending.targetValue)) activeRollRef.current = null
        }
      })
      .catch(() => {
        if (cancelled) return
        // 加载或初始化失败同样退回 2D，不能把检定卡死在这里。
        const failedToken = activeRollRef.current ?? pendingRollRef.current?.token ?? null
        activeRollRef.current = null
        pendingRollRef.current = null
        setFailed(true)
        onUnsupportedRef.current?.(failedToken)
      })

    return () => {
      cancelled = true
      pendingRollRef.current = null
      activeRollRef.current = null
      stageRef.current?.dispose()
      stageRef.current = null
    }
  }, [kind])

  useImperativeHandle(
    ref,
    () => ({
      roll(token, targetValue) {
        if (failed || pendingRollRef.current !== null || activeRollRef.current !== null) return false
        const stage = stageRef.current
        if (stage) {
          activeRollRef.current = token
          if (!stage.roll(targetValue)) {
            activeRollRef.current = null
            return false
          }
          return true
        }
        pendingRollRef.current = { token, targetValue }
        return true
      },
    }),
    [failed],
  )

  if (failed) return null
  return <div ref={containerRef} className={className} data-testid="dice-3d-stage" />
})
