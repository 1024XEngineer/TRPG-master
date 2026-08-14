"""Opt-in real-model probe for context-safe runtime creation.

Runtime creation is intentionally semantic: the Engine can verify IDs and
effect ordering, while the step Agent judges items against their current scene
and locations against WorldProfile/background plus Canon conflicts. This smoke
test exercises that production decision boundary against the configured
provider. It is skipped in CI unless explicitly enabled.
"""

from __future__ import annotations

import json
import os

import pytest
from collaboration_framework.contracts import (
    ActionPlan,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    MoveEntityEffect,
)
from collaboration_framework.host.schemas import (
    HostAgentContext,
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
)

from app.adapters.openai_models import PromptActionPlanStepAdjudicator, PromptHostTurnDecisionModel
from app.core.config import Settings
from tests.test_play_sim_real_model import _structured_client
from tests.test_rule_match_adjudication import _cemetery_context

RUN_SMOKE = os.getenv("RUN_REAL_MODEL_CREATION_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_SMOKE,
    reason="set RUN_REAL_MODEL_CREATION_SMOKE=1 to call the configured provider",
)


CASES = (
    (
        "已有窗户必须复用",
        "我打开书房窗户。",
        "kimball_study",
        "existing_entity",
    ),
    (
        "墓地普通石子可拾取",
        "我从墓地地上捡起一枚普通石子，装进背包。",
        "cemetery",
        "ordinary_item",
    ),
    (
        "墓地普通树枝可拾取",
        "我从墓地地上捡起一根掉落的枯树枝，装进背包。",
        "cemetery",
        "ordinary_item",
    ),
    (
        "地上不能凭空出现军用炸弹",
        "我从地上捡起一枚完好的军用炸弹，装进背包。",
        "cemetery",
        "unsafe_item",
    ),
    (
        "书房普通书可拿走",
        "我从书房书架上随手拿一本没有特殊标记的普通书，装进背包。",
        "kimball_study",
        "ordinary_item",
    ),
    (
        "书房空白笔记本可拿走",
        "我从书桌上拿走一本空白的普通笔记本，装进背包。",
        "kimball_study",
        "ordinary_item",
    ),
    (
        "书房不能声明秘密墓地通道",
        "我发现书架后有一条秘密地下通道直通墓地，现在进入地下通道。",
        "kimball_study",
        "secret_location",
    ),
    (
        "符合背景的诊所可以创建",
        "前往镇上的诊所。",
        "cemetery",
        "background_location",
    ),
    (
        "符合背景的教堂可以创建",
        "前往镇上的教堂。",
        "cemetery",
        "background_location",
    ),
    (
        "时代冲突的地点不能创建",
        "前往镇上的量子传送站。",
        "cemetery",
        "unsafe_location",
    ),
)


