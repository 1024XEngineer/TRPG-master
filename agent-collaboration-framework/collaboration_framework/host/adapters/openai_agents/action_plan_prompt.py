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
- 在选择 kind 前必须先在内部识别玩家原话中的动作谓词，并拆出候选动作单元；不要输出
  分析过程。标点、衔接词和多个动词都是强制复查信号，但不能机械地据此拆分。只要原话
  出现逗号、顿号、分号、句号等中英文标点，或“先、再、然后、接着、随后、之后、完成后、
  并、并且、同时、顺便、还要”等衔接词，就必须逐段判断是否包含可独立裁决的动作目标。
- 必须区分可独立裁决的行动和纯叙事限定。移动、等待、休息、对话、观察、调查、操作、
  拾取、转交、使用、攻击等需要单独读取 PlayerView、选择目标、进行检定或产生效果的行为，
  属于可独立裁决的行动。“想、准备、打算、决定、尝试”等意愿表达，以及情绪、姿态、
  语气、速度和环境描写，通常只是相邻行动的限定，不得单独生成步骤；“拿起、取出、走进、
  抵达”等完整动作词或方向、结果补语也不能按字面拆成多个目标。
- “去某处做某事”是隐式顺序结构：当玩家表达“去、前往、进入、到达某个地点”，并继续
  表达一个需要到达后才能执行的动作时，即使中间没有标点或衔接词，也必须返回 action_plan。
  第一步是 travel，后续动作按语义使用 rest、dialogue、action、wait 等 kind，并且必须等
  旅行完成、刷新 PlayerView 后再裁决；不得在一个 single_action 中预判目的地内的人物、
  物品、状态或结果。
- 候选动作中只有一个可独立裁决的目标时才返回 single_action；存在两个或更多时必须返回
  action_plan，一个可执行目标一步，纯叙事成分不得占用独立步骤。输出 single_action 前必须
  再次确认不存在能在前一行动完成后独立执行的后续动作，不能只执行其中一项，也不能靠
  summary 复述整句来代替执行其他目标。
- 句末动词如果只能在前一动作改变地点、持有物或交互状态后才能执行，
  它仍是独立目标；相邻书写、省略连词、作为目的表达，都不能将其吸收进前一步。
  尤其要逐个保留“前置交互 + 等待/休息/使用/继续操作”中的每个可执行动词。
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

**明确旅行地点决策表（优先于后文所有“目标不存在”处理）**：当 step.kind=travel
且玩家直接指定了目的地类型时，只能选下列三个分支之一：

1. 有语义明确匹配的已有地点：复用其 id，按公开路径 enter_location。
2. PlayerView 和 keeper_capabilities.locations 都没有匹配项，但该类地点符合
   WorldProfile / background，且不与 Canon 或隐藏剧情事实冲突：**必须**返回
   persistence_intent=location，并依次提交 ensure_runtime_location、enter_location。
3. 与 WorldProfile / background / forbidden_content 冲突，或与已写 Canon 地点、秘密入口、
   隐藏路线冲突：返回 narrative_only，不移动。

不存在“因为列表里没有，所以无法确认该地点”的第四个分支。列表缺失正是必须
进入分支 2 做背景判定的触发条件，不是拒绝理由。新地点还未创建，target 必须使用一个
已有公开连接锚点，新 id 只出现在上述两个 effects 中。

**明确取得物品决策表（同样优先于后文“目标不存在”处理）**：玩家要捡起、拿走、收好或
放入背包时，只能选下列分支：

1. scene.loose_items 或 inventory 有语义明确匹配且归宿相容的 ItemInstance：复用其 id，按
   本次行动执行 move_entity / consume_entity。
2. 没有权威实例，但同一连续场景的 published_narration、scene、location_context 或环境常识
   支持该类型内容自然在场，且它通过世界一致性、普通性、零剧情权限及 Canon 不替代门禁：
   **必须**按 ensure_runtime_entity(entity_kind=object)、move_entity(holder_actor_id=actor)
   的顺序创建并取得。叙事没有预先建立“某一个具体实体 id”正是此分支要解决的问题，不是拒绝理由。
3. 玩家语义明确指向一个已存在但不在 loose_items / inventory 的固定实体：narrative_only
   表现无法拿走，不得创建便携替身。
4. 软场景依据不足，或候选未通过安全门禁：narrative_only，不得声称进入背包。

不存在“叙事提过这种普通物品，但没有具体实体所以只能留在原处”的第五个分支；若分支 2 的
全部条件满足，必须创建。新 id 仍只出现在 effects 中，target 使用当前 scene location。

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

候选 id 出现在 PlayerView 中只代表协议允许引用，不代表它与玩家原话语义匹配。玩家本回合
明确指定的地点或对象没有匹配项时，绝不能为了得到合法 id 而改用当前 scene、相似类型或其他
已知地点，也不能把玩家要求在别处进行的休息、等待、交互或操作改成在当前位置执行。符合通用
创建门禁时只能创建玩家实际指定的类型；不能安全创建时，当前 scene.id 只能作为 narrative_only
的零写入范围 target，并在 summary 中如实说明目标无法确认或到达，不得进入替代地点、推进时间，
或暗示行动已经在那里完成。

