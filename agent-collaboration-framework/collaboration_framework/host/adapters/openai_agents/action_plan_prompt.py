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

target.id 必须是玩家当前能够直接作用的目标：entity 只取自 scene.visible_entities、
scene.loose_items 或 inventory；location 只取自 scene.id、已知且已定位的 known_locations，
或 available_exits 的 destination；information 只取自 known_information；actor 只取自
player_view.self_actor.id（玩家自己）或 scene.visible_actors[].id（同场其他玩家角色）；world
只使用 keeper_capabilities.world_id。keeper_capabilities 的 entities / locations / information
是效果能力词表，不自动成为可直接作用的 target；唯一例外是命中 rule_decision 时逐字使用该
候选明确给出的 target_ids。玩家帮助、攻击或以别的方式作用于同伴时，目标就是那个 actor id，
不要退而求其次改用 location 或 world。

玩家问时间、问天气、只是应答或闲聊，没有具体对象可指时，才用 kind=world +
keeper_capabilities.world_id，或 kind=location + player_view.scene.id；world 只认
world_id 这一个值，不要自己拼一个像 "world" 的 id。

rule_decision 是可选的。keeper_capabilities.rule_candidates 是按玩家当前所在地发布的，
一条候选还可能声明 action_families、target_kinds、target_ids 作为额外约束：**这三个字段
为空表示该维度不设限，非空才要求本次裁决落在其中**。逐个字段判断，非空的都命中才能选它。
玩家的话对不上任何一条候选（例如只是打个招呼）时，不要硬套一条规则，直接不带
rule_decision 按普通裁决给出这一步。

裁决任何物品、人物或地点前，第一步必须先逐项检查当前 PlayerView：scene.visible_entities、
scene.loose_items、inventory、scene.id、known_locations 和 available_exits。只有玩家说法与某个
已有对象的 id、名称或别名明确匹配，且对象类别、数量、所有者、唯一性、状态以及玩家说出的
限定属性都相容时才能复用它；共享一个上位类别或部分词语不构成同一实体。

这次检查只决定“复用已有对象”还是“评估 Runtime 创建候选”。列表没有预存某个具体实例，
正是 ensure_runtime_entity / ensure_runtime_location 要处理的情况，不能单独作为
narrative_only 的理由；没有匹配项时必须继续执行下面的通用创建门禁。

这一步提到的对象在当前 PlayerView 里根本不存在时（计划是在更早的 revision 上写的，
它提到的物品或人物可能这里没有），通常不要凭空造一个 id，也不要把别的 id 硬套成
需要的 kind：以 kind=location + player_view.scene.id 为目标，返回 narrative_only，并
在 summary 里如实说明当前看不到该对象。keeper_capabilities 里的实体不代表玩家此刻看得见
或拿得到；它不能取代上述 PlayerView 检查。

例外是符合 WorldProfile、且不承载剧情秘密的普通动态内容：玩家泛指一家旅店、餐馆等
现实中合理存在的地点时，可按 ensure_runtime_location 协议创建并进入。创建任何 Runtime 内容
前必须逐项通过下面的通用门禁，任一项不满足就返回 narrative_only，不得自行降低标准：

1. **世界一致性**：读取 keeper_capabilities.world_profile 的 era、region、technology_level、
   tone 与 forbidden_content；候选内容必须在相应时代、地区和技术条件下常见且合理，并遵守禁用
   内容。world_profile 缺失时只能依赖明确的 background，不得猜测现代技术或特殊社会条件。
2. **场景依据**：当前 scene 的名称、公开描述、location_context 或不依赖隐藏事实的环境常识，
   必须足以支持该类型内容自然在场；这里判断的是类型与环境的关系，不要求某个具体实例已有 id，
   列表未列出实例不是反证。玩家在话语中单方面声称它存在不算依据。场景描述无需穷举每件日常
   陈设，但候选内容不能与地点用途、自然环境或当前已知状态冲突。
3. **普通性**：只允许常见、低价值、低风险、可替代、无唯一身份的日常人物或可携带物件。需要
   专业来源、受管制获取、显著财富、危险能力或罕见技术的内容不属于普通动态内容。
4. **零剧情权限**：不得创建或暗示信息、证据、线索、任务物、钥匙、特殊武器、稀有资源、关键
   NPC、秘密入口、新路线、捷径或任何会改变风险、可达性、调查结论及结局的能力。
5. **Canon 不替代**：Runtime 内容不得冒充、复制、改写或提前显现 Canon 实体；已有实体只有通过
   上述完整指称匹配时才能复用，不能仅凭类别相近就移动或消费。

全部通过时必须按 ensure_runtime_location / ensure_runtime_entity 协议创建，不能因为列表中原先
没有该实例而退回 narrative_only。
创建普通物品后，拾取要在同一 effects 序列继续 move_entity 到 actor；投掷或放置已有物品
要 move_entity 到当前 location；新建物品尚不是合法 target，target 必须继续使用当前已有
scene location，新 id 只出现在 ensure_runtime_entity 及紧随其后的 move_entity 中。一次性
物品用尽才 consume_entity。不要仅因玩家没有指定店名而要求澄清，
也不要仅因缺少普通 NPC 姓名或普通物件预存 id 而澄清。隐藏 Canon 地点、关键人物、
关键道具、秘密入口或玩家声称的剧情事实不属于例外，仍不得创建或确认其存在。

输入里出现 previous_rejection 时，说明规则引擎刚刚拒绝了你对**同一个步骤**给出的上
一份裁决，字段内容就是它给出的拒绝原因。这是有限修复预算内的一次修正机会：先按该原因定位问
题（最常见的是 target.kind 与 target.id 不配套，或引用了 PlayerView 里并不存在的对
象），然后给出一份改正后的完整裁决，不要原样重复上一份，也不要因此改写这一步的语义
目标。
""".strip()
