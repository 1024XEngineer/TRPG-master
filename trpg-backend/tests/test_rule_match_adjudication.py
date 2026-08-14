"""玩家话语 → 模组规则匹配 → 产出检定（#226 §2 Rule Match View）。

这条链此前没有任何覆盖，于是出现过一个只在真实模型下才暴露的故障：引擎把
`rule_candidates` 投影出来了、也序列化进了模型输入，但**提示词从没提过它存在**，所以
线上模型永远不会返回 `rule_decision`，模组的 agent_match 规则一条都不触发——一整局只有
纯叙事，没有任何检定。能力测试没抓到，是因为它们用脚本化 planner 把效果直接注入，绕过
了裁决器。

这里从两端把链子钉住：

* `_DeterministicStepAdjudicator` 命中规则时必须交出所有权（rule_decision + 检定 +
  空效果）——这是 fake provider 下的真实行为；
* 送进模型的上下文必须真的带着 `rule_candidates`，并且提示词必须真的教模型怎么用它
  ——真实模型的行为无法确定性断言，但"信息有没有到模型面前"可以。
"""

from __future__ import annotations

import pathlib
from typing import Literal

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    ActionTarget,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    LocationContextView,
    ModuleContentV3,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PlayerView,
    RequiredAdjudicationCheck,
    SingleActionDecision,
)
from collaboration_framework.engine import InMemoryEngineStore, RuleEngineService
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import ActorState
from collaboration_framework.host.adapters.openai_agents import (
    current_step_adjudication_instructions,
    host_turn_decision_instructions,
)
from collaboration_framework.host.application import PlayerViewProjector, TurnExecutionError
from collaboration_framework.host.schemas import (
    ActionPlanStepContext,
    HostAgentContext,
    RecentTurnContext,
)

from app.adapters.openai_models import _SAFE_ADJUDICATION_INSTRUCTIONS
from app.core.action_plan_turn import (
    DeterministicHostTurnDecisionModel,
    _deterministic_step_adjudication,
    _DeterministicStepAdjudicator,
    _match_travel_target,
    _normalize_single_travel_decision,
    _RuleFirstStepAdjudicator,
)

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agent-collaboration-framework"
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)


def _content() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


