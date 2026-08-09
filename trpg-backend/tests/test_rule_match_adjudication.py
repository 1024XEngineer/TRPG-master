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
    ActionPlanStep,
    ActionTarget,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    ModuleContentV3,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    RequiredAdjudicationCheck,
)
from collaboration_framework.engine import InMemoryEngineStore, RuleEngineService
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import ActorState
from collaboration_framework.host.adapters.openai_agents import (
    current_step_adjudication_instructions,
)
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.schemas import ActionPlanStepContext

from app.adapters.openai_models import _SAFE_ADJUDICATION_INSTRUCTIONS
from app.core.action_plan_turn import (
    _DeterministicStepAdjudicator,
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
        update={"scene_id": "cemetery"},
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


async def test_unknown_ordinary_travel_reaches_runtime_location_agent() -> None:
    """#212 普通动态地点必须交给 Agent 提议，不能被可见地点快路径提前拒绝。"""

    class RuntimeLocationFallback:
        calls = 0

        async def adjudicate(self, context):
            self.calls += 1
            return ActionAdjudication(
                request_id=context.step_request_id,
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary="在阿诺兹堡登记一家普通旅店并前往休息",
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="travel", description=context.step.semantic_goal),
                check=NoAdjudicationCheck(),
                success_effects=(
                    EnsureRuntimeLocationEffect(
                        location_id="runtime_arnoldsburg_inn",
                        name="阿诺兹堡旅店",
                        parent_location_id="town",
                        connected_location_id="street",
                    ),
                    EnterLocationEffect(location_id="runtime_arnoldsburg_inn"),
                ),
            )

    fallback = RuntimeLocationFallback()
    adjudication = await _RuleFirstStepAdjudicator(fallback).adjudicate(
        await _cemetery_context(
            "我想去小镇上的旅馆休息到晚上",
            step_kind="travel",
            semantic_goal="前往小镇上的旅馆",
        )
    )

    assert fallback.calls == 1
    assert adjudication.target.id == "cemetery"
    assert [effect.type for effect in adjudication.success_effects] == [
        "ensure_runtime_location",
        "enter_location",
    ]


def test_prompt_allows_ordinary_runtime_location_without_false_clarification() -> None:
    assert "不应反问具体哪一家" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "ensure_runtime_location、enter_location" in _SAFE_ADJUDICATION_INSTRUCTIONS
    assert "不要仅因玩家没有指定店名而要求澄清" in current_step_adjudication_instructions()


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
