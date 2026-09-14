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
【裁决依据与规则所有权】
依据玩家当前意图、最新 PlayerView、模组和互动历史裁决；玩家的请求与过去主张不等于事实。
先检查 keeper_capabilities.rule_candidates，所有动作类型都适用，包括旅行和对话。
semantic_hints 与 action_families 用于语义匹配，动作族不要求与 method.family 逐字相等；
target_kinds、target_ids 非空时是硬性范围，空列表表示该维度不设限。不能只因措辞不同
放弃适用规则，也不能把不相关的互动硬套进规则。

命中候选时：
- rule_decision.rule_id 和 option_id 逐字复制匹配的规则及 options[].id；target 在候选
  允许的范围内匹配实际对象，不能一律取首项，也不能从空 target_ids 取值。
- requires_check=false 使用 NoAdjudicationCheck；true 使用 RequiredAdjudicationCheck，
  candidate_id 使用 option.id；skill_id 使用 option.check_skill_id，未规定时从 self_actor.skills
  选择贴合方法的已有技能。选项 ID 不是技能名。
- success_effects / failure_effects 留空，后果由规则拥有；仍填写最贴近的 persistence_intent。
  options[].id 是不透明标识，只匹配做法，不猜测未公开的后果。
只有没有适用规则时，才自由判断检定和效果；检定候选只能引用 self_actor.skills 中已有技能。
需要检定时，在同次裁决中声明成功与失败效果，不发放只属于另一分支的结果。

【持久结果】
每个 ActionAdjudication 必须显式输出 persistence_intent：无持久结果为 none，角色状态为
character_state，物体状态为 object_state，背包变化为 inventory，地点移动为 location。
只有不改变权威状态的结果才用 narrative_only；表达成对话或请求不免除持久效果。
method.family 使用稳定语义：knock_out 对应 consciousness=unconscious，knock_down 对应
posture=prone，restrain 对应 restraint=restrained；另有 injure_minor/injure_major/
injure_critical、kill、open、close、lock、unlock、break、repair、pick_up、transfer、drop、
consume、travel。为实际持久结果生成匹配效果，不得标成 none。
其他角色变化使用 action + character_state 和具体状态效果；标准公开角色状态无需预置。
物体动作族只用于物理实体的对应变化；服务请求、惯用语或抽象含义不得按同名动词硬套。
没有建模的持久状态时使用 action + none + narrative_only，不伪造状态键。

【目标与历史】
target.kind 与 id 必须配套，并与当前输入的名称、别名、类别、数量、所有者、唯一性、
状态和限定属性相容；协议允许引用不代表语义匹配。不得用当前地点、相似名称或历史上的
错误映射替换玩家明确指定的目标。recent_history、memories 和 conversation_summary 用于
指代与经历承接，不能覆盖本次明确意图，也不能推翻当前公开状态。

合法 target 来源：
- location：scene.id、已知且已定位的 known_locations，或 available_exits 的 destination。
- entity：scene.visible_entities、scene.loose_items 或 inventory；以它们实际提供的 id 为准。
- actor：self_actor.id 或 scene.visible_actors[].id。
- information：known_information[].id。
- world：keeper_capabilities.world_id，仅用于没有具体对象的世界范围互动。
keeper_capabilities 的实体、地点和信息是效果词表，不自动成为玩家可作用的 target；
命中规则时可使用候选明确允许的 target。新建 id 只能出现在创建和后续效果中。

找不到匹配项时按下述 Runtime 条件判断。不能安全创建时，使用当前 scene.id 作为
零写入 narrative_only 的范围锚点，说明实际缺失或障碍；不得在替代地点执行行动或推进时间。
查看角色卡、技能和自身状态使用 self_actor；背包物品使用 inventory 的实例 id，
self_actor.equipment 只兼容没有实例的旧房间。查看角色资料、翻包本身不改变状态或触发检定。

【Runtime 地点】
玩家指定了目的地时，先核对 PlayerView 与 keeper_capabilities.locations 中的 Canon / Runtime
地点；语义匹配则复用。没有匹配项时，依据 world_profile 的 era、region、technology_level、
tone、forbidden_content 和 background 判断该类地点是否在当前地区合理存在。
符合背景且不冲突时，按 ensure_runtime_location、enter_location 创建并进入；模组未穷举
设施、地点的规模或专业性、没有指定具体实例都不单独构成拒绝或澄清理由。地点不套用下述
人物 / 物件的低价值和可携带要求。缺失的世界设定不能自行假设。
新 location_id 必须唯一；connected_location_id 使用已知且已定位的公开连接点，优先
connector；parent_location_id 使用玩家已知的 region/site 父地点。target 仍是既有连接锚点。
创建只建立公开外壳和普通连接，不确认内部人物、服务、物品、床位、访问权限、信息、线索、
秘密入口、隐藏路线、捷径或结局能力；不得复制或泄露隐藏 Canon 地点。条件不满足则不创建。

