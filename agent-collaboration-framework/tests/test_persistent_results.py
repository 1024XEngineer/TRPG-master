"""持久化动作族覆盖观测测试。

本文件确保开放动作族未命中策略表时只产生诊断，不改变既有裁决结果。
"""

import logging
from types import SimpleNamespace

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    NoAdjudicationCheck,
)
from collaboration_framework.engine.adjudication import _target_persistent_capability
from collaboration_framework.engine.persistent_results import (
    validate_persistent_effects,
)


def test_unknown_family_is_observable_without_changing_validation(caplog) -> None:
    adjudication = ActionAdjudication(
        request_id="unknown-family-observation",
        source_revision="revision-1",
        actor_id="actor-1",
        summary="观察周围",
        target=ActionTarget(kind="location", id="library"),
        method=ActionMethod(family="  观察  ", description="观察周围"),
        check=NoAdjudicationCheck(),
    )

    with caplog.at_level(logging.INFO):
        result = validate_persistent_effects(adjudication)

    assert result is None
    assert "persistent_family_policy_missing" in caplog.text
    record = next(item for item in caplog.records if item.message == "persistent_family_policy_missing")
    assert record.family == "观察"
    assert record.persistence_intent == "none"


def _persistent_action(*, intent: str, family: str, target: str = "target") -> ActionAdjudication:
    """构造最小自由裁决，专门验证持久意图的降级标记。"""

    return ActionAdjudication(
        request_id="persistent-test",
        source_revision="revision-1",
        actor_id="actor-1",
        summary="尝试改变目标状态",
        target=ActionTarget(kind="entity", id=target),
        method=ActionMethod(family=family, description="尝试改变目标状态"),
        persistence_intent=intent,
        check=NoAdjudicationCheck(),
    )


def test_missing_state_capability_can_fallback_to_generic_check() -> None:
    result = validate_persistent_effects(
        _persistent_action(intent="character_state", family="restrain"),
        target_kind="object",
        target_state_keys={"cut"},
    )

    assert result is not None
    assert result.code == "PERSISTENT_EFFECT_REQUIRED"
    assert result.allow_generic_fallback is True


def test_npc_character_state_still_requires_effect() -> None:
    result = validate_persistent_effects(
        _persistent_action(intent="character_state", family="knock_out"),
        target_kind="npc",
        target_state_keys={"consciousness"},
    )

    assert result is not None
    assert result.code == "PERSISTENT_EFFECT_REQUIRED"
    assert result.allow_generic_fallback is False


def test_object_state_with_matching_capability_still_requires_effect() -> None:
    result = validate_persistent_effects(
        _persistent_action(intent="object_state", family="open"),
        target_kind="object",
        target_state_keys={"open"},
    )

    assert result is not None
    assert result.code == "PERSISTENT_EFFECT_REQUIRED"
    assert result.allow_generic_fallback is False


def test_persistent_effect_mismatch_never_marks_generic_fallback() -> None:
    action = _persistent_action(intent="character_state", family="knock_out")
    action = action.model_copy(
        update={
            "success_effects": (
                ChangeEntityStateEffect(
                    entity_id="target",
                    key="posture",
                    value="prone",
                ),
            )
        },
        deep=True,
    )
    result = validate_persistent_effects(
        action,
        target_kind="npc",
        target_state_keys={"consciousness", "posture"},
    )

    assert result is not None
    assert result.code == "PERSISTENT_EFFECT_MISMATCH"
    assert result.allow_generic_fallback is False


def test_item_instance_live_state_is_included_in_capability_snapshot() -> None:
    """物品实例已写入状态后，后续缺效果裁决仍必须走持久结果闸门。"""

    runtime = SimpleNamespace(
        module_content=SimpleNamespace(
            entities=(
                SimpleNamespace(id="drawer", kind="object", state={"open": False}),
            )
        ),
        game_state=SimpleNamespace(
            item_instances={
                "drawer": SimpleNamespace(
                    definition_id="drawer",
                    state=SimpleNamespace(values={"open": True}),
                )
            },
            public_entity_state_keys={"drawer": ("open",)},
            runtime_entities={},
            actors={},
            runtime_locations={},
        ),
        canon_location_ids=set(),
        canon_information_ids=set(),
    )

    kind, state_keys = _target_persistent_capability(runtime, "drawer")

    assert kind == "object"
    assert "open" in state_keys
