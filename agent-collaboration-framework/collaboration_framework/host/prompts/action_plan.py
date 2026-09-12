"""Provider-neutral prompt fragments for finite ActionPlan decisions."""

from collaboration_framework.contracts import ActionPlanPolicy

PROMPT_VERSION = "trpg-host-intent-v10"
TURN_PLANNER_PROMPT_VERSION = "trpg-turn-planner-v3"


def turn_planning_instructions(policy: ActionPlanPolicy) -> str:
    """Describe pure semantic planning with no adjudication authority."""

    return f"""
你只负责把玩家当前输入整理为一个有限、严格顺序的 ActionPlan。

- 对任何可执行输入都返回 action_plan；单一目标必须表示为 steps.length == 1。
- 一个 step 只代表一个需要在执行时重新读取最新 PlayerView 的语义目标。
- 玩家表达两个或更多目标时，一个目标一步，不能吞掉后续目标，也不能把多个动作压成一步。
- 标点，以及“先、再、然后、接着、随后、之后、完成后、并、顺便、还要”等衔接词是
  复查信号，但情绪、姿态、语气、速度和环境描写通常只是相邻动作的限定。
- “去某处做某事”是隐式顺序：先生成 travel，再为到达后的 rest、dialogue、action 或
  wait 生成独立步骤。不得预判目的地中的人物、物品、状态或结果。
- “拽着、扶着、背着、让某人跟随”等都是尝试，不代表 NPC 已经同意或随行。
  人不在场时，只能依据公开位置先会合；不知位置时保留寻找目标，不得猜测隐藏位置。
  当前公开状态尚未随行时，“带人去某处”应先尝试建立同行，再前往目的地；已在随行的
  人无需重复建立。否定、解除同行和玩家明确要求的目的地必须保留，不得改写成肯定行动。
- step.kind 只能是 travel、wait、rest、action、dialogue；步骤不得分支、循环、并行或动态追加。
- plan.goal、semantic_goal 和 public_progress_label 必须完全玩家安全，只描述玩家希望完成的事。
- 玩家明确说出的 PlayerView 公开地点、人物、物件名称或别名，以及动作限定词，必须在对应
  semantic_goal 中保留足以让后续基于最新 PlayerView 唯一识别目标的公开文字。不得把明确名称
  泛化成“眼前的人”“那里”或其他会丢失唯一识别线索的说法；玩家原本只使用代词时才保留代词。
- 公开文字锚点只能来自玩家输入或 PlayerView 的公开字段；不得补写 Keeper-only 名称、目标 ID、
  裁决、效果、检定或任何隐藏信息，也不得用相似名称替换玩家明确指定的目标。
- 严格只输出 ActionPlan schema 已声明的字段；不得添加执行细节、对象标识、规则结论、
  隐藏信息或未来结果。
- 当前技术上限是 {policy.max_plan_steps} 步。超过上限时不得截断或假装完成，应请求玩家缩小目标。
- 无法可靠拆分时，用一个保持玩家原意的语义步骤交给后续安全边界处理，绝不能补写隐藏事实。
""".strip()


def host_turn_decision_instructions(policy: ActionPlanPolicy) -> str:
    """Describe product semantics without turning the soft window into a step cap."""

    return f"""
将玩家当前输入按可独立裁决的目标数量整理为 single_action 或 action_plan。
单一目标返回 single_action 和 ActionAdjudication；多个目标返回 action_plan，一个目标一步。
依据动作语义划分；标点、衔接词与连续动词是复查信号，情绪、姿态、语气、速度、意愿和
环境描写通常只是限定，不单独成步。需要前一步改变位置、持有物或交互状态后才能执行的
动作仍是独立目标，不能因省略连词或位于句末而丢失；到另一地点做事应先 travel 再执行后续目标。
各步执行时读取最新 PlayerView，不预判未来人物、物品或结果，不用 summary 代替后续执行。

action_plan.steps 只保存玩家安全的 semantic_goal，保留原话明确的公开目标和限定条件；
不写 ID、裁决、效果、检定结果、revision 或隐藏信息。kind 仅为 travel、wait、rest、action、dialogue。
步骤严格顺序，不分支、循环、并行或动态追加；3 步只是默认推进窗口，绝对上限为
{policy.max_plan_steps} 步。超限或无法安全切分时请求澄清，不截断或假装完成。

player_input.interlocutor_id / interlocutor_name 指定当前可见的 NPC，不表示跳过社交裁决。
同句话混合对 NPC 的发言与其他明确的立即行动时，先澄清整句，不自动拆成两次执行。
""".strip()


def current_step_adjudication_instructions() -> str:
    """Step-specific scope; the adapter appends the shared adjudication contract once."""

    return """
只裁决当前 ActionPlan step，以本次最新 PlayerView 为准，不预读、裁决或描述未来步骤。
request_id、source_revision、actor_id 由应用层注入，输出不能改变身份。
按 ActionAdjudication 契约返回检定与结果，需要玩家选择时停在当前步骤。
step.kind 只表示语义目标类型，不绕过规则匹配，也不免除应提交的持久效果。
后续步骤依据实际提交结果和新视图继续，不把计划目标当成事实。

previous_rejection 是同一步骤上次裁决的引擎拒绝原因。根据具体错误给出修正后的完整裁决，
不重复错误，不改变步骤语义，也不为绕开校验丢掉仍然适用的规则或检定。
PERSISTENT_EFFECT_REQUIRED 且目标无承载该结果的权威状态位时，保持 target、method、check，
将 persistence_intent 收窄为 none，效果留空或 narrative_only，不伪造状态键或取消必要检定。
""".strip()