async def _cemetery_context(
    utterance: str,
    *,
    step_kind: Literal["action", "dialogue", "travel"] = "action",
    semantic_goal: str | None = None,
    scene_id: str = "cemetery",
) -> ActionPlanStepContext:
    """把调查员放到墓地，那里 melodias 的 observe_caretaker 规则在射程内。"""

    content = _content()
    actors = {
        "pc_1": ActorState(
            player_id="p1",
            name="调查员",
            source_character_id="c1",
            source_character_version=1,
            state={"skills": {"spot-hidden": 60, "psychology": 50}},
        )
    }
    state = create_initial_game_state(content, room_id="r1", actors=actors).model_copy(
        update={"scene_id": scene_id},
        deep=True,
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    engine = RuleEngineService(store)
    projector = PlayerViewProjector(engine)
    player_input = PlayerInput(
        room_id="r1",
        player_id="p1",
        actor_id="pc_1",
        client_action_id="act-1",
        utterance=utterance,
    )
    view = await projector.project(player_input)
    return ActionPlanStepContext(
        player_input=player_input,
        plan_id="plan-1",
        plan_goal=utterance,
        step_index=0,
        step_request_id="act-1-step-0",
        step=ActionPlanStep(
            kind=step_kind,
            semantic_goal=semantic_goal or utterance,
        ),
        player_view=view,
        keeper_capabilities=await projector.keeper_capabilities(
            player_input,
            expected_revision=view.revision,
        ),
    )


def _located(view: PlayerView) -> LocationContextView:
    """v3 投影必然带 location_context；断言它在，顺带把 Optional 收窄掉。"""

    location_context = view.location_context
    assert location_context is not None
    return location_context


async def test_engine_publishes_rule_candidates_where_the_actor_stands() -> None:
    """规则匹配的前提：引擎得先把候选发出来。"""

    context = await _cemetery_context("仔细观察守墓人")

    assert context.keeper_capabilities is not None
    rule_ids = {candidate.rule_id for candidate in context.keeper_capabilities.rule_candidates}
    assert "observe_caretaker" in rule_ids


async def test_rule_candidates_reach_the_model_payload() -> None:
    """候选必须真的进到发给模型的 JSON 里。

    这一层单独钉住，是因为它坏掉的时候不会有任何报错：模型只会安静地退回
    narrative_only，看起来像"模型不想触发剧情"，而不是"我们没告诉它有剧情"。
    """

    context = await _cemetery_context("仔细观察守墓人")

    payload = context.to_json_dict()
    world_profile = payload["keeper_capabilities"]["world_profile"]
    assert world_profile == {
        "era": "1920s 美国禁酒令时期",
        "region": "密歇根州阿诺兹堡",
        "technology_level": "早期汽车与电报",
        "tone": "安静、克制、带哥特气息",
        "forbidden_content": ["提前揭示道格拉斯的食尸鬼身份"],
    }
    candidates = payload["keeper_capabilities"]["rule_candidates"]
    assert candidates, "rule_candidates 没有进入模型输入"
    observe = next(item for item in candidates if item["rule_id"] == "observe_caretaker")
    assert observe["options"], "规则候选必须带上可选做法，否则模型无从选择"


def test_prompt_teaches_the_model_to_use_rule_candidates() -> None:
    """提示词必须教模型用 rule_candidates —— 这正是当初漏掉的那一环。

    断言的是词汇本身：只要模型看不到 `rule_decision` 这个出口，引擎把候选投影得
    再全也没有用。
    """

    assert "rule_candidates" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "rule_decision" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "option_id" in _SAFE_ADJUDICATION_INSTRUCTIONS


async def test_matched_rule_hands_ownership_to_the_rule() -> None:
    """命中规则时：交出 rule_decision 与检定，且不自带任何效果（#226 §5）。

    用词照抄模组发布的词汇（`semantic_hints` 里的"梅洛迪亚斯·杰弗逊"与 option 的
    "用侦查"）。确定性裁决器只做字面匹配——它是 fake provider 的替身，真实模型才做
    语义判断。用玩家的自然说法在这里匹配不上，见下一条用例。
    """

    context = await _cemetery_context("用侦查观察梅洛迪亚斯·杰弗逊")
    assert context.keeper_capabilities is not None
    adjudication = await _DeterministicStepAdjudicator().adjudicate(context)

    assert adjudication.rule_decision is not None
    assert adjudication.rule_decision.rule_id == "observe_caretaker"
    assert isinstance(adjudication.check, RequiredAdjudicationCheck)
    assert adjudication.check.candidates
    # 后果归规则所有：这里自带效果会被忽略，写了反而误导。
    assert adjudication.success_effects == ()
    assert adjudication.failure_effects == ()
    # 选中的 option 必须来自引擎发布的菜单，不能是自造的。
    published = {
        option.id
        for candidate in context.keeper_capabilities.rule_candidates
        if candidate.rule_id == "observe_caretaker"
        for option in candidate.options
    }
    assert adjudication.rule_decision.option_id in published


async def test_natural_chinese_action_family_reaches_the_unique_rule() -> None:
    """稳定动作族词汇可直接命中唯一候选，不必依赖模型猜测。"""

    adjudication = await _DeterministicStepAdjudicator().adjudicate(
        await _cemetery_context("仔细观察守墓人")
    )

    assert adjudication.rule_decision is not None
    assert adjudication.rule_decision.rule_id == "observe_caretaker"
    assert isinstance(adjudication.check, RequiredAdjudicationCheck)


async def test_fake_single_action_uses_the_same_rule_match_view() -> None:
    """单动作不能绕过 v3 Rule Match 而静默退化成纯叙事。"""

    step_context = await _cemetery_context("仔细观察守墓人")
    decision = await DeterministicHostTurnDecisionModel().generate(
        HostAgentContext(
            player_input=step_context.player_input,
            player_view=step_context.player_view,
            recent_history=RecentTurnContext.empty(
                player_input=step_context.player_input,
                player_view=step_context.player_view,
            ),
            keeper_capabilities=step_context.keeper_capabilities,
        )
    )

    assert isinstance(decision, SingleActionDecision)
    assert decision.adjudication.rule_decision is not None
    assert decision.adjudication.rule_decision.rule_id == "observe_caretaker"
    assert isinstance(decision.adjudication.check, RequiredAdjudicationCheck)


async def test_rule_first_adjudicator_does_not_call_model_for_unique_match() -> None:
    """线上裁决对唯一 Match View 候选也走确定性路径。"""

    class FailingFallback:
        async def adjudicate(self, context):
            del context
            raise AssertionError("唯一规则候选不应调用模型")

    adjudication = await _RuleFirstStepAdjudicator(FailingFallback()).adjudicate(
        await _cemetery_context("仔细观察守墓人")
    )

    assert adjudication.rule_decision is not None
    assert adjudication.rule_decision.rule_id == "observe_caretaker"


async def test_visible_dialogue_does_not_call_model_or_reveal_information() -> None:
    """普通对话不应因二次模型调用失败，也不能绕过规则凭空揭示线索。"""

    class FailingFallback:
        async def adjudicate(self, context):
            del context
            raise AssertionError("可见人物的普通对话不应调用模型")

    adjudication = await _RuleFirstStepAdjudicator(FailingFallback()).adjudicate(
        await _cemetery_context(
            "前往公墓，询问守墓人是否见过有人常来墓地",
            step_kind="dialogue",
            semantic_goal="询问守墓人梅洛迪亚斯是否见过有人常来墓地",
        )
    )

    assert adjudication.target.kind == "entity"
    assert adjudication.target.id == "melodias"
    assert adjudication.method.family == "talk"
    assert isinstance(adjudication.check, NoAdjudicationCheck)
    assert adjudication.rule_decision is None
    assert len(adjudication.success_effects) == 1
    assert isinstance(adjudication.success_effects[0], NarrativeOnlyEffect)


async def test_unknown_ordinary_travel_is_resolved_without_a_model_round_trip() -> None:
    """#212 普通动态地点要真的建出来。

    只靠提示词不管用：模型反复回答「阿诺兹堡没有挂牌的旅店」，玩家因此永远
    住不进任何旅店。泛指一个普通去处、且不与任何已写地点重名时，这里确定性
    地登记并进入，不再看模型脸色。
    """

    class FailingFallback:
        async def adjudicate(self, context):
            del context
            raise AssertionError("普通去处不应该还要问模型")

    context = await _cemetery_context(
        "我想去小镇上的旅馆休息到晚上",
        step_kind="travel",
        semantic_goal="前往小镇上的旅馆",
    )
    adjudication = await _RuleFirstStepAdjudicator(FailingFallback()).adjudicate(context)

    assert [effect.type for effect in adjudication.success_effects] == [
        "ensure_runtime_location",
        "enter_location",
    ]
    created, entered = adjudication.success_effects
    assert isinstance(created, EnsureRuntimeLocationEffect)
    assert isinstance(entered, EnterLocationEffect)
    # 挂在公共路网上，而不是玩家此刻站着的墓地。
    assert created.connected_location_id == "arnoldsburg_streets"
    assert adjudication.target.id == "arnoldsburg_streets"
    assert entered.location_id == created.location_id

    normalized = _normalize_single_travel_decision(
        SingleActionDecision(adjudication=adjudication),
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    normalized_created = next(
        effect
        for effect in normalized.adjudication.success_effects
        if isinstance(effect, EnsureRuntimeLocationEffect)
    )
    normalized_entered = next(
        effect
        for effect in normalized.adjudication.success_effects
        if isinstance(effect, EnterLocationEffect)
    )
    # 新地点在提交前不能作为 target；连接锚点保留，同时进入刚创建的地点。
    assert normalized.adjudication.target.id == "arnoldsburg_streets"
    assert normalized_entered.location_id == normalized_created.location_id


@pytest.mark.asyncio
async def test_runtime_venue_can_be_reused_through_a_synonym() -> None:
    """Runtime 展示名与玩家用词不同时，仍应命中原地点。"""

    context = await _cemetery_context("去旅馆", step_kind="travel")
    template = context.player_view.known_locations[0]
    runtime_inn = template.model_copy(
        update={
            "id": "ambient_inn",
            "kind": "site",
            "name": "镇上的旅店",
            "existence": "known",
            "localization": "located",
            "access": "reachable",
            "visited": True,
        },
        deep=True,
    )
    context = context.model_copy(
        update={
            "player_view": context.player_view.model_copy(
                update={
                    "known_locations": (*context.player_view.known_locations, runtime_inn),
                },
                deep=True,
            )
        },
        deep=True,
    )

    adjudication = _deterministic_step_adjudication(context)

    assert adjudication is not None
    assert adjudication.target.id == "ambient_inn"
    assert adjudication.success_effects == (EnterLocationEffect(location_id="ambient_inn"),)
    assert all(
        not isinstance(effect, EnsureRuntimeLocationEffect)
        for effect in adjudication.success_effects
    )


@pytest.mark.asyncio
async def test_travel_to_current_runtime_venue_is_a_successful_noop() -> None:
    """已在同一 Runtime 地点时，同义地名不应触发重复进入或澄清。"""

    context = await _cemetery_context("去旅馆", step_kind="travel")
    template = context.player_view.known_locations[0]
    runtime_inn = template.model_copy(
        update={
            "id": "ambient_inn",
            "kind": "site",
            "name": "镇上的旅店",
            "existence": "known",
            "localization": "located",
            "access": "reachable",
            "visited": True,
        },
        deep=True,
    )
    current_view = context.player_view.model_copy(
        update={
            "scene": context.player_view.scene.model_copy(
                update={"id": "ambient_inn", "name": "镇上的旅店"},
                deep=True,
            ),
            "location_context": _located(context.player_view).model_copy(
                update={"current_location_id": "ambient_inn"},
                deep=True,
            ),
            "known_locations": (*context.player_view.known_locations, runtime_inn),
        },
        deep=True,
    )
    context = context.model_copy(update={"player_view": current_view}, deep=True)

    adjudication = _deterministic_step_adjudication(context)

    assert adjudication is not None
    assert adjudication.method.family == "action"
    assert adjudication.persistence_intent == "none"
    assert adjudication.success_effects == (NarrativeOnlyEffect(),)
    assert adjudication.summary == "已经位于镇上的旅店"

    wrong_model_decision = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=current_view.revision,
            actor_id="pc_1",
            summary="前往其他地点",
            target=ActionTarget(kind="location", id="cemetery"),
            method=ActionMethod(family="travel", description="前往其他地点"),
            persistence_intent="location",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="cemetery"),),
        )
    )
    normalized = _normalize_single_travel_decision(
        wrong_model_decision,
        player_input=context.player_input,
        view=current_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    assert normalized.adjudication.target.id == "ambient_inn"
    assert normalized.adjudication.persistence_intent == "none"
    assert normalized.adjudication.success_effects == (NarrativeOnlyEffect(),)


@pytest.mark.asyncio
async def test_travel_matching_uses_destination_name_not_shared_prefix() -> None:
    """地域修饰部分相同时，必须由地点核心名称决定目的地。"""

    context = await _cemetery_context(
        "依次前往多个地点",
        step_kind="travel",
        semantic_goal="前往镇上的图书馆",
    )
    template = context.player_view.known_locations[0]
    runtime_inn = template.model_copy(
        update={
            "id": "ambient_inn",
            "kind": "site",
            "name": "镇上的旅店",
            "existence": "known",
            "localization": "located",
            "access": "reachable",
            "visited": True,
        },
        deep=True,
    )
    current_view = context.player_view.model_copy(
        update={
            "scene": context.player_view.scene.model_copy(
                update={"id": "ambient_inn", "name": "镇上的旅店"},
                deep=True,
            ),
            "location_context": _located(context.player_view).model_copy(
                update={"current_location_id": "ambient_inn"},
                deep=True,
            ),
            "known_locations": (*context.player_view.known_locations, runtime_inn),
        },
        deep=True,
    )
    context = context.model_copy(update={"player_view": current_view}, deep=True)

    destination = _match_travel_target(current_view, context.step.semantic_goal)
    assert destination is not None
    assert destination.id == "library"

    adjudication = _deterministic_step_adjudication(context)
    assert adjudication is not None
    assert adjudication.target.id == "library"
    assert adjudication.success_effects == (EnterLocationEffect(location_id="library"),)


async def test_planner_cannot_invent_ambient_venue_for_npc_search() -> None:
    """“找 NPC”不能因模型擅自补写“住处”而创建无关的动态地点。"""

    class RecordingFallback:
        calls = 0

        async def adjudicate(self, context):
            self.calls += 1
            return ActionAdjudication(
                request_id=context.step_request_id,
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=context.step.semantic_goal,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="travel", description=context.step.semantic_goal),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )

    fallback = RecordingFallback()
    adjudication = await _RuleFirstStepAdjudicator(fallback).adjudicate(
        await _cemetery_context(
            "去找守墓人",
            step_kind="travel",
            semantic_goal="前往守墓人的住处寻找守墓人",
        )
    )

    assert fallback.calls == 1
    assert all(
        not isinstance(effect, EnsureRuntimeLocationEffect)
        for effect in adjudication.success_effects
    )


