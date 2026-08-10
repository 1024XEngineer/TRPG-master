import { useEffect, useState } from 'react'
import type { PortraitGenerationResult } from 'trpg-sdk'
import { Image, RefreshCw, Sparkles, X } from 'lucide-react'
import { friendlyErrorMessage } from '@/services/api-client'
import { generateCharacterPortrait } from '@/services/character/portrait-api'

interface PortraitGenerationModalProps {
  roomId: string
  characterId: string
  characterName: string
  result: PortraitGenerationResult | null
  portraitUrl?: string
  onResult: (result: PortraitGenerationResult) => void
  onClose: () => void
}

export function PortraitGenerationModal({
  roomId,
  characterId,
  characterName,
  result,
  portraitUrl,
  onResult,
  onClose,
}: PortraitGenerationModalProps) {
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !generating) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [generating, onClose])

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setError('')
    try {
      onResult(await generateCharacterPortrait(roomId, characterId))
    } catch (err) {
      setError(friendlyErrorMessage(err, '生成人物图片失败，请稍后重试'))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <>
      <div
        className="fixed inset-0 bg-black/55 z-40 animate-fade-in"
        onClick={generating ? undefined : onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="portrait-dialog-title"
        className="fixed inset-x-0 bottom-0 z-50 max-h-[92vh] overflow-y-auto rounded-t-2xl bg-card px-5 pb-7 pt-4 animate-slide-up"
      >
        <div className="mx-auto w-full max-w-md">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h3 id="portrait-dialog-title" className="truncate text-base font-bold text-text-primary">
                {characterName}的人物图片
              </h3>
              <p className="mt-0.5 text-xs text-text-muted">写实肖像 · 1024 × 1024</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={generating}
              aria-label="关闭人物图片生成"
              title="关闭"
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-panel text-text-muted transition-colors disabled:opacity-40"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mx-auto flex aspect-square w-full max-w-[360px] items-center justify-center overflow-hidden rounded-md border border-border-mid bg-panel">
            {generating ? (
              <div className="flex flex-col items-center gap-3 text-text-muted" aria-live="polite">
                <RefreshCw className="h-8 w-8 animate-spin text-brass" />
                <span className="text-sm">正在生成人物图片…</span>
              </div>
            ) : portraitUrl ? (
              <img
                src={portraitUrl}
                alt={`${characterName}的人物图片`}
                className="h-full w-full object-cover"
                onError={() => setError('人物头像加载失败，请稍后重试')}
              />
            ) : (
              <Image className="h-14 w-14 text-text-dim" strokeWidth={1.4} />
            )}
          </div>

          {result && !generating && (
            <div className="mt-4 border-l-2 border-brass px-3">
              <div className="text-[11px] font-semibold text-brass-dark">生成依据</div>
              <p className="mt-1 text-[13px] leading-5 text-text-muted">{result.promptSummary}</p>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-4 text-center text-sm text-[#b43b3b]">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="mt-5 flex min-h-11 w-full items-center justify-center gap-2 rounded-sm bg-brass px-5 py-3 text-sm font-semibold text-white transition-colors active:bg-brass-dark disabled:opacity-50"
          >
            {portraitUrl ? <RefreshCw className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
            {generating ? '生成中…' : portraitUrl ? '重新生成' : '开始生成'}
          </button>
        </div>
      </div>
    </>
  )
}
