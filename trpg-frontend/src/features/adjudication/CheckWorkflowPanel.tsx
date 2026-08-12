import { useState } from 'react'
import { Ban, Dices, RotateCcw, Sparkles } from 'lucide-react'

import type { CheckRunView, PendingCheckDecisionView, PostRollOption } from './types'

const difficultyLabels = {
  regular: '常规难度',
  hard: '困难难度',
  extreme: '极难难度',
} as const

const degreeLabels = {
  critical_success: '大成功',
  extreme_success: '极难成功',
  hard_success: '困难成功',
  regular_success: '成功',
  failure: '失败',
  fumble: '大失败',
} as const

interface CheckWorkflowPanelProps {
  decision?: PendingCheckDecisionView | null
  checkRun?: CheckRunView | null
  busy?: boolean
  onSelectSkill: (candidateId: string) => void
  onCancel: () => void
  onPostRollOption: (optionId: string, revisedMethod?: string) => void
}

function optionLabel(option: PostRollOption): string {
  if (option.kind === 'accept_result') return '接受当前结果'
  if (option.kind === 'spend_resource') return `消耗 ${option.cost} 点幸运`
  return '强推一次'
}

export function CheckWorkflowPanel({
  decision,
  checkRun,
  busy = false,
  onSelectSkill,
  onCancel,
  onPostRollOption,
}: CheckWorkflowPanelProps) {
  const [revisedMethod, setRevisedMethod] = useState('')
  if (!decision && !checkRun) return null

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 px-4 py-6" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="待处理检定"
        className="check-workflow-dialog"
      >
        <div className="check-workflow-dialog__content">
      {decision && (
        <>
          <div className="mb-3 flex items-start gap-2">
            <Dices className="mt-0.5 h-5 w-5 shrink-0 text-brass" aria-hidden="true" />
            <div>
              <h3 className="text-sm font-bold text-text-primary">选择检定方式</h3>
              <p className="mt-0.5 text-xs text-text-muted">{decision.summary}</p>
            </div>
          </div>
          <div className="space-y-2">
            {decision.options.map((option) => (
              <button
                key={option.candidate_id}
                type="button"
                disabled={busy}
                onClick={() => onSelectSkill(option.candidate_id)}
                className="w-full rounded-lg border border-border-light bg-white p-3 text-left disabled:opacity-50"
              >
                <span className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-text-primary">
                    {option.display_name} · {option.target_value}%
                  </span>
                  <span className="text-[11px] text-[#8a642d]">
                    {difficultyLabels[option.difficulty]}
                  </span>
                </span>
                <span className="mt-1 block text-xs text-text-muted">{option.method_summary}</span>
                <span className="mt-1 block text-[11px] text-text-dim">
                  {option.player_safe_reason}
                </span>
              </button>
            ))}
          </div>
          {decision.allow_cancel && (
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-border-light px-3 py-2 text-xs text-text-muted disabled:opacity-50"
            >
              <Ban className="h-3.5 w-3.5" aria-hidden="true" />
              取消行动（不会掷骰）
            </button>
          )}
        </>
      )}

      {checkRun && (
        <>
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#efe2c4] font-mono text-lg font-bold text-[#6f5126]">
              {checkRun.roll.value}
            </div>
            <div>
              <h3 className="text-sm font-bold text-text-primary">
                服务端 D100 · {degreeLabels[checkRun.roll.degree]}
              </h3>
              <p className="text-xs text-text-muted">
                骰点已保存；刷新或重试不会重新投掷
              </p>
            </div>
          </div>
          {checkRun.status === 'awaiting_post_roll_decision' && (
            <div className="mt-3 space-y-2">
              {checkRun.post_roll_options.map((option) => (
                <div key={option.option_id}>
                  {option.kind === 'push' && (
                    <>
                      <label
                        htmlFor={`push-method-${checkRun.check_id}`}
                        className="mb-1 block text-xs font-medium text-text-primary"
                      >
                        说明改变后的做法
                      </label>
                      <textarea
                        id={`push-method-${checkRun.check_id}`}
                        value={revisedMethod}
                        disabled={busy}
                        onChange={(event) => setRevisedMethod(event.target.value)}
                        placeholder="例如：先按年份缩小范围，再重新检索"
                        className="mb-2 min-h-16 w-full rounded-lg border border-border-light bg-white p-2 text-xs"
                      />
                      <p className="mb-2 text-[11px] text-[#9b3f35]">
                        {option.player_safe_risk_summary}
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    disabled={busy || (option.kind === 'push' && !revisedMethod.trim())}
                    onClick={() =>
                      onPostRollOption(
                        option.option_id,
                        option.kind === 'push' ? revisedMethod.trim() : undefined,
                      )
                    }
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-brass px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                  >
                    {option.kind === 'spend_resource' ? (
                      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : option.kind === 'push' ? (
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : null}
                    {optionLabel(option)}
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
        </div>
      </section>
    </div>
  )
}
