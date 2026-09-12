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
    EnsureRuntimeEntityEffect,
    EnterLocationEffect,
    ModuleContentV3,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
    SkillCheckCandidate,
    ValidationFeedback,
    VisibleEntity,
)
from collaboration_framework.engine import (
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.application.semantic_preservation import (
    compare_repair_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
V3_FIXTURE = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
# 开局唯一可见的 Canon 实体；语义匹配要靠它的玩家可见名。
TARGET = "thomas"
TARGET_LABEL = "托马斯·金博尔"
# 开局已知但不在场的另一个可见目标，用来构造「一句话点到两个目标」。
OTHER_LABEL = "阿诺兹堡图书馆"


def player_input(
    action_id: str = "semantic-test",
    utterance: str = f"查看{TARGET_LABEL}",
) -> PlayerInput:
    return PlayerInput(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        client_action_id=action_id,
        utterance=utterance,
    )


def runtime():
    module = ModuleContentV3.model_validate_json(V3_FIXTURE.read_text(encoding="utf-8"))
    state = GameState(
        room_id="room_01",
        scene_id=module.initial_state.start_location_id,
        actors={
            "pc_1": ActorState(
                player_id="player_01",
                name="陈探员",
                source_character_id="character_v3",
                source_character_version=1,
                state={"skills": {"spot-hidden": 60}},
            )
        },
        entities={},
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
        summary=f"查看{TARGET_LABEL}",
        target=ActionTarget(kind="entity", id=target_id),
        method=ActionMethod(family=family, description=f"查看{TARGET_LABEL}"),
        check=NoAdjudicationCheck(),
        success_effects=effects,
    )


def test_visible_target_id_correction_is_preserved() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-entity")
    repaired = _action(target_id=TARGET)
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "TARGET_ID_CORRECTED"


def test_missing_object_state_can_narrow_to_generic_check() -> None:
    """只有没有角色状态能力的物体目标才可收窄为普通行动。"""

    _, _, projector = runtime()
    view = asyncio.run(projector.project(player_input(utterance="观察")))
    rope = VisibleEntity(
        id="restraint_rope",
        kind="object",
        name="细绳",
        description="捆住双手的细绳",
    )
    view = view.model_copy(
        update={
            "scene": view.scene.model_copy(
                update={"visible_entities": (*view.scene.visible_entities, rope)}
            )
        },
        deep=True,
    )
    original = ActionAdjudication(
        request_id="persistent-repair",
        source_revision="0",
        actor_id="pc_1",
        summary="使劲挣脱束缚",
        target=ActionTarget(kind="entity", id="restraint_rope"),
        method=ActionMethod(family="restrain", description="使劲挣脱束缚"),
        persistence_intent="character_state",
        check=NoAdjudicationCheck(),
    )
    repaired = original.model_copy(
        update={
            "method": ActionMethod(family="action", description="使劲挣脱束缚"),
            "persistence_intent": "none",
        },
        deep=True,
    )
    result = compare_repair_semantics(
        player_input=player_input(utterance="使劲挣脱束缚"),
        plan_goal="使劲挣脱束缚",
        step=ActionPlanStep(kind="action", semantic_goal="使劲挣脱束缚"),
        original=original,
        repaired=repaired,
        validation_feedback=ValidationFeedback(
            status="rejected",
            code="PERSISTENT_EFFECT_REQUIRED",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="当前候选需要机械修正",
            generic_fallback_allowed=True,
        ),
        player_view=view,
    )

    assert result.status == "narrowed"
    assert result.reason_code == "PERSISTENCE_INTENT_NARROWED"


def test_npc_persistent_intent_cannot_be_downgraded() -> None:
    """NPC 的角色状态行动不能借收窄路径绕过持久结果完整性。"""

    _, _, projector = runtime()
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))
    original = _action(target_id=TARGET, family="knock_out").model_copy(
        update={"persistence_intent": "character_state"},
        deep=True,
    )
    repaired = original.model_copy(
        update={
            "method": ActionMethod(family="action", description=f"查看{TARGET_LABEL}"),
            "persistence_intent": "none",
        },
        deep=True,
    )
    result = compare_repair_semantics(
        player_input=player_input(utterance=f"击晕{TARGET_LABEL}"),
        plan_goal=f"击晕{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"击晕{TARGET_LABEL}"),
        original=original,
        repaired=repaired,
        validation_feedback=ValidationFeedback(
            status="rejected",
            code="PERSISTENT_EFFECT_REQUIRED",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="当前候选需要机械修正",
            generic_fallback_allowed=False,
        ),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "PERSISTENCE_INTENT_CHANGED"


def test_target_id_correction_can_update_matching_effect_reference() -> None:
    _, _, projector = runtime()
    original = _action(
        target_id="missing-entity",
        effects=(
            ChangeEntityStateEffect(
                entity_id="missing-entity",
                key="seen",
                value=True,
            ),
        ),
    )
    repaired = _action(
        target_id=TARGET,
        effects=(
            ChangeEntityStateEffect(entity_id=TARGET, key="seen", value=True),
        ),
    )
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "preserved"
    assert result.reason_code == "TARGET_ID_CORRECTED"


def test_target_drift_is_rejected_even_when_validator_would_accept_it() -> None:
    _, _, projector = runtime()
    original = _action(target_id="missing-entity")
    repaired = _action(target_id="melodias")
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
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
        method_summary=f"查看{TARGET_LABEL}",
        player_safe_reason="使用侦查能力",
    ).model_copy(update=candidate_updates)
    return _action(target_id=TARGET).model_copy(
        update={"check": RequiredAdjudicationCheck(candidates=(candidate,))},
        deep=True,
    )


