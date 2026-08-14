/** 角色生图任务弹窗：关闭不取消，任务状态始终以服务端快照为准。 */
import { useEffect, useState } from 'react'
import { Image, RefreshCw, Sparkles, Square, X } from 'lucide-react'
import { friendlyErrorMessage } from '@/services/api-client'
import { cancelCharacterPortrait, createCharacterPortrait } from '@/services/character/portrait-api'
import { isPortraitTaskActive, portraitTaskKey, usePortraitGenerationStore } from '@/stores/portrait-generation-store'

interface Props { roomId: string; characterId: string; characterName: string; portraitUrl?: string; onClose: () => void }

export function PortraitGenerationModal({ roomId, characterId, characterName, portraitUrl, onClose }: Props) {
  const key = portraitTaskKey(roomId, characterId)
  const task = usePortraitGenerationStore((s) => s.tasks[key])
  const cancelling = usePortraitGenerationStore((s) => s.cancelling[key] ?? false)
  const setTask = usePortraitGenerationStore((s) => s.setTask)
  const setCancelling = usePortraitGenerationStore((s) => s.setCancelling)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const active = isPortraitTaskActive(task)

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [onClose])

  const generate = async () => {
    if (active || submitting) return
    setSubmitting(true); setError('')
    try { setTask(roomId, characterId, await createCharacterPortrait(roomId, characterId)) }
    catch (reason) { setError(friendlyErrorMessage(reason, '生成人物图片失败，请稍后重试')) }
    finally { setSubmitting(false) }
  }
  const cancel = async () => {
    if (!task || cancelling || task.status === 'cancelling') return
    setCancelling(roomId, characterId, true); setError('')
    try { setTask(roomId, characterId, await cancelCharacterPortrait(roomId, characterId, task.generationId)) }
    catch (reason) { setError(friendlyErrorMessage(reason, '终止生成失败，请稍后重试')) }
    finally { setCancelling(roomId, characterId, false) }
  }

  const status = task?.status === 'cancelling' || cancelling ? '终止中…'
    : active ? '正在生成人物图片…' : task?.status === 'cancelled' ? '本次生成已终止'
      : task?.status === 'failed' ? '本次生成失败，可重新尝试' : ''
  return <>
    <div className="fixed inset-0 bg-black/55 z-40 animate-fade-in" onClick={onClose} aria-hidden="true" />
    <div role="dialog" aria-modal="true" aria-labelledby="portrait-dialog-title" className="portrait-generation-modal fixed inset-x-0 bottom-0 z-50 max-h-[92vh] overflow-y-auto animate-slide-up">
      <div className="mx-auto w-full max-w-md">
        <div className="portrait-generation-modal__header mb-4 flex items-center justify-between gap-3">
          <div><h3 id="portrait-dialog-title" className="font-bold text-text-primary">{characterName}的人物图片</h3><p className="mt-0.5 text-text-muted">写实肖像 · 1024 × 1024</p></div>
          <button type="button" onClick={onClose} aria-label="关闭窗口，生成将在后台继续" title="关闭窗口（不会终止生成）" className="flex h-8 w-8 items-center justify-center rounded-full bg-panel"><X className="h-4 w-4" /></button>
        </div>
        <div className="mx-auto flex aspect-square w-full max-w-[360px] items-center justify-center overflow-hidden rounded-md border border-border-mid bg-panel">
          {active ? <div className="flex flex-col items-center gap-3 text-text-muted" aria-live="polite"><RefreshCw className="h-8 w-8 animate-spin text-brass" /><span>{status}</span></div>
            : portraitUrl ? <img src={portraitUrl} alt={`${characterName}的人物图片`} className="h-full w-full object-cover" />
              : <Image className="h-14 w-14 text-text-dim" />}
        </div>
        {task?.promptSummary && <div className="mt-4 border-l-2 border-brass px-3"><div className="font-semibold text-brass-dark">生成依据</div><p className="mt-1 text-text-muted">{task.promptSummary}</p></div>}
        {!active && status && <p className="mt-4 text-center text-text-muted" aria-live="polite">{status}</p>}
        {active && <p className="mt-3 text-center text-xs text-text-muted">关闭窗口不会终止任务，进入游戏后仍会继续生成</p>}
        {error && <p role="alert" className="mt-4 text-center text-[#b43b3b]">{error}</p>}
        <button type="button" onClick={active ? cancel : generate} disabled={submitting || cancelling || task?.status === 'cancelling'} className="mt-5 flex min-h-11 w-full items-center justify-center gap-2 rounded-sm bg-brass px-5 py-3 font-semibold text-white disabled:opacity-50">
          {active ? <Square className="h-4 w-4" /> : portraitUrl ? <RefreshCw className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
          {task?.status === 'cancelling' || cancelling ? '终止中…' : active ? '终止生成' : submitting ? '提交中…' : portraitUrl ? '重新生成' : '开始生成'}
        </button>
      </div>
    </div>
  </>
}