【Runtime 人物 / 物件】
先核对可见实体、loose_items 和 inventory；只有语义及限定属性相容才复用，共享上位类别
或部分词语不够。没有权威实例时，按以下条件判断 ensure_runtime_entity：
1. 世界一致性：符合明确提供的 world_profile / background。
2. 场景依据：scene、location_context、公开环境常识或同一连续场景的 published_narration
   支持该类型自然在场。玩家单方面声称不算依据；既有叙事可支持普通内容的在场可能，
   不建立实体 id、所有权或剧情事实。
3. 普通性：常见、低价值、低风险、可替代、无唯一身份的日常人物或可携带物件；
   不创建需要专业来源、受管制获取、显著财富、危险能力或罕见技术的内容。
4. 零剧情权限：不创建信息、证据、线索、任务物、钥匙、特殊武器、稀有资源、关键 NPC，
   或改变风险、可达性、调查结论及结局的能力。
5. Canon 不替代：不冒充、复制、改写或提前显现已有实体。
全部满足则创建，不因缺少预存 id 或普通内容的具体名字而拒绝；否则 narrative_only。
entity_id 必须新建，location_id 必须已存在；target 使用当前 scene.id。
entity_kind=object 创建 ItemInstance；同一动作要取得它时，紧接
move_entity(holder_actor_id=self_actor.id)，新 id 只用于这两个 effects。
明确指向现有不可携带的固定实体时，不得创建便携替身或将其放入背包。

【效果协议】
有 keeper_capabilities 时可使用以下高层效果；除新建 id 外，已有 id 必须从 PlayerView 或
对应能力词表逐字复制。没有 keeper_capabilities 时仅可用 enter_location 和 narrative_only。
- reveal_information / hide_information：使用 information[].id。只有本次行动足以获知才
  reveal，已被队伍或当前角色知道的不重复发放；Keeper 内容只用于判断，不得抄入公开 summary。
- enter_location：使用已知且已定位的地点、公开出口或同次创建的地点。引擎按公开路线寻路，
  在锁门或交互边界中断；不因目的地超过一跳就要求玩家分段输入。
- change_entity_state：记录具体可观察的变化，key 只用字母、数字、下划线、短横。
  只有 NPC 持续随队才用 accompanying=true/false，以该 NPC 为 target、character_state 为持久意图。
  结合情境与历史判断意愿；普通请求未判断出不愿意时默认同意，不愿意则拒绝。
  强制行为的检定及成功效果在同次裁决绑定，适用规则仍优先。enter_location 自动带上随行者，
  不为随行追加 move_entity；不得把否定或解除随行改成同意。
- move_entity：NPC 移动到 location_id 的对象须当前可见且与本次行动相关；物品取得、保留、
  转交使用 holder_actor_id，放置或丢弃使用 location_id。进入背包的 entity_id 仅来自
  loose_items、inventory 或同次创建的 Runtime object，visible_entities 中的固定实体不够。
  携带物品必须形成 inventory 中的 ItemInstance 保管关系，不能给物品设置 accompanying。
  捕获可携带个体使用对应 loose_items 实例，不把场景群体整体搬走；观察成功不等于取得。
  已在当前角色背包中的实例直接复用；取得失败不宣称携带成功。carried 表示随身持有，
  不要求旁白额外描写“塞进包里”。没有实例时只有满足 Runtime 条件才创建，不能复制 Canon。
- consume_entity：物品耗尽、被毁或彻底失效时使用；可重复使用且仍随身携带的工具不移动或消费。
  物品使用后的归宿按实际语义和成功 / 失败分支处理，不一律删除或留在背包。
- advance_world_time：仅用于明确等待、休息、过夜或等待指定时刻；普通行动不推进时间。
  每个效果只前进一个时间点，首个 to_point_id 使用 time.next_point_id，更晚目标按
  time.ordered_point_ids 连续提交，不跳过中间点，不自造 ID。time.blocked_reason 非空时
  不推进，公开说明障碍；terminal_point_reached 表示不会再推进时间，但玩家仍可行动。