@pytest.mark.asyncio
async def test_single_travel_prefers_explicit_player_destination() -> None:
    """模型把“去墓地”裁成办公室时，玩家原话中的明确地点必须覆盖模型。"""

    context = await _cemetery_context("去墓地", step_kind="travel", scene_id="thomas_office")
    wrong = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=context.player_view.revision,
            actor_id="pc_1",
            summary="去墓地",
            target=ActionTarget(kind="location", id="thomas_office"),
            method=ActionMethod(family="travel", description="去墓地"),
            persistence_intent="none",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="thomas_office"),),
        )
    )

    normalized = _normalize_single_travel_decision(
        wrong,
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    assert normalized.adjudication.target.id == "cemetery"
    assert normalized.adjudication.persistence_intent == "location"
    entered = next(
        effect
        for effect in normalized.adjudication.success_effects
        if isinstance(effect, EnterLocationEffect)
    )
    assert entered.location_id == "cemetery"


@pytest.mark.asyncio
async def test_single_travel_replans_unknown_destination_instead_of_substituting() -> None:
    """单意图模型不得把未列出的玩家目的地换成一个合法的已知 id。"""

    context = await _cemetery_context("去教堂看看", step_kind="travel")
    wrong = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=context.player_view.revision,
            actor_id="pc_1",
            summary="前往阿诺兹堡公共墓地",
            target=ActionTarget(kind="location", id="cemetery"),
            method=ActionMethod(family="travel", description="前往阿诺兹堡公共墓地"),
            persistence_intent="location",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="cemetery"),),
        )
    )

    normalized = _normalize_single_travel_decision(
        wrong,
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    assert normalized.adjudication.summary == "去教堂看看"
    assert normalized.adjudication.target.id == context.player_view.scene.id
    assert normalized.adjudication.persistence_intent == "location"
    assert normalized.adjudication.success_effects == (NarrativeOnlyEffect(),)


@pytest.mark.asyncio
async def test_unknown_destination_narrative_only_still_gets_bounded_creation_repair() -> None:
    """模型直接放弃未知地点时，也要进入同一条创建修复路径。"""

    context = await _cemetery_context("进入诊所", step_kind="travel")
    abandoned = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=context.player_view.revision,
            actor_id="pc_1",
            summary="无法确认行动",
            target=ActionTarget(kind="location", id="cemetery"),
            method=ActionMethod(family="action", description="无法确认行动"),
            persistence_intent="none",
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )
    )

    normalized = _normalize_single_travel_decision(
        abandoned,
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    assert normalized.adjudication.summary == "进入诊所"
    assert normalized.adjudication.method.family == "travel"
    assert normalized.adjudication.persistence_intent == "location"


@pytest.mark.asyncio
async def test_step_travel_rejects_known_location_substitution_for_unknown_destination() -> None:
    """二次地点裁决仍选错已知地点时，必须零写入停止。"""

    class WrongLocationFallback:
        async def adjudicate(self, context):
            return ActionAdjudication(
                request_id=context.step_request_id,
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary="前往阿诺兹堡公共墓地",
                target=ActionTarget(kind="location", id="cemetery"),
                method=ActionMethod(family="travel", description="前往阿诺兹堡公共墓地"),
                persistence_intent="location",
                check=NoAdjudicationCheck(),
                success_effects=(EnterLocationEffect(location_id="cemetery"),),
            )

    with pytest.raises(TurnExecutionError) as captured:
        await _RuleFirstStepAdjudicator(WrongLocationFallback()).adjudicate(
            await _cemetery_context(
                "去教堂看看",
                step_kind="travel",
                semantic_goal="前往教堂",
            )
        )

    assert captured.value.code == "TRAVEL_DESTINATION_NOT_FOUND"
    assert captured.value.retryable is False


@pytest.mark.asyncio
async def test_single_travel_builds_plan_when_companion_is_elsewhere() -> None:
    """同行 NPC 不在身边时，必须先会合再前往玩家指定目的地。"""

    context = await _cemetery_context("带托马斯去墓地", step_kind="travel")
    wrong = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=context.player_view.revision,
            actor_id="pc_1",
            summary="带托马斯去墓地",
            target=ActionTarget(kind="location", id="thomas_office"),
            method=ActionMethod(family="travel", description="带托马斯去墓地"),
            persistence_intent="none",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="thomas_office"),),
        )
    )

    normalized = _normalize_single_travel_decision(
        wrong,
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, ActionPlan)
    assert [step.kind for step in normalized.steps] == ["travel", "travel"]
    assert "托马斯" in normalized.steps[0].semantic_goal
    assert "会客室" in normalized.steps[0].semantic_goal
    assert "墓地" in normalized.steps[1].semantic_goal


