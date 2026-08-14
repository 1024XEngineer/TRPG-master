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
    EnsureRuntimeEntityEffect,
    ModuleContent,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
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


def _greeting(*, rule: RuleDecisionRef | None) -> ActionAdjudication:
    return ActionAdjudication(
        request_id="request",
        source_revision="0",
        actor_id="pc_1",
        summary="跟邻居打个招呼",
        target=ActionTarget(kind="entity", id="bookshelf"),
        method=ActionMethod(family="social", description="打招呼"),
        check=NoAdjudicationCheck(),
        rule_decision=rule,
    )


def _compare(original: ActionAdjudication, repaired: ActionAdjudication, code: str):
    _, _, projector = runtime()
    view = asyncio.run(projector.project(player_input(utterance="跟邻居打个招呼")))
    return compare_repair_semantics(
        player_input=player_input(utterance="跟邻居打个招呼"),
        plan_goal="跟邻居打个招呼",
        step=ActionPlanStep(kind="action", semantic_goal="跟邻居打个招呼"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(code=code),
        player_view=view,
    )


def test_dropping_an_out_of_scope_rule_is_an_allowed_narrowing() -> None:
    """#313：引擎判 RULE_OUT_OF_SCOPE 之后，放弃这条规则是唯一能走通的修复。

    把 rule_decision 设回 None，这一步退化成普通叙事裁决——拿不到任何它原本拿不到
    的东西。不允许的话，第 313 号那三次「跟邻居打个招呼」即使改成 auto_repairable
    也照样死在语义保持这一关。
    """

    result = _compare(
        _greeting(rule=RuleDecisionRef(rule_id="question_neighbors", option_id="fast-talk")),
        _greeting(rule=None),
        "RULE_OUT_OF_SCOPE",
    )

    assert result.status == "narrowed"
    assert result.reason_code == "RULE_DECISION_DROPPED"


def test_swapping_to_another_rule_still_requires_player_choice() -> None:
    """只放行「有 -> 无」。换一条规则等于让模型自己挑模组后果（#226 §1）。"""

    result = _compare(
        _greeting(rule=RuleDecisionRef(rule_id="question_neighbors", option_id="fast-talk")),
        _greeting(rule=RuleDecisionRef(rule_id="impress_caretaker", option_id="credit-rating")),
        "RULE_OUT_OF_SCOPE",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"


def test_a_rule_may_not_be_dropped_for_an_unrelated_rejection() -> None:
    """目标不存在跟规则范围无关，这时丢掉规则是模型在夹带（#313）。"""

    result = _compare(
        _greeting(rule=RuleDecisionRef(rule_id="question_neighbors", option_id="fast-talk")),
        _greeting(rule=None),
        "TARGET_UNAVAILABLE",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"


def test_nonportable_pickup_can_be_repaired_to_runtime_item_creation() -> None:
    """A wrong generic-entity binding may be repaired without changing pickup intent."""

    _, _, projector = runtime()
    current_input = player_input(utterance="拿起刚才提到的普通册子")
    view = asyncio.run(projector.project(current_input))
    original = ActionAdjudication(
        request_id="request",
        source_revision="0",
        actor_id="pc_1",
        summary="拿起刚才提到的普通册子",
        target=ActionTarget(kind="entity", id="bookshelf"),
        method=ActionMethod(family="pick_up", description="拿起刚才提到的普通册子"),
        persistence_intent="inventory",
        check=NoAdjudicationCheck(),
        success_effects=(
            MoveEntityEffect(entity_id="bookshelf", holder_actor_id="pc_1"),
        ),
    )
    repaired = original.model_copy(
        update={
            "target": ActionTarget(kind="location", id=view.scene.id),
            "success_effects": (
                EnsureRuntimeEntityEffect(
                    entity_id="runtime_volume",
                    entity_kind="object",
                    name="一本普通册子",
                    location_id=view.scene.id,
                ),
                MoveEntityEffect(entity_id="runtime_volume", holder_actor_id="pc_1"),
            ),
        },
        deep=True,
    )

    result = compare_repair_semantics(
        player_input=current_input,
        plan_goal=original.summary,
        step=ActionPlanStep(kind="action", semantic_goal=original.summary),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(code="INVENTORY_TARGET_NOT_PORTABLE"),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "INVENTORY_TARGET_REANCHORED"


def test_nonportable_pickup_can_be_narrowed_to_zero_write_obstruction() -> None:
    _, _, projector = runtime()
    current_input = player_input(utterance="拿起固定陈设")
    view = asyncio.run(projector.project(current_input))
    original = ActionAdjudication(
        request_id="request",
        source_revision="0",
        actor_id="pc_1",
        summary="拿起固定陈设",
        target=ActionTarget(kind="entity", id="bookshelf"),
        method=ActionMethod(family="pick_up", description="拿起固定陈设"),
        persistence_intent="inventory",
        check=NoAdjudicationCheck(),
        success_effects=(
            MoveEntityEffect(entity_id="bookshelf", holder_actor_id="pc_1"),
        ),
    )
    repaired = original.model_copy(
        update={
            "method": ActionMethod(family="action", description="拿起固定陈设"),
            "persistence_intent": "none",
            "success_effects": (NarrativeOnlyEffect(),),
        },
        deep=True,
    )

    result = compare_repair_semantics(
        player_input=current_input,
        plan_goal=original.summary,
        step=ActionPlanStep(kind="action", semantic_goal=original.summary),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(code="INVENTORY_TARGET_NOT_PORTABLE"),
        player_view=view,
    )

    assert result.status == "narrowed"
