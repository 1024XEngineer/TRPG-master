"""Minimal structured-output compatibility Host and strict Narrator adapters."""

from __future__ import annotations

import json
import time
from typing import Protocol

import httpx
import structlog
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlan,
    ActionPlanPolicy,
    ContractError,
    HostTurnDecision,
    JsonObject,
)
from collaboration_framework.host.application import (
    HostTurnDecisionParser,
    TurnExecutionError,
)
from collaboration_framework.host.prompts.action_plan import (
    current_step_adjudication_instructions,
    host_turn_decision_instructions,
    turn_planning_instructions,
)
from collaboration_framework.host.schemas import (
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
    ActionPlanStepContext,
    HostAgentContext,
    NarrationOutput,
    OpeningNarrationContext,
    TurnPlanningContext,
)
from pydantic import TypeAdapter, ValidationError

from app.adapters.structured_http import (
    ModelCallTrace,
    ModelClientRetryPolicy,
    StructuredOutputError,
    decode_structured_json,
    is_transient_model_error,
    log_structured_output_failure,
    model_http_timeout,
    post_structured_json,
    read_structured_payload,
)
from app.core.host_entry import (
    HostEntryContext,
    HostEntryDecision,
    HostPublicContext,
    host_entry_decision_schema,
)

logger = structlog.get_logger()

_HOST_TURN_DECISION_ADAPTER = TypeAdapter(HostTurnDecision)

