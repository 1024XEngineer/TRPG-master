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

target.id 只能逐字取自这几处，不要自造：keeper_capabilities 的 entities / locations /
information；keeper_capabilities.world_id；player_view.scene.id；以及局内角色——
player_view.self_actor.id（玩家自己）和 player_view.scene.visible_actors[].id（同场其他
玩家角色），这两类用 kind=actor。玩家帮助、攻击或以别的方式作用于同伴时，目标就是那个
actor id，不要退而求其次改用 location 或 world。

玩家问时间、问天气、只是应答或闲聊，没有具体对象可指时，才用 kind=world +
keeper_capabilities.world_id，或 kind=location + player_view.scene.id；world 只认
world_id 这一个值，不要自己拼一个像 "world" 的 id。

rule_decision 是可选的。keeper_capabilities.rule_candidates 是按玩家当前所在地发布的，
一条候选还可能声明 action_families、target_kinds、target_ids 作为额外约束：**这三个字段
为空表示该维度不设限，非空才要求本次裁决落在其中**。逐个字段判断，非空的都命中才能选它。
玩家的话对不上任何一条候选（例如只是打个招呼）时，不要硬套一条规则，直接不带
rule_decision 按普通裁决给出这一步。

这一步提到的对象在当前 PlayerView 里根本不存在时（计划是在更早的 revision 上写的，
它提到的物品或人物可能这里没有），通常不要凭空造一个 id，也不要把别的 id 硬套成
需要的 kind：以 kind=location + player_view.scene.id 为目标，返回 narrative_only，并
在 summary 里如实说明当前看不到该对象。

例外是符合 WorldProfile、且不承载剧情秘密的普通动态内容：玩家泛指一家旅店、餐馆等
现实中合理存在的地点时，可按 ensure_runtime_location 协议创建并进入；当前场景按常识
应有普通工作人员、路人或无关紧要的可携带物品时，可按 ensure_runtime_entity 协议创建。
创建普通物品后，拾取要在同一 effects 序列继续 move_entity 到 actor；投掷或放置已有物品
要 move_entity 到当前 location；一次性物品用尽才 consume_entity。不要仅因玩家没有指定店名而要求澄清，
也不要仅因缺少普通 NPC 姓名或普通物件预存 id 而澄清。隐藏 Canon 地点、关键人物、
关键道具、秘密入口或玩家声称的剧情事实不属于例外，仍不得创建或确认其存在。

输入里出现 previous_rejection 时，说明规则引擎刚刚拒绝了你对**同一个步骤**给出的上
一份裁决，字段内容就是它给出的拒绝原因。这是有限修复预算内的一次修正机会：先按该原因定位问
题（最常见的是 target.kind 与 target.id 不配套，或引用了 PlayerView 里并不存在的对
象），然后给出一份改正后的完整裁决，不要原样重复上一份，也不要因此改写这一步的语义
目标。
""".strip()