@pytest.mark.asyncio
async def test_single_travel_moves_named_companion_present_with_player() -> None:
    """“带他”由裁决摘要消解后，身边 NPC 必须获得权威移动效果。"""

    context = await _cemetery_context(
        "带他去找守墓人",
        step_kind="travel",
        scene_id="thomas_office",
    )
    decision = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="model-owned",
            source_revision=context.player_view.revision,
            actor_id="pc_1",
            summary="带托马斯去找守墓人",
            target=ActionTarget(kind="location", id="cemetery"),
            method=ActionMethod(family="travel", description="和托马斯一起前往墓地"),
            persistence_intent="location",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="cemetery"),),
        )
    )

    normalized = _normalize_single_travel_decision(
        decision,
        player_input=context.player_input,
        view=context.player_view,
        capabilities=context.keeper_capabilities,
    )

    assert isinstance(normalized, SingleActionDecision)
    moved = tuple(
        effect
        for effect in normalized.adjudication.success_effects
        if isinstance(effect, MoveEntityEffect)
    )
    assert moved == (MoveEntityEffect(entity_id="thomas", location_id="cemetery"),)


async def test_ambient_venue_never_shadows_an_authored_location() -> None:
    """重名的去处必须留给模组自己揭示。

    地下酒吧是模组写过的隐藏地点。如果这里也能凭「酒吧」两个字造一个同名
    运行时地点，玩家就能绕过隐藏边条件，直接走进一个冒牌的地下酒吧。
    """

    class RecordingFallback:
        calls = 0

        async def adjudicate(self, context):
            self.calls += 1
            return ActionAdjudication(
                request_id=context.step_request_id,
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=context.step.semantic_goal,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="travel", description=context.step.semantic_goal),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )

    fallback = RecordingFallback()
    with pytest.raises(TurnExecutionError) as captured:
        await _RuleFirstStepAdjudicator(fallback).adjudicate(
            await _cemetery_context(
                "我想去地下酒吧",
                step_kind="travel",
                semantic_goal="前往地下酒吧",
            )
        )

    assert fallback.calls == 1
    assert captured.value.code == "TRAVEL_DESTINATION_NOT_FOUND"