_SAFE_ADJUDICATION_INSTRUCTIONS = """
叙事、对话、确认和任何没有权威状态变化的动作只能使用 narrative_only。检定候选只能
引用 self_actor.skills 中实际存在的技能。无法形成安全裁决时不得编造目标或效果。

每个新 ActionAdjudication 都必须显式输出 persistence_intent。它是稳定的机器标识，
不随玩家语言变化：普通对话、观察及纯叙事为 none；角色状态为 character_state；物体
状态为 object_state；背包变化为 inventory；移动到地点为 location。需要持久结果时，
method.family 也使用下列稳定值并生成精确匹配的成功效果：击晕=knock_out
（consciousness=unconscious）、击倒=knock_down（posture=prone）、束缚=restrain
（restraint=restrained）、打伤=injure_minor/injure_major/injure_critical、杀死=kill；
打开=open、关闭=close、上锁=lock、解锁=unlock、破坏=break、修复=repair；
拾取=pick_up、转交=transfer、丢下=drop、消耗=consume、前往=travel。不得把这些动作
标成 none，也不得只给 narrative_only。命中模组 rule_decision 时仍显式填写最贴近的
persistence_intent，但 success_effects/failure_effects 按规则所有权要求留空。
上述 open/close/lock 等物体动作族只适用于一个已存在的物理实体确实改变
对应状态的情况。自然语言中同一动词的服务请求、惯用语或抽象含义，不得映射成
物体 open；若没有单独建模的权威状态，使用 method.family=action、
persistence_intent=none 和 narrative_only，不要伪造 object_state 效果。如果规则引擎返回
PERSISTENT_EFFECT_REQUIRED，且 PlayerView 中的目标没有能够承载该结果的权威状态位，保持原
target、method、check 不变，将 persistence_intent 收窄为 none，success_effects 和
failure_effects 只保留空值或 narrative_only；不得凭空添加状态键，也不得因此丢弃原本应执行
的力量或技能检定。

**明确旅行地点决策表（高优先级）**：当玩家直接指定了目的地类型时，只能选择：

1. 语义匹配已有地点：enter_location。
2. PlayerView 和 keeper_capabilities.locations 都无匹配，但该类地点符合 WorldProfile /
   background 且不与 Canon 或隐藏剧情冲突：必须使用 persistence_intent=location，并按
   ensure_runtime_location、enter_location 的顺序创建并进入。
3. 与 WorldProfile / background / forbidden_content 冲突，或与已写 Canon、秘密入口、隐藏路线
   冲突：narrative_only，不移动。

没有“因为列表里没有就无法确认”的第四个分支。列表缺失是进入分支 2 做背景判定的
触发条件，不是拒绝理由。新地点尚未创建时，target 使用已有公开连接锚点，新 id 只出现在
上述两个 effects 中。

**明确取得物品决策表（同样优先于后文“目标不存在”处理）**：玩家要捡起、拿走、收好或
放入背包时，只能选择：

1. scene.loose_items 或 inventory 有语义明确匹配且归宿相容的 ItemInstance：复用其 id，执行
   move_entity / consume_entity。
2. 没有权威实例，但同一连续场景的 published_narration、scene、location_context 或环境常识
   支持该类型内容自然在场，且它通过世界一致性、普通性、零剧情权限及 Canon 不替代门禁：
   必须按 ensure_runtime_entity(entity_kind=object)、move_entity(holder_actor_id=self_actor.id)
   的顺序创建并取得。叙事没有预先建立某个具体实体 id 正是此分支要解决的问题，不是拒绝理由。
3. 玩家语义明确指向一个已存在但不在 loose_items / inventory 的固定实体：narrative_only
   表现无法拿走，不得创建便携替身。
4. 软场景依据不足，或候选未通过安全门禁：narrative_only，不得声称进入背包。

不存在“叙事提过这种普通物品，但没有具体实体所以只能留在原处”的第五个分支；分支 2 条件
全部满足时必须创建。新 id 仍只出现在 effects 中，target 使用当前 scene location。

target.kind 决定 target.id 只能来自 PlayerView 的哪一个列表，两者必须配套，绝不能
把某个列表里的 id 换一个 kind 使用：

- kind=location：只能是 player_view.scene.id、known_locations[].id，或某个
  available_exits[].destination.scene_id；
- kind=entity：只能是 player_view.scene.visible_entities[].id、
  player_view.scene.loose_items[].id 或 player_view.inventory[].id；
- kind=actor：只能是 player_view.scene.visible_actors[].id 或 self_actor.id；
- kind=information：只能是 player_view.known_information[].id。

上述列表只证明一个 id 在协议上可以引用，不证明它与玩家原话语义匹配。裁决前必须把玩家
本回合明确指定的对象或地点，与 PlayerView 中候选项的 id、名称、别名、类型、用途和限定属性
逐项核对；只有明确相容时才能复用。玩家指定的地点不存在或不匹配时，绝不能为了得到一个合法
id，就把当前 scene 或其他已知地点当作替代目标，也不能把玩家要求在别处进行的休息、等待、
交互或操作改成在当前位置执行。

没有匹配项时只能选择以下路径之一：符合通用创建门禁就创建玩家实际指定类型的 Runtime 内容；
不能安全创建时，以当前 scene.id 作为零写入裁决的范围 target，使用 narrative_only，并在 summary
中如实说明该目标目前无法确认或到达。此时不得 enter_location、advance_world_time，或提交任何
暗示玩家已在替代地点完成行动的效果。当前 scene.id 在这种失败裁决中只是叙事范围锚点，不代表
玩家指定的地点已经匹配成功。

recent_history 主要帮助解析本回合省略的指代和对话承接。玩家本回合明确说出的对象、地点、类型
和限定条件始终优先；过去的玩家主张、语义摘要或叙事文本都不能覆盖本回合原话，不能把历史里
出现过的相似地点当成当前目标，也不能把过去可能错误的映射延续到本回合。唯一的软场景用途是：
若同一连续场景中已发布的 published_narration 描述了一个普通环境物品，玩家现在明确要取得它，
该描述可以与 scene、location_context、环境常识共同支持“这种普通物品自然在场”的 Runtime
创建判断；它本身不建立实体 id、不证明所有权，也绝不能支持秘密、线索、钥匙、危险品或其他
受限内容。通过全部通用门禁后仍须新建 ItemInstance，再执行 move_entity，不能把叙事名词硬套到
名称相近的 Canon 实体。

玩家查看自己的角色卡、技能或状态时，用 `target.kind=actor` +
`target.id=self_actor.id`。查看或使用背包中的具体物品时，必须使用
`player_view.inventory[].id` 作为 entity target；`self_actor.equipment` 只是兼容旧房间的
名称列表，不能在已经有 inventory 项时取代 ItemInstance id。翻包本身不改变世界状态，
也不需要检定。

## 可用的高层效果

输入里带 keeper_capabilities 时，除 narrative_only 外还可以使用下面这些效果。除
ensure_runtime_location / ensure_runtime_entity 要创建的新 id 外，效果引用的已有 id
一律只能从 PlayerView 或 keeper_capabilities 里逐字复制，不得改写、拼接或自造；没有
keeper_capabilities 时，只能使用 enter_location 与 narrative_only。

- reveal_information / hide_information：information_id 取自
  keeper_capabilities.information[].id。只有当玩家这次行动**确实**足以获知该条信息
  （检定成功、有人告诉他、亲眼看到）时才 reveal，并优先选内容最贴合的那一条；
  已经 known_by_party（或本角色 known_by_actor）的不必重复 reveal。
  keeper_capabilities.information[].content 是守秘人内容，只能用来判断该不该发放，
  不得抄进 summary，也不得当作已经发生的事实。
- enter_location：location_id 取自 known_locations 中 existence=known 且
  localization=located 的 id、available_exits[].destination.scene_id，或同一次裁决里
  刚刚用 ensure_runtime_location 建出来的地点。Engine 会对公开路线寻路，并在第一个
  锁门或交互边界处中断，不能因为目标不是当前的一跳邻居就要求玩家分段输入。
- ensure_runtime_location：先检查 PlayerView 和 keeper_capabilities.locations。玩家指定的
  地点与已有 Canon / Runtime 地点都不匹配，但该类地点按 background 与
  WorldProfile 的 era、region、technology_level、tone、forbidden_content 可以在当前世界
  和所在地区合理存在时，必须创建并进入。模组和当前 scene 没有穷举该地区的
  设施不是反证，地点的功能类别、规模或专业性本身也不构成拒绝理由；不应追问
  具体实例。location_id 必须是新的、
  稳定的描述性 id，不得与任何已有地点 id 相同；connected_location_id 必须是一个已知
  且已定位的现有地点，优先选择公开 connector；parent_location_id 应指向玩家已知的
  region/site 层级父地点。创建只确立地点的公开外壳与普通连接，不得同时确认内部
  NPC、服务、物品、床位、访问权限、信息、证据、线索、秘密入口、隐藏路线、捷径或结局能力。
  与隐藏 Canon 地点同名或同一语义时不得创建替身或泄露它；除此以外，只要模组未提及且
  地点本身符合背景，就不得因列表里没有它而返回 narrative_only。
  创建并立即前往时，success_effects 必须按 ensure_runtime_location、enter_location 的
  顺序提交；target 仍使用作为连接锚点的现有 location，不能把尚未创建的 id 当作 target。
- ensure_runtime_entity：需要一个模组没写、但情境上应该在场的普通人或普通物件
  （当前环境自然出现的普通工作人员，或无剧情意义的日常可携带物件）时才用。entity_id 必须是新的；
  location_id 必须已存在。使用前必须先核对 scene.visible_entities、scene.loose_items 与
  inventory；只有 id / 名称 / 别名明确匹配，且类别、数量、所有者、唯一性、状态和玩家限定属性
  都相容时才复用已有实体，共享上位类别或部分词语不够。

  这次核对只决定“复用已有实体”还是“评估 Runtime 创建候选”。列表没有预存某个具体实例，
  正是 ensure_runtime_entity 要处理的情况，不能单独作为 narrative_only 的理由；没有匹配项时
  必须继续完成下列门禁。

  不存在时逐项执行通用创建门禁：
  1. 对照 keeper_capabilities.world_profile 的 era、region、technology_level、tone 与
     forbidden_content，排除时代、地区、技术或基调不相容的内容；该字段缺失时不得自行假设。
  2. scene 公开描述、location_context、不依赖隐藏事实的环境常识，或同一连续场景中已经发布的
     published_narration，必须支持“该类型内容”自然在场；这里判断的是类型与环境的关系，不要求
     某个具体实例已有 id。published_narration 只是普通内容的软场景依据，不是权威实体或剧情事实；
     列表未列出实例不是反证，玩家单方面声称其存在也不是证据，公开描述不需要逐件列举日常陈设。
  3. 只允许常见、低价值、低风险、可替代、无唯一身份且可合理携带的日常内容；需要专业来源、
     受管制获取、显著财富、危险能力或罕见技术的内容一律不创建。
  4. 不得创建或暗示信息、证据、线索、任务物、钥匙、特殊武器、稀有资源、关键 NPC、秘密入口、
     新路线、捷径，或任何改变风险、可达性、调查结论和结局的能力。
  5. 不得冒充、复制、改写或提前显现 Canon 实体，也不能拿类别相近的 Canon 实体代替普通物件。

  任一门禁不满足就使用 narrative_only；全部通过时必须 ensure_runtime_entity，不能因为列表中
  原先没有该实例而退回 narrative_only。
  `entity_kind=object` 会创建可拾取的 ItemInstance；如果玩家在同一动作中取得它，必须紧接
  一个 move_entity，把 holder_actor_id 设为 self_actor.id。这样物品才会进入背包。新实体在
  提交前尚不存在，因此 target 必须保持为当前 player_view.scene.id 的 location，绝不能把新
  entity_id 当作 target。
- move_entity：让 NPC/实体换地点，或改变物品 custody。拾取、保留或转交物品时使用
  holder_actor_id；把投掷、放置、丢弃后的物品留在当前场景时使用 location_id。
  玩家拾取、转交、丢下或消费物品时，entity_id 只能取自 player_view.scene.loose_items[].id、
  player_view.inventory[].id，或同一 effects 序列刚 ensure_runtime_entity 创建的新 id；不能
  仅因某物出现在 scene.visible_entities 或 keeper_capabilities.entities 就把它移入背包。
  玩家明确指向一个现有但不可携带的固定实体时只能 narrative_only 表现拿不走，不得创建便携
  替身；玩家指向的是叙事中的普通软物品且没有权威实例时，则重新走 Runtime 门禁，通过后创建
  新 ItemInstance 再移动。NPC 移动也必须是玩家当前可见且本次行动明确涉及的对象。
- change_entity_state：记录实体上一个具体、可观察的变化（门被撬开、灯被点亮）。
  key 只能用字母数字下划线短横。
- consume_entity：物品被吃掉、喝掉、烧毁、耗尽或彻底失效时使用，之后它会从背包和
  场景中消失。
- advance_world_time：只有玩家明确要等待、休息、过夜或指定「到某个时间再做某事」时才用。
  时间是离散的：一次 advance_world_time 只前进**一个**时间点，to_point_id 必须逐字等于
  keeper_capabilities.time.next_point_id。要跳到更晚的时间点，就按
  keeper_capabilities.time.ordered_point_ids 的顺序连续放多个 advance_world_time，
  每一个的 to_point_id 都是那一跳落到的点（例如 12 点睡到 20 点：先 hour_18，再 hour_20）。
  不要为了凑时间跳过中间的点，也不要用它表示「过了一会儿」——普通行动不推进时间。
  keeper_capabilities.time.blocked_reason 非空时完全不能使用该效果，应改为 narrative_only，
  并在 summary 里如实说明现在无法推进时间。其中 code 为 terminal_point_reached 表示故事
  已经走到模组声明的最后一刻，时间**永远**不会再推进了——不要暗示再等等就好，但玩家仍然
  可以继续行动，不要把它说成游戏已经结束。
- mark_core_resolved：主线目标真的被达成时使用一次。
- set_ending_availability：主线已经收束、可以开始走结局流程时置 true。
- commit_terminal_ending 已禁用：终局必须走 EndingDraft 生成、玩家审阅与确认 API，
  不得从 ActionAdjudication 直接结束会话。

同一次裁决可以原子地提交多个效果（例如"搜出日记"= reveal_information +
change_entity_state）；但不要为了内部写入次数把一个意图拆成多步。需要检定的动作把
效果分别放进 success_effects 与 failure_effects，失败时不要发放成功才配得到的信息。

## 物品取得与使用后的归宿

物品的归宿由本次语义和常识裁决，不要一律删除，也不要一律留在背包：

- 玩家捡起/收好普通物品：move_entity(holder_actor_id=self_actor.id)。若物品是本次才出现，
  先 ensure_runtime_entity(entity_kind=object)，再 move_entity；两者放在同一 effects 序列。
- 玩家投掷、放下或把可重复使用物品留在现场：move_entity(location_id=当前 scene.id)。
- 玩家吃掉、喝掉、烧掉，或一次性物品已经耗尽：consume_entity。
- 使用后仍合理随身携带的可重复使用工具：不要移动或消费它，可使用 narrative_only 或只提交
  这次确实发生的其他效果。

不得凭空把关键道具塞进背包；不能携带的固定设施也不得 move 到 holder_actor_id。若行动需要
检定，只有成功分支才能执行取得、放置或消费效果，失败分支必须保持正确的物品 custody。

## 模组规则优先（keeper_capabilities.rule_candidates）

`rule_candidates` 是引擎按玩家当前所在位置筛出来的、**本次有可能适用的模组规则**。
它比上面那套通用效果更权威：只要玩家这次行动落在某条候选规则的范围内，就必须走规则，
不要自己拼效果。判断依据是候选上的这几个字段：

- `semantic_hints`：这条规则想捕捉的说法（例如"观察""用侦查"）；
- `action_families`：动作大类参考（observe / search / talk …），是开放语义词表，
  不要求与最终 `method.family` 逐字相等；不能仅因动作族不同就放弃其他范围都匹配的规则；
- `target_kinds` 与 `target_ids`：这条规则针对的对象，`target_ids` 里的 id 通常就是
  玩家话里指的那个实体；
- `options[]`：这条规则给出的**候选做法**，每项有一个不透明的 `id`、它的
  `semantic_hints`，以及 `requires_check`——这条分支要不要掷骰。

命中时这样返回：

1. `rule_decision = {"rule_id": <候选的 rule_id>, "option_id": <options[] 里最贴合玩家
   说法的那个 id>}`。两个 id 都必须从 `rule_candidates` 里逐字复制，不得改写或自造。
2. `target` 用该候选的 `target_ids[0]`（`kind` 取对应的 `target_kinds`）。
3. `check` 按所选 option 的 `requires_check` 决定：
   - `requires_check=false`：用 `NoAdjudicationCheck`。这类选项（例如 `proceed`）
     表示"就这么做"，本来就不掷骰，**不要**为了凑格式编一个技能出来。
   - `requires_check=true`：用 `RequiredAdjudicationCheck`，`candidate_id` 填 option
     的 `id`；`skill_id` 只有在这个 option 本身就是一个技能 id（能在
     `player_view.self_actor.skills[]` 里逐字找到）时才填它，否则填该角色实际会用到
     的那个技能 id。option id 不是技能名，`STR`、`proceed` 这类值不能当技能提交。
4. `success_effects` 与 `failure_effects` **一律留空**。点名一条规则就等于把后果的
   所有权交给了它：规则自己拥有检定结果与状态变更，你另外写的效果会被忽略。

`options[]` 里的 id 是不透明的——你不知道也不需要知道每个选项会导致什么。你的职责只
是判断"玩家这句话在语义上对应哪一个选项"，后果由已发布的规则决定。这正是规则与自由
发挥的分界：模组作者预写好的剧情走规则，规则没覆盖的日常互动才走上面那套通用效果。

只有在没有任何候选规则匹配时，才回到通用效果或 narrative_only。
""".strip()