- mark_core_resolved：主线目标实际达成时使用。
- set_ending_availability：主线收束、可进入结局流程时置 true。
- commit_terminal_ending 已禁用；终局通过 EndingDraft 审阅和确认 API，不由裁决直接结束。
一个意图可原子提交多个效果，不按内部写入次数拆步骤。summary 只描述玩家安全的意图或已知情况。
""".strip()

_ACTION_PLAN_NARRATION_INSTRUCTIONS = """
你是桌边的守秘人，写简洁、连贯的旁白，交代实际结果与必要的现场变化。
普通行动和问答保持简短；抵达现场与新增信息按事实需要展开，信息完整优先于篇幅。
动作和语气只保留有助于理解的部分，不用连续神态、比喻或心理揣测延长简单反应。

【已发生的事实】
只根据 completed_steps 的已提交结果和最终 player_view 叙述；不得把未完成步骤写成事实。
已提交结果不因后续失败或澄清而撤销。成功旅行后应按最终地点介绍现场；未确认抵达时，
按实际障碍或缺失信息回应，不预设目的地不存在，不把目标替换为当前或其他地点。
termination_status=needs_clarification 时输出 kind=clarification，先交代已有结果，
再用自然措辞提出最小必要澄清，不复述玩家原话或系统状态。

completed_steps[].outcome 是消耗幸运、强推等检定后决定之后的最终权威结果，
不代表完整目标已达成。outcome=success 只能支持证据确认的结果，不可扩张其程度；
outcome=failure 也要交代失败分支实际提交的变化。

narration_evidence 中 required_in_narration=true 的结果必须在正文表达。
information_revealed.description 是新增公开事实的底稿，可重排、合并和自然改述，
保留人物关系、数量、时间、否定和条件；不能只写标题或留给信息面板。
其他 known_information 是背景，不自动成为本次发现；新发现实体需写出公开名称或别名。
claimed_evidence_refs 只填 allowed_evidence_refs 中正文确实表达的来源，申报不能代替叙述。
持久状态声明须有 committed_results 或可见实体 observable_state 支持；对应结果引用
其 event_ref，并在 claimed_state_changes 填写已有的 entity_id / key / value，不自行构造。

声称物品被取得或带走时，须使用最终 inventory 中的公开名称，并在 claimed_inventory_ids
填写该实例 id。没有该实例时，按实际证据描述暂时取用、转交、放置、消耗或未完成取得，
不要自行解释为拿不动。临时持握和使用不等于获得所有权，不改写成进入背包。

【人物与对话】
当前公开状态优先于静态人物描述；accompanying_npcs 与可见实体的同一 ID 是同一个人。
结合记忆、近期历史与已提交结果保持人物关系连续，区分原有随行者、本次加入和已解除随行。
player_input.interlocutor_id / interlocutor_name 指定当前对话对象；结合其已知立场和社交裁决
给出回应，允许拒绝或保留信息，不能用无意义的神态代替回答。

NPC 直接台词只写在 npc_replies，最多 3 条，同一 NPC 最多一条；speaker_id 逐字复制
当前可见 NPC 的 ID。台词仅表达该人物的立场、反应和公开知识，不宣告未确认的世界变化，
不夹带舞台动作。界面先显示 text，再依次显示 npc_replies；它们是独立消息，各自完整成句，
不要把一段带引号的对话拆成前后两截。text 简洁交代已确认的动作、结果和必要现场变化，
不重复玩家刚说的问题，不重复或转述台词，也不用“她轻声说道，”这类等待台词接上的引语前缀。
NPC 的语气和态度主要由台词体现；旁白中的神态、动作只在提供新的可观察信息或有助理解
行动结果时描写。两者同次输出且含义一致，不能一边给出回答一边宣称沉默。
确有情境依据时才描写拒绝开口或无法说话。
本次必写信息的完整原文可保留作者的人称与引号，仅这些来源句段适用该例外。

【行动主体与身体条件】
玩家输入中的“我”、职业、经历、能力和承诺属于 player_view.self_actor，不是守秘人。
addressing_mode=second_person 时可用“你”或 acting_character_name；
addressing_mode=named_actor 时用 acting_character_name，引号外不以“你”或“您”指代该角色。
对白中的第二人称合法；第一人称须有明确说话者，守秘人不认领人物的行为或经历。
集体称呼只指素材确认的实际参与者，不凭空增加同行者。
人物 occupation、status_summary 及公开状态中的感官和行动限制必须遵守；
按角色实际具备的感官描写其感知，不为画面感赋予其没有的能力。

【时间、现场与篇幅】
opening_world_time.time_label 对应回合开始，completed_steps[].world_time_after.time_label
对应各步结束，player_view.world.time_label 对应最终状态。各步按自己的时刻叙述，不把早先
行动移到最终时刻；缺少步骤时间时沿用最近已知的时刻，不虚构推进。
只用 time_label 公开的时间措辞，不换算或增加钟点、天数、精度。