def test_prompt_allows_ordinary_runtime_location_without_false_clarification() -> None:
    assert "不应追问" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "具体实例" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "ensure_runtime_location、enter_location" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "地点的功能类别、规模或专业性本身也不构成拒绝理由" in (_SAFE_ADJUDICATION_INSTRUCTIONS)
    assert "不要仅因玩家没有指定普通内容的具体名称或实例而要求澄清" in (
        current_step_adjudication_instructions()
    )
    assert "不得把人物和可携带物件的" in current_step_adjudication_instructions()
    assert "地点的功能类别、规模或专业性本身也不构成拒绝理由" in (
        current_step_adjudication_instructions()
    )


def test_prompt_preserves_terminal_actions_and_distinguishes_service_verbs() -> None:
    planning = host_turn_decision_instructions(ActionPlanPolicy())

    assert "句末动词" in planning
    assert "相邻书写、省略连词" in planning
    assert "前置交互 + 等待/休息/使用/继续操作" in planning
    assert "服务请求、惯用语或抽象含义" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "不得映射成\n物体 open" in _SAFE_ADJUDICATION_INSTRUCTIONS


def test_prompt_forbids_semantically_unrelated_target_substitution() -> None:
    assert "只证明一个 id 在协议上可以引用，不证明它与玩家原话语义匹配" in (
        _SAFE_ADJUDICATION_INSTRUCTIONS
    )
    assert "绝不能为了得到一个合法\nid，就把当前 scene 或其他已知地点当作替代目标" in (
        _SAFE_ADJUDICATION_INSTRUCTIONS
    )
    assert "过去可能错误的映射延续到本回合" in _SAFE_ADJUDICATION_INSTRUCTIONS

    step_instructions = current_step_adjudication_instructions()
    assert "不能覆盖玩家本回合明确指定的对象、地点" in step_instructions
    assert "不得进入替代地点、推进时间" in step_instructions