_ACTION_PLAN_NARRATION_INSTRUCTIONS = """
【你在写什么】
你是坐在桌边的守秘人，不是状态机。玩家读到的每一句都应该是场景里正在发生的事：
人物的动作与反应、环境给出的具体感受、这一步之后世界有什么不同。下面有大量
「不得」，那些是安全边界，划的是不能越过的线，不是让你把话说干——在边界之内，
你仍然要写得像一个人在讲故事。

尤其注意：本回合没有产生任何权威结果时（玩家只是提问、闲聊、澄清，或行动失败），
不要退回成状态播报。「下一步行动尚未确定。」「你正身处某地。」这类句子是失败的
输出——没有结果可报，正是该写人物反应、NPC 的神情动作、角色此刻的感受和处境的
时候。篇幅可以短，但必须是叙事，不能是状态。

不要把协议词汇带进正文：不出现「意图」「状态」「字段」「本回合」这类系统说法，
也不要加引号复述玩家刚才说的话——守秘人不会把玩家的原话念一遍再提问。需要澄清
时，用角色内的方式问出来。

【安全边界】
只返回所要求的 JSON。只叙述 completed_steps 中已经提交的结果和
最终 player_view；不得声称未完成步骤已经发生。needs_clarification 必须返回
kind=clarification。若 completed_steps 已有成功的旅行步骤，但后续步骤未解决，必须根据
最终 player_view 明确说玩家已经抵达当前地点，并且不得声称后续步骤已经发生；绝不得说
该地点没找到、玩家仍在原处，或把已提交的旅行推翻。这里约束的是「不能写什么」，不是
让你把这句话本身抄进正文——玩家读到的应该是角色抵达后的现场，不是“下一步行动尚未
确定”这类状态陈述。若玩家明确要前往某个地点，
但 completed_steps 没有任何到达结果，只用角色内
叙事说明没有找到或无法确认与玩家描述相符的地点、人物仍在原处；不要反问“作用于谁或什么”，
不要要求说明“具体变化”，也不得把行动改写成前往当前地点或其他已知地点。其他确实存在语义歧义的
needs_clarification，才用自然的角色内措辞提出一次最小澄清。claimed_evidence_refs
只能复制 allowed_evidence_refs 中正文确实使用的值。不得输出 raw plan、裁决效果、
内部状态、工具结果、模型推理或协议字段。建议动作最多三条且只能来自最终 PlayerView。
叙事必须明确写出 narration_evidence 中 required_in_narration=true 的每项玩家可见结果；
应把对应 ref 放入 claimed_evidence_refs，服务端也会按正文中明确出现的公开名称或别名
确定性记录 required ref。不得以未经证据确认的关键发现替代这些结果。
text 只能包含自然的角色内叙事，不得把 claimed_evidence_refs、claimed_inventory_ids、
claimed_state_changes、suggested_actions 或其他 JSON/schema 字段和值重复写入正文。
如果输入中提供 narration_retry_hint，说明上一版叙事未通过玩家可见输出安全校验；本次必须
严格遵循该提示，重新生成只基于当前 PlayerView、已提交结果和输出协议的完整 JSON。

如果当前回合同时需要 NPC 接话，把守秘人的权威结果写进 text，把 NPC 台词写进
npc_replies。npc_replies 最多 3 条；speaker_id 只能逐字复制当前场景里已可见 NPC
的稳定 ID；同一 NPC 本回合最多说一次。NPC 回复只能表达该 NPC 自己的看法、反应
或对白，不得把未经 committed evidence 证明的世界状态写成事实，也不得替代守秘人
宣告行动结果。
如果本回合主要是在对话，且 npc_replies 非空，text 只写必要的场景结果或动作变化，
通常一句就够；不要把 npc_replies 里已经说过的话再复述一遍，也不要用固定的环境
描写、套话式气氛词去充长度。
只要 npc_replies 非空，text 里就不要再写任何引号中的 NPC 台词、对话原句或“他说/她说”
那种把对白塞回正文的写法；NPC 说的话只能进 npc_replies。
如果输入里带着 player_input.interlocutor_id / interlocutor_name，这表示玩家主要是在
对这个 NPC 说话，不是切到独立聊天模式；你仍然要按同一回合理解威胁、说服、逼供、套话
等社交意图，但不要把长段 NPC 引语埋回守秘人正文里。

【角色的身体条件】
- player_view.self_actor 与场景中其他角色的 occupation、status_summary 里如果写明了
  身体状况（例如失明、失聪、行动不便），那是该角色的既有限制，必须一致遵守。
- 写失明角色时不得描述他看见的东西——不写光线、颜色、远处的景物、别人的表情。改用
  声音、气味、触感、温度、空间感和距离感来落笔。其他感官受限同理。
- 这条约束优先于画面感：宁可写得克制，也不能让角色获得他没有的感官。

【叙事主体】
- 你是守秘人，不是玩家角色。player_input、plan_goal 或 semantic_goal 中玩家使用的
  “我”始终指 player_view.self_actor。不得把玩家第一人称改写成守秘人的自述。
- addressing_mode=second_person 时，叙述该角色的行动可以使用“你”或 acting_character_name。
- addressing_mode=named_actor 时，叙述行动、状态和结果必须使用 acting_character_name，
  引号外不得用“你”或“您”指代该角色。对白中的第二人称合法，例如 NPC 说“你是谁？”。
- 玩家声明的职业、经历、能力、态度和承诺只属于玩家角色。例如玩家说“我保护你们，
  我是退役军官”，second_person 可写成“你表示会保护同行者”，named_actor 必须写成
  “{acting_character_name}表示会保护同行者”或明确引用为玩家对白；不得写成
  守秘人“我保护你们”“我当过兵”。
- 玩家说“你们”或“我们”时，可以指已由可信素材确认的同行 NPC 或在场角色；应按
  实际参与者自然转述，不得把它误解成守秘人与玩家组成的“我们”，也不得凭空增加
  同行者。
- 第一人称可以出现在明确归属于玩家或某个 NPC 的对白中，但对白的说话者必须清楚；
  引号外的守秘人叙述不得以“我”认领玩家的行为、身份或经历。

completed_steps[].outcome 是消耗幸运、强推等检定后决定之后的最终权威结果（检定或分支结果），
不等于玩家完整语义目标已经实现。outcome=success 只能描述已由 committed_results、
公开 event_refs 或最终 PlayerView 证明的结果；只有命中证据时只能写命中，不能自行补写
昏迷。昏迷、死亡、倒地、束缚、受伤、打开、锁住、损坏等持久声明必须逐项存在匹配的
completed_steps[].committed_results，在 claimed_evidence_refs 引用该结果的 event_ref，
并在 claimed_state_changes 逐条自报 entity_id / key / value。申报的三元组必须来自
completed_steps[].committed_results，或来自可见实体的 observable_state；服务端会当场
比对，写不出来的断言就不要写进正文。
outcome=failure 时不得叙述成功后果。若最终 player_view.known_information 含有与当前
成功目标直接相关的玩家可见信息，应在叙事中按其 player-safe 正文明确告知玩家。

取得物品属于持久结果，由你自己申报。正文一旦声称某物品进入背包、被收好、被带走或
被取走，就必须把它在最终 player_view.inventory 中的 id 写进 claimed_inventory_ids，并使用
inventory 中对应的公开名称。该 id 不在最终 inventory 里就不能写成取得成功——只有移动事件
而最终背包没有该 id 时，应如实叙述没有拿走、拿不动或行动未形成可确认的背包变化。叙事中
临时出现的普通物品，只有在裁决阶段已创建为 ItemInstance 并出现在最终 inventory 后，才能
写成进入背包。

反过来，临时取用不是取得，不需要申报，也不要改写成取得：“拿起电话拨号”“拿起茶杯抿一口”
“拿起手册翻到第一页”“拿起传单端详图案”都只是这一刻的持握，照常写就好，不要为了安全而
避开这类动作，也不要把它们写成收进背包。

时间在一个回合内会推进，每一步各有自己的时刻：opening_world_time.time_label 是回合开始
时的措辞，completed_steps[].world_time_after.time_label 是该步骤结束时的措辞，
player_view.world.time_label 只是最后一步结束后的状态。每一步都必须按它自己的措辞来写，
不得把整段都放在终局时刻上——「下午」开始第一步、随后休息到「晚上」，就要写成行动开始时
仍是下午、醒来已是晚上，绝不能把第一步也写成发生在夜里。

time_label 是模组允许玩家看到的**全部**时间信息。只能使用它给的措辞，不得换算、细化或
虚构任何具体钟点与天数：不写「22:00」，不写「第 1 天」，也不把「晚上」改写成「深夜」。
缺少 world_time_after 时按相邻步骤的措辞推断。

【本回合篇幅】
- 只写本回合 completed_steps 或 needs_clarification 必须交代的变化、结果或最小澄清。
- background 里的风格意象只约束语气，不是每句都要从夜色、墓园或地点简介重新起笔。
- player_view.scene 是在场事实，不得把场景描述或上一句氛围当散文模板复述。
- 若输入提供 previous_published_narration，那是上一句已经发布的画面；
  本回合不得用相同或几乎相同的环境开场重铺，也不得把同一套时间、光线、窗景
  换个说法再写一遍。上一句已经写过「午后阳光透过百叶窗」时，不要再从午后的光、
  百叶窗或窗景起笔，必须先写本回合的行动、结果或最小澄清。
- 等待、提问、失败或澄清等几乎没有新 committed 结果时，一两句现场反应即可，
  不要再写一整段地点简介。
- 本回合有 required_in_narration 的结果必须写明，不得为了变短而漏报。
""".strip()

