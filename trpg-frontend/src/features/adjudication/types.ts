export type CheckDifficulty = 'regular' | 'hard' | 'extreme'

export type CheckDegree =
  | 'critical_success'
  | 'extreme_success'
  | 'hard_success'
  | 'regular_success'
  | 'failure'
  | 'fumble'

export interface PendingCheckOption {
  candidate_id: string
  skill_id: string
  display_name: string
  target_value: number
  difficulty: CheckDifficulty
  method_summary: string
  player_safe_reason: string
}

export interface PendingCheckDecisionView {
  decision_id: string
  status: 'awaiting_skill_choice'
  action_request_id: string
  source_revision: string
  decision_version: number
  actor_id: string
  summary: string
  options: PendingCheckOption[]
  // false 表示这次检定由规则强制：没有取消路由，玩家只能掷。
  allow_cancel: boolean
}

export interface CheckRoll {
  value: number
  degree: CheckDegree
  passed: boolean
}

export type PostRollOption =
  | { option_id: string; kind: 'accept_result' }
  | {
      option_id: string
      kind: 'spend_resource'
      resource_id: 'luck'
      cost: number
      result_degree: CheckDegree
    }
  | {
      option_id: string
      kind: 'push'
      requires_revised_method: true
      player_safe_risk_summary: string
    }

export interface CheckRunView {
  check_id: string
  action_request_id: string
  selected_candidate_id: string
  status: 'awaiting_post_roll_decision' | 'resolved'
  version: number
  roll_count: number
  roll: CheckRoll
  post_roll_options: PostRollOption[]
  final_result: CheckRoll | null
}
