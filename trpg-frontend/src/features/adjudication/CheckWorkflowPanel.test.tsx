import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CheckWorkflowPanel } from './CheckWorkflowPanel'
import type { CheckRunView, PendingCheckDecisionView } from './types'

const decision: PendingCheckDecisionView = {
  decision_id: 'decision-1',
  status: 'awaiting_skill_choice',
  action_request_id: 'action-1',
  source_revision: '42',
  decision_version: 1,
  actor_id: 'actor-1',
  summary: '查找旧报中与墓地有关的记录',
  allow_cancel: true,
  options: [
    {
      candidate_id: 'library',
      skill_id: 'library-use',
      display_name: '图书馆使用',
      target_value: 60,
      difficulty: 'regular',
      method_summary: '按目录系统检索馆藏与旧报',
      player_safe_reason: '侧重系统检索和资料整理',
    },
    {
      candidate_id: 'spot',
      skill_id: 'spot-hidden',
      display_name: '侦查',
      target_value: 50,
      difficulty: 'hard',
      method_summary: '直接在旧报架中寻找异常记录',
      player_safe_reason: '侧重从大量材料中发现显眼细节',
    },
  ],
}

describe('CheckWorkflowPanel', () => {
  it('shows safe skill choices and lets the player cancel before rolling', () => {
    const onSelect = vi.fn()
    const onCancel = vi.fn()
    render(
      <CheckWorkflowPanel
        decision={decision}
        onSelectSkill={onSelect}
        onCancel={onCancel}
        onPostRollOption={vi.fn()}
      />,
    )

    expect(screen.getByRole('dialog', { name: '待处理检定' })).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('图书馆使用 · 60%')).toBeInTheDocument()
    expect(screen.getByText('侧重从大量材料中发现显眼细节')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /侦查/ }))
    fireEvent.click(screen.getByRole('button', { name: /取消行动/ }))

    expect(onSelect).toHaveBeenCalledWith('spot')
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('shows the authoritative roll and only enables push after a revised method', () => {
    const onPostRoll = vi.fn()
    const checkRun: CheckRunView = {
      check_id: 'check-1',
      action_request_id: 'action-1',
      selected_candidate_id: 'library',
      status: 'awaiting_post_roll_decision',
      version: 1,
      roll_count: 1,
      roll: { value: 64, degree: 'failure', passed: false },
      final_result: null,
      post_roll_options: [
        { option_id: 'accept-current', kind: 'accept_result' },
        {
          option_id: 'spend-luck-4',
          kind: 'spend_resource',
          resource_id: 'luck',
          cost: 4,
          result_degree: 'regular_success',
        },
        {
          option_id: 'push-once',
          kind: 'push',
          requires_revised_method: true,
          player_safe_risk_summary: '再次尝试会承担更严重的失败后果',
        },
      ],
    }
    render(
      <CheckWorkflowPanel
        checkRun={checkRun}
        onSelectSkill={vi.fn()}
        onCancel={vi.fn()}
        onPostRollOption={onPostRoll}
      />,
    )

    expect(screen.getByText('服务端 D100 · 失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '消耗 4 点幸运' })).toBeEnabled()
    const push = screen.getByRole('button', { name: '强推一次' })
    expect(push).toBeDisabled()
    fireEvent.change(screen.getByLabelText('说明改变后的做法'), {
      target: { value: '先按年份缩小范围后重新检索' },
    })
    fireEvent.click(push)

    expect(onPostRoll).toHaveBeenCalledWith(
      'push-once',
      '先按年份缩小范围后重新检索',
    )
  })
})