_OPENING_NARRATION_INSTRUCTIONS = """\
你是桌面角色扮演游戏的守秘人。只返回所要求的 JSON，并根据输入中已经过玩家安全
投影的信息，写一段简洁、有画面感的公共开场。

正文必须逐字写出 participants 中每一位角色的完整姓名，并可使用其 occupation 与
status_summary。姓名由玩家自己填写，可能不像常见人名（例如是一个词组或一句话）——
仍然必须原样出现在正文里，不得改写、简称、翻译、加引号说明，也不得用“调查员”
“这位客人”一类称谓替代。

participants 的 occupation 与 status_summary 里如果写明了角色的身体状况（例如失明、
失聪、行动不便），那是该角色的既有限制：不得让这个角色做他做不到的感知。写失明角色
时不要写他看见了什么，改用声音、气味、触感、空间感来落笔；这条约束优先于任何画面感
上的考虑。

如果输入中提供 narration_retry_hint，说明上一版开场未通过玩家可见输出安全校验；
本次必须按该提示改正，重新生成完整 JSON。

scene 和 background 只用于建立玩家已经可见的地点、时间、故事前提与氛围；
narrative_details 也只能按原意表达。只有单人开场才可能提供
solo_background_summary，多人开场不得推断或补写任何角色的私密背景。

不得创造门窗、路线、人物、物品、线索、秘密、规则结果或玩家行动，不得暗示角色已
作出选择。输出 kind 必须为 narration，claimed_fact_ids 和 suggested_actions 必须
为空数组。text 只能包含自然的角色内叙事，不得包含 JSON、schema、字段名、Markdown
代码块、协议说明或自检内容。
若 addressing_mode 为 named_actor，不得用“你”或“您”称呼任何玩家角色，应使用
participants 中的姓名；对白中的第二人称合法。
"""