async def test_real_model_keeps_terminal_action_in_compound_goal() -> None:
    """句末的可执行动作不能被前置交互吸收或丢失。"""

    settings = Settings()
    assert settings.host_model_provider != "fake"
    step_context = await _cemetery_context(
        "去旅馆，开一间房休息",
        step_kind="travel",
    )
    decision = await PromptHostTurnDecisionModel(_structured_client(settings)).generate(
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

    assert isinstance(decision, ActionPlan)
    assert [step.kind for step in decision.steps] == ["travel", "action", "rest"]
    combined_goals = " ".join(step.semantic_goal for step in decision.steps)
    assert "旅馆" in combined_goals
    assert "房" in combined_goals
    assert "休息" in combined_goals


async def test_real_model_does_not_treat_service_request_as_physical_open() -> None:
    """服务语义的“开”不得伪造物体开启状态。"""

    settings = Settings()
    assert settings.host_model_provider != "fake"
    step_context = await _cemetery_context(
        "开一间房",
        step_kind="action",
    )
    result = await PromptActionPlanStepAdjudicator(_structured_client(settings)).adjudicate(
        step_context
    )

    assert result.method.family != "open"
    assert result.persistence_intent != "object_state"


async def test_real_model_materializes_ordinary_item_from_soft_narration_on_pickup() -> None:
    settings = Settings()
    assert settings.host_model_provider != "fake"
    context = await _cemetery_context(
        "把刚才提到的那本诗集装进背包",
        scene_id="kimball_study",
        step_kind="action",
    )
    history = RecentTurnContext(
        room_id=context.player_input.room_id,
        viewer_player_id=context.player_input.player_id,
        as_of_revision=context.player_view.revision,
        turns=(
            RecentTurn(
                correlation_id="previous-description",
                source_player_id=context.player_input.player_id,
                source_actor_id=context.player_input.actor_id,
                scene_id=context.player_view.scene.id,
                player_utterance=VisibleHistoryText(
                    text="书架上还有别的读物吗？",
                    visibility="player_scoped",
                ),
                published_narration=VisibleHistoryText(
                    text="书架上还零星放着几本小说和诗集。",
                    visibility="player_scoped",
                ),
            ),
        ),
    )

    result = await PromptActionPlanStepAdjudicator(_structured_client(settings)).adjudicate(
        context.model_copy(update={"recent_history": history})
    )

    effects = result.success_effects
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
    created, moved = effects[0], effects[1]
    assert isinstance(created, EnsureRuntimeEntityEffect)
    assert isinstance(moved, MoveEntityEffect)
    assert created.entity_id == moved.entity_id
    assert result.target.kind == "location"
    assert result.target.id == context.player_view.scene.id


@pytest.mark.parametrize(
    ("label", "utterance", "scene_id", "expectation"),
    CASES,
    ids=(
        "existing-window",
        "ordinary-pebble",
        "ordinary-branch",
        "unsafe-bomb",
        "ordinary-book",
        "ordinary-notebook",
        "secret-passage",
        "background-clinic",
        "background-church",
        "anachronistic-location",
    ),
)
async def test_real_model_respects_runtime_creation_boundary(
    label: str,
    utterance: str,
    scene_id: str,
    expectation: str,
) -> None:
    settings = Settings()
    assert settings.host_model_provider != "fake"
    adjudicator = PromptActionPlanStepAdjudicator(_structured_client(settings))
    step_kind = "travel" if expectation.endswith("location") else "action"
    result = await adjudicator.adjudicate(
        await _cemetery_context(
            utterance,
            scene_id=scene_id,
            step_kind=step_kind,
        )
    )
    effects = [effect.type for effect in result.success_effects]
    print(
        json.dumps(
            {
                "label": label,
                "target": {"kind": result.target.kind, "id": result.target.id},
                "summary": result.summary,
                "persistence_intent": result.persistence_intent,
                "effects": [effect.model_dump(mode="json") for effect in result.success_effects],
            },
            ensure_ascii=False,
        )
    )

    if expectation == "existing_entity":
        assert result.target.id == "study_window"
        assert "ensure_runtime_entity" not in effects
    elif expectation == "ordinary_item":
        assert effects[:2] == ["ensure_runtime_entity", "move_entity"]
        assert result.persistence_intent == "inventory"
        assert result.target.kind == "location"
        assert result.target.id == scene_id
    elif expectation == "unsafe_item":
        assert "ensure_runtime_entity" not in effects
    elif expectation == "secret_location":
        assert "ensure_runtime_location" not in effects
        assert "enter_location" not in effects
    elif expectation == "background_location":
        assert effects[:2] == ["ensure_runtime_location", "enter_location"]
        assert result.persistence_intent == "location"
        assert result.target.kind == "location"
        created_location, entered = result.success_effects[0], result.success_effects[1]
        assert isinstance(created_location, EnsureRuntimeLocationEffect)
        assert isinstance(entered, EnterLocationEffect)
        assert result.target.id != created_location.location_id
        assert entered.location_id == created_location.location_id
    elif expectation == "unsafe_location":
        assert "ensure_runtime_location" not in effects
        assert "enter_location" not in effects
    else:  # pragma: no cover - CASES are static and exhaustive.
        raise AssertionError(f"unknown expectation: {expectation}")
