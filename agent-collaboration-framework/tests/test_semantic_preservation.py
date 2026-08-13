from __future__ import annotations

import asyncio
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlanStep,
    ActionTarget,
    ChangeEntityStateEffect,
    ConsumeEntityEffect,
    EnterLocationEffect,
    ModuleContent,
    NoAdjudicationCheck,
    PlayerInput,
    RequiredAdjudicationCheck,
    SkillCheckCandidate,
    ValidationFeedback,
)
from collaboration_framework.engine import (
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.application.semantic_preservation import (
    compare_repair_semantics,
)

ROOT = Path(__file__).resolve().parents[1]


def player_input(
    action_id: str = "semantic-test",
    utterance: str = "调查书架",
) -> PlayerInput:
    return PlayerInput(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        client_action_id=action_id,
        utterance=utterance,
    )


def runtime():
    module = ModuleContent.model_validate_json(
        (ROOT / "fixtures/demo-module.json").read_text(encoding="utf-8")
    )
    state = GameState.model_validate_json(
        (ROOT / "fixtures/demo-state.json").read_text(encoding="utf-8")
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    return module, store, PlayerViewProjector(RuleEngineService(store))


def _feedback(
    *,
    code: str = "TARGET_UNAVAILABLE",
    affected_effects=(),
) -> ValidationFeedback:
    return ValidationFeedback(
        status="rejected",
        code=code,
        repairability="auto_repairable",
        fault="agent",
        player_safe_reason="当前候选需要机械修正",
        affected_effects=affected_effects,
    )


def _action(*, target_id: str, family: str = "action", effects=()) -> ActionAdjudication:
    return ActionAdjudication(
        request_id="request",
        source_revision="0",
        actor_id="pc_1",
        summary="调查书架",
        target=ActionTarget(kind="entity", id=target_id),
        method=ActionMethod(family=family, description="调查书架"),
        check=NoAdjudicationCheck(),
        success_effects=effects,
    )


def test_visible_target_id_correction_is_preserved() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-bookshelf")
    repaired = _action(target_id="bookshelf")
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "TARGET_ID_CORRECTED"


def test_target_id_correction_can_update_matching_effect_reference() -> None:
    _, _, projector = runtime()
    original = _action(
        target_id="missing-bookshelf",
        effects=(
            ChangeEntityStateEffect(
                entity_id="missing-bookshelf",
                key="seen",
                value=True,
            ),
        ),
    )
    repaired = _action(
        target_id="bookshelf",
        effects=(
            ChangeEntityStateEffect(entity_id="bookshelf", key="seen", value=True),
        ),
    )
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "TARGET_ID_CORRECTED"


def test_target_drift_is_rejected_even_when_validator_would_accept_it() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-bookshelf")
    repaired = _action(target_id="cabinet")
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "TARGET_CHANGED"


def test_world_target_correction_is_fail_closed_without_canonical_world_binding() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-world")
    repaired = _action(target_id="another-world")
    original = original.model_copy(
        update={"target": ActionTarget(kind="world", id="missing-world")}, deep=True
    )
    repaired = repaired.model_copy(
        update={"target": ActionTarget(kind="world", id="another-world")}, deep=True
    )
    view = asyncio.run(projector.project(player_input(utterance="检查当前环境")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="检查当前环境"),
        plan_goal="检查当前环境",
        step=ActionPlanStep(kind="action", semantic_goal="检查当前环境"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "TARGET_CHANGED"


def _checked_action(**candidate_updates) -> ActionAdjudication:
    candidate = SkillCheckCandidate(
        candidate_id="spot-candidate",
        skill_id="spot-hidden",
        difficulty="regular",
        method_summary="调查书架",
        player_safe_reason="使用侦查能力",
    ).model_copy(update=candidate_updates)
    return _action(target_id="bookshelf").model_copy(
        update={"check": RequiredAdjudicationCheck(candidates=(candidate,))},
        deep=True,
    )


def test_unchanged_check_candidate_is_preserved() -> None:
    _, _, projector = runtime()
    original = _checked_action()
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=original.model_copy(deep=True),
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "MECHANICAL_REPAIR"


def test_changed_check_candidate_identity_is_rejected() -> None:
    _, _, projector = runtime()
    original = _checked_action()
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    changed_fields = (
        {"candidate_id": "listen-candidate"},
        {"skill_id": "listen"},
        {"player_safe_reason": "使用聆听能力"},
    )
    for candidate_updates in changed_fields:
        result = compare_repair_semantics(
            player_input=player_input(utterance="调查书架"),
            plan_goal="调查书架",
            step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
            original=original,
            repaired=_checked_action(**candidate_updates),
            validation_feedback=_feedback(),
            player_view=view,
        )

        assert result.status == "requires_clarification"
        assert result.reason_code == "CHECK_CHANGED"


def test_ambiguous_visible_target_mentions_require_clarification() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-target")
    repaired = _action(target_id="bookshelf")
    view = asyncio.run(
        projector.project(player_input(utterance="调查书架和柜子"))
    )

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架和柜子"),
        plan_goal="调查书架和柜子",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架和柜子"),
        original=original.model_copy(
            update={
                "summary": "调查书架和柜子",
                "method": ActionMethod(family="action", description="调查书架和柜子"),
            },
            deep=True,
        ),
        repaired=repaired.model_copy(
            update={
                "summary": "调查书架和柜子",
                "method": ActionMethod(family="action", description="调查书架和柜子"),
            },
            deep=True,
        ),
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "TARGET_CHANGED"


def test_method_family_change_is_rejected() -> None:
    _, _, projector = runtime()
    original = _action(target_id="bookshelf", family="dialogue")
    repaired = _action(target_id="bookshelf", family="action")
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="dialogue", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "METHOD_CHANGED"


def test_explicit_no_harm_limit_is_not_overridden_by_repair() -> None:
    _, _, projector = runtime()
    input_value = player_input(utterance="说服守卫放行，不伤害守卫")
    original = _action(target_id="butler", family="dialogue")
    repaired = _action(target_id="butler", family="combat")
    view = asyncio.run(projector.project(input_value))

    result = compare_repair_semantics(
        player_input=input_value,
        plan_goal="说服守卫放行，不伤害守卫",
        step=ActionPlanStep(kind="dialogue", semantic_goal="说服守卫放行，不伤害守卫"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "METHOD_CHANGED"


def test_only_validator_rejected_effect_can_be_removed() -> None:
    _, _, projector = runtime()
    original = _action(
        target_id="bookshelf",
        effects=(
            ChangeEntityStateEffect(entity_id="bookshelf", key="seen", value=True),
            ConsumeEntityEffect(entity_id="bookshelf"),
        ),
    )
    repaired = _action(
        target_id="bookshelf",
        effects=(ChangeEntityStateEffect(entity_id="bookshelf", key="seen", value=True),),
    )
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(
            affected_effects=(
                {"branch": "success", "effect_index": 1, "effect_type": "consume_entity"},
            )
        ),
        player_view=view,
    )

    assert result.status == "narrowed"


def test_new_irreversible_effect_requires_clarification() -> None:
    _, _, projector = runtime()
    original = _action(target_id="bookshelf")
    repaired = _action(
        target_id="bookshelf",
        effects=(EnterLocationEffect(location_id="study"),),
    )
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "NEW_OR_CHANGED_EFFECT"


def test_same_length_effect_replacement_requires_clarification() -> None:
    _, _, projector = runtime()
    original = _action(
        target_id="bookshelf",
        effects=(ChangeEntityStateEffect(entity_id="bookshelf", key="seen", value=True),),
    )
    repaired = _action(
        target_id="bookshelf",
        effects=(ConsumeEntityEffect(entity_id="bookshelf"),),
    )
    view = asyncio.run(projector.project(player_input(utterance="调查书架")))

    result = compare_repair_semantics(
        player_input=player_input(utterance="调查书架"),
        plan_goal="调查书架",
        step=ActionPlanStep(kind="action", semantic_goal="调查书架"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "NEW_OR_CHANGED_EFFECT"