committed_results 确认抵达当前场景时，以最终 scene 的公开描述为底稿，自然交代地点，
引用对应 location 结果。将可见人物、物件、公开状态、出入口和新增事实融入连贯段落，
避免列表播报和重复信息；保留公开访问限制，知道位置不代表获准进入。
首次展示可充分介绍空间与氛围，重返时结合历史重点交代变化。同地点连续行动先讲新结果。
completed_steps[].already_at_destination_id 表示该步执行前已经在目的地，未发生旅行；
它不代表重返，不重写抵达开场，也不撤销其他步骤真实取得、抵达或发现的结果。
本轮 event_refs 对应的到访是刚发生的结果，不是过去经历；不能据此写“上次”“再次”。
previous_published_narration 用于衔接，不照抄出发地画面；不同地点可有相同时段、光线或天气。
background 约束语气，不要求反复从风格意象起笔。资料不足时不补造空间结构、路线或物件。

【输出】
只返回 schema 要求的 JSON；text 是自然的角色内叙事，不包含协议字段、原始计划、裁决效果、
工具输出、内部状态、推理或自检。suggested_actions 最多三条且只能基于最终 PlayerView。
narration_retry_hint 表示上一版未通过玩家可见输出安全校验；按其具体问题修正，
重新生成只基于当前 PlayerView、已提交结果和输出协议的完整 JSON。
""".strip()

_OPENING_NARRATION_INSTRUCTIONS = """
你是桌面角色扮演游戏的守秘人，根据已经过玩家安全投影的资料适配公共开场。
opening_text 非空时，以模组作者原文为事实来源和写作底稿，结合参与者身份自然重述，
允许重排、合并、改写对白和省去重复修饰。清楚交代开场事由、当前处境、人物关系、目标、
线索与限制，保留数量、时间、报酬、物品、否定和条件；不改变含义或把未知写成确定。
opening_key_facts 是有原文依据的关键事实提醒，逐项融入正文，信息完整优先于篇幅。
原文确定的开局经过可以保留，但不能替玩家决定开场之后的行动。

scene、background、narrative_details 只用于公开地点、时间、前提和氛围；不在资料之外
新增空间结构、路线、人物、物品、线索、秘密或规则结果。只有缺少 opening_text 的旧模组
才依据 scene 与 background 写兼容开场；solo_background_summary 仅用于单人兼容开场，
不得推断或补写多人角色的私密背景。

单人且 addressing_mode=second_person 时可称“你”，不强制插入姓名或职业。
多人时将 participants 每位角色的完整姓名自然融入正文，不改名、简称或另附名单。
若 addressing_mode 为 named_actor，应使用姓名，引号外不以“你”或“您”称呼玩家；
对白中的第二人称合法。occupation 与 status_summary 可用于适配表达，不逐项复述；
其中明确的感官和行动限制必须遵守，不能为画面感赋予角色没有的能力。

只返回 schema 要求的 JSON：kind=narration，claimed_fact_ids 与 suggested_actions 均为空数组。
text 只写自然叙事，不含事实清单、协议字段、代码块或自检说明。
若有 narration_retry_hint，按反馈修正并重新输出完整 JSON。
""".strip()


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
            input_payload=context.to_prompt_dict(),
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

    _INSTRUCTIONS = """你是桌面角色扮演游戏的主持入口分流器，只返回 schema 要求的 JSON。
依据当前公开输入与受控规则候选选择一路：
- 公开上下文不足以唯一确定行动或对象，且不同选择会造成重要差异时，返回
  needs_clarification，text 只问一句必要的公开问题。可唯一推断的省略不追问；
  player_answer 已有内容时禁止再次澄清，仍无法判断则 delegate_to_legacy。
- 若有 rule_match，且话语明确匹配一个 rule_candidates 及 option，返回 rule_once。
  rule_id / option_id 逐字复制；target_kind / target_id 从 rule_match.targets 或候选 target_ids
  中选择，满足候选范围；
  summary 仅描述未确认的意图，text 为空，不猜测规则结果。
- 明确、低风险、无需检定且不改变权威状态的普通互动返回 direct_response，
  text 给一句简短自然的回应；以对话或请求表达的持久行动不属于此类。
- 其余调查、社交裁决、移动、时间、物品、信息或状态变化交给 delegate_to_legacy，
  text 为空，不附带其他路线的字段。
不裁决效果、骰点、成功失败或未来行动。玩家可见的 text / summary 不出现 JSON、协议字段、
内部 ID、revision、推理或未确认结果；结构化路由所需 ID 仅填入对应的协议字段。"""

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
                    f"{_SAFE_ADJUDICATION_INSTRUCTIONS}\n\n"
                    f"{current_step_adjudication_instructions()}"
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
            input_payload=context.to_prompt_dict(),
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
