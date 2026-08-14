"""Fail-closed semantic checks for Validator-generated repair proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionEffect,
    ActionPlanStep,
    PlayerInput,
    PlayerView,
    ValidationFeedback,
)

SemanticPreservationStatus = Literal[
    "preserved",
    "narrowed",
    "requires_clarification",
]


@dataclass(frozen=True)
class SemanticPreservationResult:
    status: SemanticPreservationStatus
    reason_code: str
    safe_reason: str


_SAFE_REASON = "修复方案可能改变原本行动，需要玩家确认下一步"


def compare_repair_semantics(
    *,
    player_input: PlayerInput,
    plan_goal: str,
    step: ActionPlanStep,
    original: ActionAdjudication,
    repaired: ActionAdjudication,
    validation_feedback: ValidationFeedback,
    player_view: PlayerView,
) -> SemanticPreservationResult:
    """Compare only player-safe structure; uncertainty always asks the player."""

    if not _same_semantic_text(original.summary, repaired.summary):
        return _clarification("SUMMARY_CHANGED")
    if not _same_method_family(original.method.family, repaired.method.family):
        return _clarification("METHOD_CHANGED")
    if not _same_semantic_text(original.method.description, repaired.method.description):
        return _clarification("METHOD_CHANGED")
    rule_dropped = _rule_decision_dropped(original, repaired, validation_feedback)
    if not rule_dropped and original.rule_decision != repaired.rule_decision:
        return _clarification("RULE_DECISION_CHANGED")
    if not _check_is_mechanical(original, repaired):
        return _clarification("CHECK_CHANGED")
    constraint_result = _check_explicit_constraints(
        player_input,
        plan_goal,
        step,
        repaired,
    )
    if constraint_result is not None:
        return constraint_result

    target_result = _compare_target(
        player_input=player_input,
        plan_goal=plan_goal,
        step=step,
        original=original,
        repaired=repaired,
        validation_feedback=validation_feedback,
        player_view=player_view,
    )
    if target_result.status == "requires_clarification":
        return target_result

    old_target_id = original.target.id
    new_target_id = repaired.target.id
    success = _compare_effect_branch(
        "success",
        original.success_effects,
        repaired.success_effects,
        validation_feedback,
        old_target_id=old_target_id,
        new_target_id=new_target_id,
    )
    if success.status == "requires_clarification":
        return success
    failure = _compare_effect_branch(
        "failure",
        original.failure_effects,
        repaired.failure_effects,
        validation_feedback,
        old_target_id=old_target_id,
        new_target_id=new_target_id,
    )
    if failure.status == "requires_clarification":
        return failure

    if rule_dropped:
        return SemanticPreservationResult(
            status="narrowed",
            reason_code="RULE_DECISION_DROPPED",
            safe_reason="已放弃不适用于本次行动的模组规则选项",
        )
    if "narrowed" in {success.status, failure.status}:
        return SemanticPreservationResult(
            status="narrowed",
            reason_code="INVALID_EFFECT_REMOVED",
            safe_reason="已移除校验器明确拒绝的无效效果",
        )
    if target_result.reason_code != "UNCHANGED":
        return target_result
    return SemanticPreservationResult(
        status="preserved",
        reason_code="MECHANICAL_REPAIR",
        safe_reason="修复仅调整了行动的机械参数",
    )


def _rule_decision_dropped(
    original: ActionAdjudication,
    repaired: ActionAdjudication,
    feedback: ValidationFeedback,
) -> bool:
    """放弃一个引擎刚判定为超范围的规则选项，是允许的收窄修复（#313）。

    只认「有 -> 无」这一个方向。换成另一条规则等于让模型自己挑模组后果，那是
    #226 明令留在服务端的决定；而放弃之后这一步退化成普通叙事裁决，拿不到任何
    它原本拿不到的东西，引擎照样会把修复后的裁决整个重新校验一遍。
    """

    return (
        feedback.code == "RULE_OUT_OF_SCOPE"
        and original.rule_decision is not None
        and repaired.rule_decision is None
    )


def _compare_target(
    *,
    player_input: PlayerInput,
    plan_goal: str,
    step: ActionPlanStep,
    original: ActionAdjudication,
    repaired: ActionAdjudication,
    validation_feedback: ValidationFeedback,
    player_view: PlayerView,
) -> SemanticPreservationResult:
    before = original.target
    after = repaired.target
    if before == after:
        return SemanticPreservationResult("preserved", "UNCHANGED", "目标未改变")

    if before.id == after.id:
        expected_kind = _safe_target_kind(after.id, player_view)
        if expected_kind == after.kind:
            return SemanticPreservationResult(
                "preserved",
                "TARGET_KIND_NORMALIZED",
                "目标类型已按玩家可见对象归一",
            )
        return _clarification("TARGET_KIND_CHANGED")

    if (
        validation_feedback.code == "INVENTORY_TARGET_NOT_PORTABLE"
        and before.kind == "entity"
        and after.kind == "location"
        and after.id == player_view.scene.id
        and original.persistence_intent == "inventory"
        and any(
            effect.type == "move_entity"
            and getattr(effect, "holder_actor_id", None) is not None
            for effect in original.success_effects
        )
        and not any(
            item.id == before.id
            for item in (*player_view.scene.loose_items, *player_view.inventory)
        )
    ):
        # The rejected id was not a portable item.  Re-anchoring the same
        # pickup intent to the current scene is the protocol-required shape
        # for either a zero-write obstruction or a guarded Runtime item
        # creation; the effect comparison below still restricts both forms.
        return SemanticPreservationResult(
            "preserved",
            "INVENTORY_TARGET_REANCHORED",
            "不可携带目标已按当前场景重新裁决",
        )

    if validation_feedback.code != "TARGET_UNAVAILABLE" or before.kind != after.kind:
        return _clarification("TARGET_CHANGED")

    semantic_sources = (
        player_input.utterance,
        plan_goal,
        step.semantic_goal,
        original.summary,
        original.method.description,
    )
    referenced_target_ids = _referenced_safe_target_ids(
        semantic_sources,
        player_view,
    )
    if referenced_target_ids == {after.id}:
        return SemanticPreservationResult(
            "preserved",
            "TARGET_ID_CORRECTED",
            "目标 ID 已按玩家可见语义修正",
        )
    return _clarification("TARGET_CHANGED")


def _check_is_mechanical(
    original: ActionAdjudication,
    repaired: ActionAdjudication,
) -> bool:
    before = original.check
    after = repaired.check
    if before.mode != after.mode or len(before.candidates) != len(after.candidates):
        return False
    for old, new in zip(before.candidates, after.candidates, strict=True):
        if (
            old.candidate_id != new.candidate_id
            or old.skill_id != new.skill_id
            or old.difficulty != new.difficulty
        ):
            return False
        if not _same_semantic_text(old.method_summary, new.method_summary):
            return False
        if not _same_semantic_text(old.player_safe_reason, new.player_safe_reason):
            return False
    return True


def _check_explicit_constraints(
    player_input: PlayerInput,
    plan_goal: str,
    step: ActionPlanStep,
    repaired: ActionAdjudication,
) -> SemanticPreservationResult | None:
    text = _normalize_text(" ".join((player_input.utterance, plan_goal, step.semantic_goal)))
    family = _normalize_text(repaired.method.family)
    effects = {effect.type for effect in (*repaired.success_effects, *repaired.failure_effects)}
    if ("不伤害" in text or "不要伤害" in text) and family in {"combat", "attack", "threaten"}:
        return _clarification("PLAYER_LIMIT_VIOLATED")
    if ("只观察" in text or "只调查" in text) and family in {"combat", "theft", "steal"}:
        return _clarification("PLAYER_LIMIT_VIOLATED")
    if "不消耗" in text and "consume_entity" in effects:
        return _clarification("PLAYER_LIMIT_VIOLATED")
    if "不被发现" in text and family in {"combat", "opencombat", "public"}:
        return _clarification("PLAYER_LIMIT_VIOLATED")
    return None


def _same_method_family(original: str, repaired: str) -> bool:
    # `action` is the ActionPlan kind used for open-ended families such as
    # observe/search. The description and summary checks above still reject a
    # real change of method (for example observe -> attack).
    stable_families = {"travel", "dialogue", "wait", "rest"}
    return original == repaired or (
        repaired == "action" and original not in stable_families
    )


def _compare_effect_branch(
    branch: Literal["success", "failure"],
    original: tuple[ActionEffect, ...],
    repaired: tuple[ActionEffect, ...],
    feedback: ValidationFeedback,
    *,
    old_target_id: str,
    new_target_id: str,
) -> SemanticPreservationResult:
    before = [_effect_payload(effect, old_target_id, new_target_id) for effect in original]
    after = [_effect_payload(effect, new_target_id, new_target_id) for effect in repaired]
    if before == after:
        return SemanticPreservationResult("preserved", "UNCHANGED", "效果未改变")
    portability_repair = _inventory_portability_repair_status(
        branch,
        before,
        after,
        feedback,
    )
    if portability_repair is not None:
        return portability_repair
    if len(after) >= len(before):
        if before == after[: len(before)] and all(
            payload == {"type": "narrative_only"} for payload in after[len(before) :]
        ):
            return SemanticPreservationResult(
                "preserved",
                "NARRATIVE_DETAIL_ADDED",
                "补齐了不产生领域副作用的叙事细节",
            )
        if _is_persistent_effect_repair(branch, before, after, feedback):
            return SemanticPreservationResult(
                "preserved",
                "PERSISTENT_EFFECT_REPAIRED",
                "已按校验反馈补齐持久结果效果",
            )
        return _clarification("NEW_OR_CHANGED_EFFECT")

    if _is_persistent_effect_repair(branch, before, after, feedback):
        return SemanticPreservationResult(
            "preserved",
            "PERSISTENT_EFFECT_REPAIRED",
            "已按校验反馈修正持久结果效果",
        )

    rejected_indices = {
        item.effect_index for item in feedback.affected_effects if item.branch == branch
    }
    kept_index = 0
    removed: set[int] = set()
    for original_index, payload in enumerate(before):
        if kept_index < len(after) and payload == after[kept_index]:
            kept_index += 1
        else:
            removed.add(original_index)
    if kept_index != len(after) or not removed or not removed <= rejected_indices:
        return _clarification("NEW_OR_CHANGED_EFFECT")
    return SemanticPreservationResult(
        "narrowed",
        "INVALID_EFFECT_REMOVED",
        "已移除校验器明确拒绝的无效效果",
    )


def _is_persistent_effect_repair(
    branch: Literal["success", "failure"],
    before: list[object],
    after: list[object],
    feedback: ValidationFeedback,
) -> bool:
    """仅允许 Validator 指定的持久结果在成功分支替换一个领域效果。

    此处只判定修复是否保持玩家原意；修复后的目标、状态键和值仍会由 Engine
    再次执行确定性校验，因此不匹配的效果不会被提交。
    """

    if branch != "success" or feedback.code not in {
        "PERSISTENT_EFFECT_REQUIRED",
        "PERSISTENT_EFFECT_MISMATCH",
    }:
        return False
    meaningful_before = [item for item in before if item != {"type": "narrative_only"}]
    meaningful_after = [item for item in after if item != {"type": "narrative_only"}]
    return len(meaningful_before) <= 1 and len(meaningful_after) == 1


def _inventory_portability_repair_status(
    branch: Literal["success", "failure"],
    before: list[object],
    after: list[object],
    feedback: ValidationFeedback,
) -> SemanticPreservationResult | None:
    """Allow only the two safe repairs for a nonportable inventory target."""

    if branch != "success" or feedback.code != "INVENTORY_TARGET_NOT_PORTABLE":
        return None
    meaningful_before = [item for item in before if item != {"type": "narrative_only"}]
    invalid_moves = [
        item
        for item in meaningful_before
        if isinstance(item, dict)
        and item.get("type") == "move_entity"
        and isinstance(item.get("holder_actor_id"), str)
    ]
    if len(meaningful_before) != 1 or len(invalid_moves) != 1:
        return None
    meaningful_after = [item for item in after if item != {"type": "narrative_only"}]
    if not meaningful_after:
        return SemanticPreservationResult(
            "narrowed",
            "NONPORTABLE_PICKUP_BLOCKED",
            "不可携带对象已改为零写入叙事结果",
        )
    if len(meaningful_after) != 2:
        return None
    created, moved = meaningful_after
    if not isinstance(created, dict) or not isinstance(moved, dict):
        return None
    if (
        created.get("type") != "ensure_runtime_entity"
        or created.get("entity_kind") != "object"
        or moved.get("type") != "move_entity"
        or moved.get("entity_id") != created.get("entity_id")
        or moved.get("holder_actor_id") != invalid_moves[0].get("holder_actor_id")
    ):
        return None
    return SemanticPreservationResult(
        "preserved",
        "RUNTIME_ITEM_PICKUP_REPAIRED",
        "普通场景物品已改为先创建再取得",
    )


def _effect_payload(effect: ActionEffect, source_id: str, replacement_id: str) -> object:
    payload = effect.model_dump(mode="json")
    if source_id == replacement_id:
        return payload
    return _replace_value(payload, source_id, replacement_id)


def _replace_value(value: object, source: str, replacement: str) -> object:
    if isinstance(value, dict):
        return {key: _replace_value(item, source, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_value(item, source, replacement) for item in value]
    if value == source:
        return replacement
    return value


def _safe_target_kind(target_id: str, view: PlayerView) -> str | None:
    if target_id == view.scene.id or any(item.id == target_id for item in view.known_locations):
        return "location"
    if any(item.id == target_id for item in view.scene.visible_entities):
        entity = next(item for item in view.scene.visible_entities if item.id == target_id)
        return "location" if entity.kind == "location" else "entity"
    if target_id == view.actor_id or any(
        item.id == target_id for item in view.scene.visible_actors
    ):
        return "actor"
    if any(item.id == target_id for item in view.known_information):
        return "information"
    return None


def _safe_target_labels(target_id: str, view: PlayerView) -> tuple[str, ...]:
    if target_id == view.scene.id:
        return (view.scene.name,)
    for item in view.scene.visible_entities:
        if item.id == target_id:
            return (item.name, *item.aliases)
    for item in view.scene.visible_actors:
        if item.id == target_id:
            return (item.name,)
    for item in view.known_locations:
        if item.id == target_id:
            return (item.name,)
    for item in view.known_information:
        if item.id == target_id:
            return (item.title,)
    return ()


def _referenced_safe_target_ids(
    sources: tuple[str, ...],
    view: PlayerView,
) -> set[str]:
    target_ids = {
        view.scene.id,
        *(item.id for item in view.scene.visible_entities),
        *(item.id for item in view.scene.visible_actors),
        *(item.id for item in view.known_locations),
        *(item.id for item in view.known_information),
    }
    return {
        target_id
        for target_id in target_ids
        if any(
            _contains_semantic_label(source, label)
            for source in sources
            for label in _safe_target_labels(target_id, view)
        )
    }


def _same_semantic_text(left: str, right: str) -> bool:
    return _normalize_text(left) == _normalize_text(right)


def _contains_semantic_label(text: str, label: str) -> bool:
    normalized_label = _normalize_text(label)
    return bool(normalized_label) and normalized_label in _normalize_text(text)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE).casefold()


def _clarification(reason_code: str) -> SemanticPreservationResult:
    return SemanticPreservationResult(
        status="requires_clarification",
        reason_code=reason_code,
        safe_reason=_SAFE_REASON,
    )
