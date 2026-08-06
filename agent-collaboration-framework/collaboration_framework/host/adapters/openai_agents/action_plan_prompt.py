"""Provider-neutral prompt fragments for finite ActionPlan decisions."""

from collaboration_framework.contracts import ActionPlanPolicy


def host_turn_decision_instructions(policy: ActionPlanPolicy) -> str:
    """Describe product semantics without turning the soft window into a step cap."""

    return f"""
你需要把玩家当前输入判断为 single_action 或 action_plan。

- 单一目标必须返回 single_action 和一个 ActionAdjudication。
- 只有包含两个或更多、且后一步依赖前一步状态的明确目标，才返回 action_plan。
- action_plan.steps 只保存玩家安全的 semantic_goal；不得保存未来 ActionAdjudication、
  ActionEffect、检定结果、隐藏信息、ID、revision、status 或推理。
- step.kind 只能是 travel、wait、rest、action、dialogue。
- 步骤严格顺序，不得输出分支、循环、并行或动态追加。
- 计划可以超过 3 步；3 只是服务端默认推进窗口，不是玩家能力上限。
- 当前绝对技术安全上限是 {policy.max_plan_steps} 步。若玩家明确目标超过该上限，
  不得截断或假装完成，应该请求玩家拆分或缩小目标。
- 无法安全切分时请求澄清，不能丢失玩家表达的后续目标。
""".strip()


def current_step_adjudication_instructions() -> str:
    return """
你只裁决当前 ActionPlan step。必须以提供的最新 PlayerView 为准，不得预读、裁决或
描述未来步骤。request_id、source_revision、actor_id 由应用层注入；你的输出不能改变
这些身份字段。当前步骤需要检定或玩家选择时，按单意图 ActionAdjudication 契约返回，
不得自行继续后续步骤。
""".strip()