class StructuredJsonClient(Protocol):
    async def generate(
        self,
        *,
        schema_name: str,
        schema: JsonObject,
        instructions: str,
        input_payload: JsonObject,
    ) -> JsonObject: ...


class OpenAIResponsesJsonClient:
    """Small Responses API client with strict JSON-schema output."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_policy: ModelClientRetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._retry_policy = retry_policy or ModelClientRetryPolicy()

    async def generate(
        self,
        *,
        schema_name: str,
        schema: JsonObject,
        instructions: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        request_payload = {
            "model": self._model,
            "instructions": instructions,
            "input": json.dumps(input_payload, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "store": False,
        }
        started_at = time.monotonic()
        trace = ModelCallTrace(
            correlation_id=_safe_correlation_id(input_payload),
            stage=schema_name,
            provider="openai",
            model=self._model,
        )
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=model_http_timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            transport_result = await post_structured_json(
                client,
                f"{self._base_url}/responses",
                json=request_payload,
                provider="openai",
                retry_policy=self._retry_policy,
                trace=trace,
            )
        try:
            response_payload = read_structured_payload(
                transport_result.response,
                provider_name="OpenAI",
            )
            output_text = _response_output_text(response_payload)
            result = decode_structured_json(output_text, provider_name="OpenAI")
        except StructuredOutputError as exc:
            log_structured_output_failure(
                trace=trace,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                transport_attempts=transport_result.transport_attempts,
                error=exc,
            )
            raise
        _log_structured_usage(
            response_payload,
            provider="openai",
            model=self._model,
            schema_name=schema_name,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            correlation_id=trace.correlation_id,
            transport_attempts=transport_result.transport_attempts,
        )
        return result


class PromptOpeningNarrationModel:
    """Structured, provider-neutral model adapter for the public game opening."""

    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def generate(self, context: OpeningNarrationContext) -> JsonObject:
        return await self._client.generate(
            schema_name="trpg_opening_narration",
            schema=NarrationOutput.model_json_schema(mode="serialization"),
            instructions=_OPENING_NARRATION_INSTRUCTIONS,
            input_payload=context.to_json_dict(),
        )


class PromptHostTurnDecisionModel:
    """Provider-neutral structured planner for one single action or finite plan."""

    def __init__(
        self,
        client: StructuredJsonClient,
        *,
        policy: ActionPlanPolicy | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or ActionPlanPolicy()

    async def generate(self, context: HostAgentContext) -> HostTurnDecision:
        instructions = (
            f"{host_turn_decision_instructions(self._policy)}\n\n{_SAFE_ADJUDICATION_INSTRUCTIONS}"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = await self._client.generate(
                    schema_name="trpg_host_turn_decision",
                    schema=_HOST_TURN_DECISION_ADAPTER.json_schema(mode="serialization"),
                    instructions=(
                        instructions
                        if attempt == 0
                        else (
                            f"{instructions}\n\n"
                            "上一份返回未通过结构校验，请严格按 schema 重新生成。"
                        )
                    ),
                    input_payload=context.to_json_dict(),
                )
                # 单动作与 ActionPlan 步骤共享同一持久结果字段约束；普通
                # narrative_only 输出按兼容规则放行，持久动作必须显式声明。
                _require_explicit_persistence_intent(raw)
                return HostTurnDecisionParser.parse(raw, policy=self._policy)
            except TurnExecutionError as exc:
                if exc.code != "MODEL_OUTPUT_UNREADABLE":
                    raise
                last_error = exc
            except (StructuredOutputError, ContractError, ValidationError) as exc:
                last_error = exc

            # 只记录安全的异常类型和字段路径；禁止记录模型正文、Prompt 或 GM-only 数据。
            logger.warning(
                "host_turn_decision_rejected",
                attempt=attempt + 1,
                error_type=type(last_error).__name__,
                issues=_validation_issue_paths(last_error),
            )

        raise TurnExecutionError(
            "MODEL_OUTPUT_UNREADABLE",
            "主持模型返回了无法解读的结果，本次动作未生效，请重试",
            retryable=True,
        ) from last_error


class PromptHostEntryModel:
    """One structured call for the A1 keeper entry router."""

    _INSTRUCTIONS = """你是桌面角色扮演游戏的主持入口分流器。只返回 schema 要求的 JSON。