def test_prompt_defines_runtime_item_custody_and_consumption() -> None:
    assert "player_view.scene.loose_items[].id" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "player_view.inventory[].id" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "这样物品才会进入背包" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "move_entity(location_id=当前 scene.id)" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "consume_entity" in _SAFE_ADJUDICATION_INSTRUCTIONS
    step_instructions = current_step_adjudication_instructions()
    assert "世界一致性" in step_instructions
    assert "场景依据" in step_instructions
    assert "普通性" in step_instructions
    assert "零剧情权限" in step_instructions
    assert "Canon 不替代" in step_instructions
    assert "拾取要在同一 effects 序列继续 move_entity" in step_instructions
    assert "新建物品尚不是合法 target" in step_instructions
    assert "keeper_capabilities.world_profile" in step_instructions
    assert "明确取得物品决策表" in step_instructions
    assert "没有具体实体所以只能留在原处" in step_instructions
    assert "published_narration 只是普通内容的软场景依据" in step_instructions
    assert "固定实体\n不能因此进入背包" in step_instructions


def test_prompt_requires_exact_existing_entity_match_before_runtime_creation() -> None:
    assert "scene.visible_entities、scene.loose_items 与" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "target 必须保持为当前 player_view.scene.id" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert (
        "不能\n  仅因某物出现在 scene.visible_entities 或 "
        "keeper_capabilities.entities 就把它移入背包" in _SAFE_ADJUDICATION_INSTRUCTIONS
    )
    assert "published_narration 只是普通内容的软场景依据" in (_SAFE_ADJUDICATION_INSTRUCTIONS)
    assert "明确取得物品决策表" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "不得创建便携\n  替身" in _SAFE_ADJUDICATION_INSTRUCTIONS
    step_instructions = current_step_adjudication_instructions()
    assert "keeper_capabilities 里的实体不代表玩家此刻看得见" in step_instructions
    assert "是效果能力词表，不自动成为可直接作用的 target" in step_instructions
    assert "类别、数量、所有者、唯一性、状态" in step_instructions
    assert "五本失窃藏书" not in step_instructions
    assert "五本失窃藏书" not in _SAFE_ADJUDICATION_INSTRUCTIONS


@pytest.mark.parametrize(
    "utterance",
    ["我在墓地里随便走走", "和守墓人聊聊天气"],
)
async def test_unmatched_utterance_falls_back_to_plain_narration(utterance: str) -> None:
    """规则没覆盖的日常互动照旧走自由发挥，不能硬套一条规则。"""

    adjudication = await _DeterministicStepAdjudicator().adjudicate(
        await _cemetery_context(utterance)
    )

    assert adjudication.rule_decision is None
