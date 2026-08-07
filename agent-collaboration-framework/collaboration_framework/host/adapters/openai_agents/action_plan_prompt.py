"""Provider-neutral prompt fragments for finite ActionPlan decisions."""

from collaboration_framework.contracts import ActionPlanPolicy


def host_turn_decision_instructions(policy: ActionPlanPolicy) -> str:
    """Describe product semantics without turning the soft window into a step cap."""

    return f"""
你需要把玩家当前输入判断为 single_action 或 action_plan。

- 单一目标必须返回 single_action 和一个 ActionAdjudication。
- 玩家一次说出两个或更多有明确先后顺序的目标时，必须返回 action_plan，一个目标一步。
  “先 A 然后 B”“先 A 再 B”“A 完了去 B”都属于这种情况，即使 B 不依赖 A 的结果，
  也不能合并成一个 single_action——每一步都要单独按当时最新的 PlayerView 裁决。
- 判断依据是玩家表达了几个目标，不是这些目标看起来有多小、多容易一起完成。
- 只有确实只表达了一个目标时才返回 single_action。
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

这一步提到的对象在当前 PlayerView 里根本不存在时（计划是在更早的 revision 上写的，
它提到的物品或人物可能这里没有），不要凭空造一个 id，也不要把别的 id 硬套成需要的
kind：以 kind=location + player_view.scene.id 为目标，返回 narrative_only，并在
summary 里如实说明当前看不到该对象。这只是本步骤的降级处理，不影响后续步骤。

输入里出现 previous_rejection 时，说明规则引擎刚刚拒绝了你对**同一个步骤**给出的上
一份裁决，字段内容就是它给出的拒绝原因。这是你唯一一次修正机会：先按该原因定位问
题（最常见的是 target.kind 与 target.id 不配套，或引用了 PlayerView 里并不存在的对
象），然后给出一份改正后的完整裁决，不要原样重复上一份，也不要因此改写这一步的语义
目标。
""".strip()