def test_unchanged_check_candidate_is_preserved() -> None:
    _, _, projector = runtime()
    original = _checked_action()
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
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
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    changed_fields = (
        {"candidate_id": "listen-candidate"},
        {"skill_id": "listen"},
        {"player_safe_reason": "使用聆听能力"},
    )
    for candidate_updates in changed_fields:
        result = compare_repair_semantics(
            player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
            plan_goal=f"查看{TARGET_LABEL}",
            step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
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
    repaired = _action(target_id=TARGET)
    view = asyncio.run(
        projector.project(player_input(utterance=f"查看{TARGET_LABEL}和{OTHER_LABEL}"))
    )

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}和{OTHER_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}和{OTHER_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}和{OTHER_LABEL}"),
        original=original.model_copy(
            update={
                "summary": f"查看{TARGET_LABEL}和{OTHER_LABEL}",
                "method": ActionMethod(family="action", description=f"查看{TARGET_LABEL}和{OTHER_LABEL}"),
            },
            deep=True,
        ),
        repaired=repaired.model_copy(
            update={
                "summary": f"查看{TARGET_LABEL}和{OTHER_LABEL}",
                "method": ActionMethod(family="action", description=f"查看{TARGET_LABEL}和{OTHER_LABEL}"),
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
    original = _action(target_id=TARGET, family="dialogue")
    repaired = _action(target_id=TARGET, family="action")
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="dialogue", semantic_goal=f"查看{TARGET_LABEL}"),
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
    original = _action(target_id=TARGET, family="dialogue")
    repaired = _action(target_id=TARGET, family="combat")
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
        target_id=TARGET,
        effects=(
            ChangeEntityStateEffect(entity_id=TARGET, key="seen", value=True),
            ConsumeEntityEffect(entity_id=TARGET),
        ),
    )
    repaired = _action(
        target_id=TARGET,
        effects=(ChangeEntityStateEffect(entity_id=TARGET, key="seen", value=True),),
    )
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
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
    original = _action(target_id=TARGET)
    repaired = _action(
        target_id=TARGET,
        effects=(EnterLocationEffect(location_id="thomas_office"),),
    )
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
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
        target_id=TARGET,
        effects=(ChangeEntityStateEffect(entity_id=TARGET, key="seen", value=True),),
    )
    repaired = _action(
        target_id=TARGET,
        effects=(ConsumeEntityEffect(entity_id=TARGET),),
    )
    view = asyncio.run(projector.project(player_input(utterance=f"查看{TARGET_LABEL}")))

    result = compare_repair_semantics(
        player_input=player_input(utterance=f"查看{TARGET_LABEL}"),
        plan_goal=f"查看{TARGET_LABEL}",
        step=ActionPlanStep(kind="action", semantic_goal=f"查看{TARGET_LABEL}"),
        original=original,
        repaired=repaired,
        validation_feedback=_feedback(),
        player_view=view,
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "NEW_OR_CHANGED_EFFECT"


def _fast_talk_check() -> RequiredAdjudicationCheck:
    return RequiredAdjudicationCheck(
        candidates=(
            SkillCheckCandidate(
                candidate_id="fast-talk",
                skill_id="fast-talk",
                difficulty="regular",
                method_summary="搭话套近乎",
                player_safe_reason="使用话术",
            ),
        )
    )


def _greeting(
    *,
    rule: RuleDecisionRef | None,
    check=None,
) -> ActionAdjudication:
    return ActionAdjudication(
        request_id="request",
        source_revision="0",
        actor_id="pc_1",
        summary="跟邻居打个招呼",
        target=ActionTarget(kind="entity", id=TARGET),
        method=ActionMethod(family="social", description="打招呼"),
        check=check or NoAdjudicationCheck(),
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
        target=ActionTarget(kind="entity", id=TARGET),
        method=ActionMethod(family="pick_up", description="拿起刚才提到的普通册子"),
        persistence_intent="inventory",
        check=NoAdjudicationCheck(),
        success_effects=(
            MoveEntityEffect(entity_id=TARGET, holder_actor_id="pc_1"),
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
        target=ActionTarget(kind="entity", id=TARGET),
        method=ActionMethod(family="pick_up", description="拿起固定陈设"),
        persistence_intent="inventory",
        check=NoAdjudicationCheck(),
        success_effects=(
            MoveEntityEffect(entity_id=TARGET, holder_actor_id="pc_1"),
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


# --------------------------------------------------------------------------- #
# #462：`RULE_REQUIRES_CHECK` 被拒之后，Agent 那一次重新生成的每条出路
#
# 被拒的那版是 `rule_decision=R` + `check=none`。修复预算只有一次
# （`ActionPlanPolicy.max_repair_attempts` 默认 1），所以下面这张表就是玩家这一
# 回合的全部可能走向。每一行都由本节的一条测试钉住：
#
# | 行 | 重新生成的版本      | 闸门判定               | 最终走向            |
# |----|--------------------|-----------------------|--------------------|
# | A  | 规则不动 + 补 check | MECHANICAL_REPAIR     | 重新提交 → 正常掷骰 |
# | B  | 丢规则 + 不掷骰     | RULE_DECISION_CHANGED | 停下问玩家          |
# | C  | 丢规则 + 改自由检定 | RULE_DECISION_CHANGED | 停下问玩家          |
# | D  | 换另一条规则        | RULE_DECISION_CHANGED | 停下问玩家          |
# | E  | 原样返回没改        | MECHANICAL_REPAIR     | 引擎再拒 → 预算耗尽 |
#
# A/E 判 `preserved`，B/C/D 判 `requires_clarification`。E 之所以也是 preserved，
# 是因为语义保持只回答「这次修复有没有换掉玩家原本要做的事」——什么都没换当然没换，
# 拦住这种空转的是引擎第二次拒绝，不是这一层。
#
# B/C/D 三行都死在 `rule_decision` 的比较上——它排在 `check` 前面，所以这三种修复
# 连 `_check_is_mechanical` 都走不到。这是有意的：`_rule_decision_dropped` 只认
# `RULE_OUT_OF_SCOPE`（那边规则本就不适用，丢掉它等于回到本来就该走的普通叙事
# 裁决），而这里 `agent_match_admits` 已经通过、规则确实适用，丢掉它等于把一个
# 掷骰门控的模组分支交给自由叙事——而 `KeeperInformationCapability.content` 已经
# 把未发现情报的全文交给了 Agent，叙事侧还没有正向闸门（#446）。
#
# 关键是「不被禁止」≠「可以自动走」：引擎没禁止 Agent 放弃规则，拦它的是这一层，
# 而且拦法是降级成「要玩家确认」而不是「拒绝」。回合不死，是停下来问。
#
# A 行与 B 行的端到端走向（plan 真的掷骰 / 真的停成 needs_clarification）另见
# tests/test_action_plan_orchestrator.py 的 #462 一节。
# --------------------------------------------------------------------------- #

_NEIGHBOURS = RuleDecisionRef(rule_id="question_neighbors", option_id="fast-talk")


def test_row_a_adding_the_required_check_is_a_mechanical_repair() -> None:
    """#462：补上分支要求的那次检定，是这条错误码下走得通的修复。

    今天任何 `check.mode` 变化都判 CHECK_CHANGED，修复会被卡死在语义保持这一关：
    模型照着提示补了 `RequiredAdjudicationCheck`，这一步照样停下来问玩家。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "preserved"
    assert result.reason_code == "MECHANICAL_REPAIR"


def test_dropping_a_superfluous_check_is_a_mechanical_repair() -> None:
    """#462 镜像面：不掷骰的分支，去掉多写的 check 同样是机械修复。"""

    result = _compare(
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        _greeting(rule=_NEIGHBOURS),
        "RULE_FORBIDS_CHECK",
    )

    assert result.status == "preserved"
    assert result.reason_code == "MECHANICAL_REPAIR"


def test_realignment_only_goes_the_direction_the_engine_named() -> None:
    """引擎说缺检定，修复却把检定去掉了——那不是对齐，是换了件事做。"""

    result = _compare(
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        _greeting(rule=_NEIGHBOURS),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "CHECK_CHANGED"


def test_check_mode_may_not_change_under_an_unrelated_rejection() -> None:
    """目标不存在跟掷不掷骰无关，这时改 check.mode 是模型在夹带。"""

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        "TARGET_UNAVAILABLE",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "CHECK_CHANGED"


def test_row_c_dropping_the_rule_for_a_free_check_asks_the_player() -> None:
    """#462 验收：这里的 `agent_match_admits` 已经通过，规则确实适用。

    与 RULE_OUT_OF_SCOPE 不同——那边规则本就不适用，降级成叙事裁决不多拿任何东西；
    这边降级会把一个掷骰门控的模组分支交给自由叙事，而 KeeperInformationCapability
    已经把未发现情报的全文交给了 Agent，叙事侧还没有正向闸门（#446）。所以
    `_rule_decision_dropped` 保持只认 RULE_OUT_OF_SCOPE，这一步落到
    RULE_DECISION_CHANGED 上：回合不死，是停下来问玩家。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(rule=None, check=_fast_talk_check()),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"


def test_row_b_dropping_the_rule_for_pure_narration_asks_the_player() -> None:
    """B 行：丢掉规则、也不掷骰，退回纯叙事——同样要问玩家。

    这是 Agent 最省力的一条出路，也是最危险的一条：规则此时此地确实适用，成功链
    上挂着掷骰门控的 `reveal_information`，而模型手里就有那条情报的全文。放行它
    等于让模型自由讲一个本该掷骰才揭晓的节拍，所以这里必须停下来问人。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(rule=None),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"


def test_row_d_swapping_to_another_rule_asks_the_player() -> None:
    """D 行：换一条规则等于让模型自己挑模组后果，那是 #226 留在服务端的决定。

    `RULE_OUT_OF_SCOPE` 下已有同形状的断言；这里钉的是新错误码下同样不放行——
    `_rule_decision_dropped` 只认「有 -> 无」，换一条连那个方向都不是。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(
            rule=RuleDecisionRef(
                rule_id="impress_caretaker", option_id="credit-rating"
            ),
            check=_fast_talk_check(),
        ),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"


def test_row_e_an_unchanged_reproposal_is_semantically_preserved() -> None:
    """E 行：原样返回在这一层是「语义没变」，不是错误。

    语义保持只回答「这次修复有没有换掉玩家原本要做的事」，没换就是 preserved。
    拦住这种空转修复的是引擎——重新提交会再次撞上 RULE_REQUIRES_CHECK，然后修复
    预算耗尽。端到端那半截见 orchestrator 的 E 行测试。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS),
        _greeting(rule=_NEIGHBOURS),
        "RULE_REQUIRES_CHECK",
    )

    assert result.status == "preserved"
    assert result.reason_code == "MECHANICAL_REPAIR"


def _luck_check() -> RequiredAdjudicationCheck:
    """按另一项能力重写的整组候选——文案也跟着换，这才是真实的修复形状。"""

    return RequiredAdjudicationCheck(
        candidates=(
            SkillCheckCandidate(
                candidate_id="luck",
                skill_id="luck",
                difficulty="regular",
                method_summary="全凭运气",
                player_safe_reason="使用幸运",
            ),
        )
    )


def test_rewriting_the_candidate_to_the_declared_skill_is_mechanical() -> None:
    """#483：引擎说该掷规则指定的能力，那么整组候选本来就得重写。

    换掉 `skill_id` 之后 `method_summary` 与 `player_safe_reason` 也得跟着换，
    否则菜单上会出现「使用话术」配着幸运的目标值。这一层只确认玩家原本要做的事没被
    换掉；掷什么由规则说了算，改成什么由引擎重新整体校验。
    """

    result = _compare(
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        _greeting(rule=_NEIGHBOURS, check=_luck_check()),
        "RULE_CHECK_SKILL_MISMATCH",
    )

    assert result.status == "preserved"
    assert result.reason_code == "MECHANICAL_REPAIR"


def test_the_candidate_may_not_be_rewritten_under_an_unrelated_rejection() -> None:
    """目标不存在跟掷哪项能力无关，这时换技能是模型在夹带。"""

    result = _compare(
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        _greeting(rule=_NEIGHBOURS, check=_luck_check()),
        "TARGET_UNAVAILABLE",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "CHECK_CHANGED"


def test_dropping_the_rule_instead_of_fixing_the_skill_asks_the_player() -> None:
    """改技能是可自动接受的修复，丢规则不是——沿用 #462 的策略，不扩展。"""

    result = _compare(
        _greeting(rule=_NEIGHBOURS, check=_fast_talk_check()),
        _greeting(rule=None, check=_luck_check()),
        "RULE_CHECK_SKILL_MISMATCH",
    )

    assert result.status == "requires_clarification"
    assert result.reason_code == "RULE_DECISION_CHANGED"