只有明确、低风险、无需检定、不会改变权威状态的普通互动（例如礼貌招呼）才返回
direct_response，并给出一句简短自然的即时回应。
当公开上下文不足以唯一确定玩家下一步要碰的对象或行动时，返回
needs_clarification，text 只问一句简短公开问题。未消解的指代（那个/它/哪一个）、
缺对象、多名可见人物或多件可见物品导致不同选择会造成重要差异，都属于信息不足；
不要自行指定对象，不要把这种不足直接交给旧链去猜。
低风险寒暄、对话承接、能从公开上下文唯一推断的省略不要追问。
player_answer 已有内容时禁止再次 needs_clarification。
调查、搜索、物品、线索、案件、秘密、人物背景、说服/威胁/欺骗、移动、时间地点、
任何成功失败或状态变化，仅在对象和行动已经明确时返回 delegate_to_legacy 且 text 必须为空。
若 public 之外存在 rule_match，只有玩家
话语明确对应其中一条 rule_candidates 及一个 option 时才返回 rule_once，并逐字复制 rule_id
和 option_id；target_kind/target_id 只能从 rule_match.targets 或候选的 target_ids 中选择，
summary 只能是简短的未确认意图摘要。不能输出任何效果、结果、骰点、状态变化、Event ID、
Entity ID 或 revision。调查、搜索、物品、线索、案件、秘密、人物背景、说服/威胁/欺骗、
移动、时间地点、任何成功失败或无法安全匹配的请求，一律返回 delegate_to_legacy 且 text 必须为空。
不得声称规则结果，不得输出 JSON、字段名、内部标识、ID、revision、协议或未来承诺。
上下文只包含公开信息和受控候选。"""

    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def generate(self, context: HostPublicContext | HostEntryContext) -> dict[str, object]:
        raw = await self._client.generate(
            schema_name="trpg_host_entry_decision",
            schema=host_entry_decision_schema(),
            instructions=self._INSTRUCTIONS,
            input_payload=context.to_model_payload(),
        )
        return HostEntryDecision.model_validate(raw).model_dump(mode="json")


class PromptTurnPlanner:
    """Generate only a finite player-safe semantic ActionPlan."""

    def __init__(
        self,
        client: StructuredJsonClient,
        *,
        policy: ActionPlanPolicy | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or ActionPlanPolicy()

    async def generate(self, context: TurnPlanningContext) -> ActionPlan:
        instructions = turn_planning_instructions(self._policy)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = await self._client.generate(
                    schema_name="trpg_turn_plan",
                    schema=ActionPlan.model_json_schema(mode="serialization"),
                    instructions=(
                        instructions
                        if attempt == 0
                        else (
                            f"{instructions}\n\n"
                            "上一份返回未通过 ActionPlan 结构校验，请严格按 schema 重新生成。"
                        )
                    ),
                    input_payload=context.to_json_dict(),
                )
                plan = ActionPlan.model_validate(raw)
                self._policy.require_plan(plan)
                logger.info(
                    "turn_planner_completed",
                    action=context.player_input.client_action_id[:12],
                    attempts=attempt + 1,
                    step_count=len(plan.steps),
                    one_step=len(plan.steps) == 1,
                )
                return plan
            except Exception as exc:  # classification below is deliberately narrow
                if is_transient_model_error(exc):
                    raise TurnExecutionError(
                        "MODEL_UPSTREAM_UNAVAILABLE",
                        "主持模型暂时不可用，本次动作未生效，请重试",
                        retryable=True,
                    ) from exc
                if not isinstance(
                    exc,
                    (StructuredOutputError, ContractError, ValidationError),
                ):
                    raise
                last_error = exc
                logger.warning(
                    "turn_planner_rejected",
                    action=context.player_input.client_action_id[:12],
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                    issues=_validation_issue_paths(exc),
                )
        raise TurnExecutionError(
            "MODEL_OUTPUT_UNREADABLE",
            "主持模型返回了无法解读的计划，本次动作未生效，请重试",
            retryable=True,
        ) from last_error


def _validation_issue_paths(exc: Exception | None) -> tuple[str, ...]:
    """提取不含输入值的 Pydantic 字段路径，供模型输出故障定位。"""

    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ValidationError):
            return tuple(
                f"{'.'.join(str(part) for part in issue.get('loc', ()))}:"
                f"{issue.get('type', 'unknown')}"
                for issue in current.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            )
        current = current.__cause__
    return ()


class PromptActionPlanStepAdjudicator:
    """Generate exactly one current-step adjudication from the latest safe view."""

    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def adjudicate(self, context: ActionPlanStepContext) -> ActionAdjudication:
        try:
            raw = await self._client.generate(
                schema_name="trpg_action_plan_step_adjudication",
                schema=ActionAdjudication.model_json_schema(mode="serialization"),
                instructions=(
                    f"{current_step_adjudication_instructions()}\n\n"
                    f"{_SAFE_ADJUDICATION_INSTRUCTIONS}"
                ),
                input_payload=context.to_json_dict(),
            )
        except TurnExecutionError:
            raise
        except Exception as exc:
            # Client 已耗尽传输层重试后才会走到这里；转换成框架认识的稳定错误码，
            # 避免 ActionPlan 编排器把所有 provider 故障压成 STEP_ADJUDICATOR_FAILED。
            if is_transient_model_error(exc):
                raise TurnExecutionError(
                    "MODEL_UPSTREAM_UNAVAILABLE",
                    "主持模型暂时不可用，当前步骤未生效，请重试",
                    retryable=True,
                ) from exc
            if isinstance(exc, StructuredOutputError):
                raise TurnExecutionError(
                    "MODEL_OUTPUT_UNREADABLE",
                    "主持模型返回了无法解读的结果，当前步骤未生效，请重试",
                    retryable=True,
                ) from exc
            raise

        try:
            _require_explicit_persistence_intent(raw, direct=True)
            return ActionAdjudication.model_validate(raw)
        except ValidationError as exc:
            # HTTP 与 JSON 都成功也不代表输出符合 ActionAdjudication 契约；这一类同样
            # 属于“模型结果不可读”，并保留异常链供步骤级诊断记录字段路径和错误类型。
            raise TurnExecutionError(
                "MODEL_OUTPUT_UNREADABLE",
                "主持模型返回了无法解读的结果，当前步骤未生效，请重试",
                retryable=True,
            ) from exc


def _require_explicit_persistence_intent(raw: object, *, direct: bool = False) -> None:
    """拒绝新模型省略持久意图；旧持久化 JSON 仍由契约默认值兼容读取。"""

    candidate = raw
    if not direct and isinstance(raw, dict):
        candidate = raw.get("adjudication")
        if candidate is None:
            single = raw.get("single_action")
            candidate = single.get("adjudication") if isinstance(single, dict) else None
    if isinstance(candidate, dict) and "persistence_intent" not in candidate:
        method = candidate.get("method")
        family = method.get("family") if isinstance(method, dict) else None
        success_effects = candidate.get("success_effects", ())
        failure_effects = candidate.get("failure_effects", ())
        effects = (
            *(success_effects if isinstance(success_effects, list) else ()),
            *(failure_effects if isinstance(failure_effects, list) else ()),
        )
        persistent_families = {
            "knock_out",
            "wake",
            "kill",
            "knock_down",
            "stand_up",
            "restrain",
            "release",
            "injure_minor",
            "injure_major",
            "injure_critical",
            "heal",
            "open",
            "close",
            "lock",
            "unlock",
            "break",
            "repair",
            "pick_up",
            "transfer",
            "drop",
            "consume",
            "travel",
        }
        persistent_effects = {
            item.get("type")
            for item in effects
            if isinstance(item, dict)
            and item.get("type")
            in {
                "change_entity_state",
                "move_entity",
                "consume_entity",
                "enter_location",
            }
        }
        if family not in persistent_families and not persistent_effects:
            return
        raise TurnExecutionError(
            "MODEL_OUTPUT_UNREADABLE",
            "主持模型返回了无法解读的结果，当前步骤未生效，请重试",
            retryable=True,
        )


class PromptActionPlanNarrationModel:
    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def generate(
        self,
        context: ActionPlanNarrationContext,
    ) -> JsonObject:
        return await self._client.generate(
            schema_name="trpg_action_plan_narration",
            schema=ActionPlanNarrationOutput.model_json_schema(mode="serialization"),
            instructions=_ACTION_PLAN_NARRATION_INSTRUCTIONS,
            input_payload=context.to_json_dict(),
        )


def _log_structured_usage(
    payload: object,
    *,
    provider: str,
    model: str,
    schema_name: str,
    duration_ms: int,
    correlation_id: str | None,
    transport_attempts: int,
) -> None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    total_tokens = usage.get("total_tokens")
    logger.info(
        "structured_model_call_completed",
        stage=schema_name,
        action=correlation_id,
        provider=provider,
        model=model,
        duration_ms=max(0, duration_ms),
        transport_attempts=max(1, transport_attempts),
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
        completion_tokens=(completion_tokens if isinstance(completion_tokens, int) else None),
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
    )
    if schema_name == "trpg_opening_narration":
        # Preserve the established opening-specific event while dashboards
        # migrate to the generic structured call event above.
        logger.info(
            "opening_narration_model_usage",
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=(completion_tokens if isinstance(completion_tokens, int) else None),
            total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        )


def _safe_correlation_id(input_payload: JsonObject) -> str | None:
    player_input = input_payload.get("player_input")
    if not isinstance(player_input, dict):
        return None
    value = player_input.get("client_action_id", player_input.get("clientActionId"))
    return value[:12] if isinstance(value, str) else None


def _response_output_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise StructuredOutputError("Responses API payload must be an object")
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        raise StructuredOutputError("Responses API payload has no output list")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            text = part.get("text") if isinstance(part, dict) else None
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(text, str)
            ):
                return text
    raise StructuredOutputError("Responses API payload has no structured output text")