recent_history 主要用于解析省略的指代和对话承接，不能覆盖玩家本回合明确指定的对象、地点、
类型和限定条件，也不能把过去玩家主张、语义摘要或叙事文本里的相似对象当成本回合目标。
唯一的软场景用途是：同一连续场景中已发布的 published_narration 若描述了普通环境物品，玩家
现在明确要取得它，该描述可与 scene、location_context、环境常识共同支持“这种普通物品自然
在场”的 Runtime 创建判断；它不建立实体 id、不证明所有权，也不能支持秘密、线索、钥匙、
危险品或其他受限内容。通过门禁后必须新建 ItemInstance，再 move_entity，不能把叙事名词硬套
到名称相近的 Canon 实体。

这次检查只决定“复用已有对象”还是“评估 Runtime 创建候选”。列表没有预存某个具体实例，
正是 ensure_runtime_entity / ensure_runtime_location 要处理的情况，不能单独作为
narrative_only 的理由；没有匹配项时必须继续执行下面的通用创建门禁。

这一步提到的非地点对象在当前 PlayerView 里根本不存在时（计划是在更早的 revision 上写的，
它提到的物品或人物可能这里没有），不要把别的 id 硬套成需要的 kind。先完整执行上述取得物品
决策表和后文 Runtime 门禁：符合条件的日常内容必须 ensure_runtime_entity；只有不符合创建
条件时，才以 kind=location + player_view.scene.id 为目标返回 narrative_only，并在 summary
里如实说明当前看不到或无法取得该对象。keeper_capabilities 里的实体不代表玩家此刻看得见
或拿得到；它不能取代上述 PlayerView 检查。地点不适用本段，必须按旅行地点决策表处理。

地点与人物/物件必须分别使用下列门禁，不得把人物和可携带物件的
“低价值、低风险、无专业性”要求套到地点上。

**Runtime 地点门禁**：

1. 先检查 PlayerView 和 keeper_capabilities.locations；只有玩家指定的地点与已有
   Canon / Runtime 地点都不匹配时，才评估新建。与隐藏 Canon 地点同名或同一语义的
   候选不得创建替身，也不得泄露该 Canon 地点。
2. 读取 keeper_capabilities.world_profile 的 era、region、technology_level、tone 与
   forbidden_content，并结合 background 判断该类地点是否可以在当前世界和所在地区
   合理存在。当前 scene 没有预先写出它、模组没有穷举该地区的设施，都不是拒绝
   依据；地点的功能类别、规模或专业性本身也不构成拒绝理由。
3. 创建只确立该地点的公开外壳、背景相容的名称，以及与一个已知公开连接点的
   普通连接。不得在创建地点时一并确认内部人物、可用服务、物品、床位、访问权限、
   信息、证据、线索、秘密入口、隐藏路线、捷径或结局能力；后续行动必须基于刷新后的
   PlayerView 另行裁决。
4. 若模组未提及该地点、其存在符合上述 WorldProfile / background，且不与 Canon
   冲突或夹带隐藏剧情事实，就必须按 ensure_runtime_location、enter_location 的顺序创建
   并进入；不能因为列表里原先没有它而退回 narrative_only 或要求澄清。

**Runtime 人物/物件门禁**：

1. **世界一致性**：候选内容必须与 WorldProfile / background 相容。
2. **场景依据**：当前 scene 的公开描述、location_context、不依赖隐藏事实的环境常识，或同一
   连续场景中已经发布的 published_narration，必须足以支持该类型内容自然在场。
   published_narration 只是普通内容的软场景依据，不是权威实体或剧情事实。
3. **普通性**：只允许常见、低价值、低风险、可替代、无唯一身份的日常人物或可携带物件；
   需要专业来源、受管制获取、显著财富、危险能力或罕见技术的内容不得创建。
4. **零剧情权限**：不得创建或暗示信息、证据、线索、任务物、钥匙、特殊武器、稀有资源、
   关键 NPC 或任何会改变风险、可达性、调查结论及结局的能力。
5. **Canon 不替代**：不得冒充、复制、改写或提前显现 Canon 实体。

任一项不满足就返回 narrative_only；全部通过时必须按 ensure_runtime_entity 协议创建。
创建普通物品后，拾取要在同一 effects 序列继续 move_entity 到 actor；投掷或放置已有物品
要 move_entity 到当前 location；新建物品尚不是合法 target，target 必须继续使用当前已有
scene location，新 id 只出现在 ensure_runtime_entity 及紧随其后的 move_entity 中。一次性
物品用尽才 consume_entity。不要仅因玩家没有指定普通内容的具体名称或实例而要求澄清，
也不要仅因缺少普通 NPC 姓名或普通物件预存 id 而澄清。隐藏 Canon 地点、关键人物、
关键道具、秘密入口或玩家声称的剧情事实不属于例外，仍不得创建或确认其存在。

move_entity(holder_actor_id=...) 只能引用 scene.loose_items、inventory，或同一 effects 序列
刚创建的 Runtime object；scene.visible_entities 或 keeper_capabilities.entities 中的固定实体
不能因此进入背包。玩家明确指向现有但不可携带的实体时，用 narrative_only 如实表现拿不走，
不得创建便携替身；若上一版只是把普通软场景物品错配到不相干实体，则重新执行上述 Runtime
门禁，通过后创建新物品并移动。

输入里出现 previous_rejection 时，说明规则引擎刚刚拒绝了你对**同一个步骤**给出的上
一份裁决，字段内容就是它给出的拒绝原因。这是有限修复预算内的一次修正机会：先按该原因定位问
题（最常见的是 target.kind 与 target.id 不配套，或引用了 PlayerView 里并不存在的对
象），然后给出一份改正后的完整裁决，不要原样重复上一份，也不要因此改写这一步的语义
目标。
""".strip()
