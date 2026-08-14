"""集中定义自由裁决的持久结果语义、完整性校验和玩家安全结果摘要。

本模块只处理首期已经冻结的高层状态与效果映射。它不解释自然语言，也不实现
COC7 战斗算法；模型必须通过受控的 ``method.family`` 和 ``persistence_intent``
表达意图，Engine 再以确定性规则核对实际效果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionEffect,
    ChangeEntityStateEffect,
    CommittedResult,
    ConsumeEntityEffect,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    PersistenceIntent,
)

from .models import DomainEvent


# 标准键和值是玩家可见状态的唯一白名单，任意模组私有键不会因此被公开。
CHARACTER_STATE_VALUES: dict[str, tuple[JsonValue, ...]] = {
    "consciousness": ("conscious", "unconscious", "dead"),
    "posture": ("standing", "prone"),
    "restraint": ("free", "restrained"),
    "injury": ("none", "minor", "major", "critical"),
}
OBJECT_STATE_VALUES: dict[str, tuple[JsonValue, ...]] = {
    "open": (True, False),
    "locked": (True, False),
    "broken": (True, False),
}
PUBLIC_STATE_KEYS = frozenset((*CHARACTER_STATE_VALUES, *OBJECT_STATE_VALUES))


@dataclass(frozen=True)
class PersistentEffectProblem:
    """Engine 使用的最小校验结论；具体错误模型仍由 Engine 统一构造。"""

    code: Literal["PERSISTENT_EFFECT_REQUIRED", "PERSISTENT_EFFECT_MISMATCH"]
    player_safe_reason: str


@dataclass(frozen=True)
class _FamilyPolicy:
    intent: PersistenceIntent
    state_key: str | None = None
    state_value: JsonValue | None = None
    effect_kind: Literal["state", "move", "consume", "enter"] = "state"


# 受控动作族既帮助模型稳定表达结果，也阻止明显持久动作被标成 none 绕过检查。
_FAMILY_POLICIES: dict[str, _FamilyPolicy] = {
    "knock_out": _FamilyPolicy("character_state", "consciousness", "unconscious"),
    "wake": _FamilyPolicy("character_state", "consciousness", "conscious"),
    "kill": _FamilyPolicy("character_state", "consciousness", "dead"),
    "knock_down": _FamilyPolicy("character_state", "posture", "prone"),
    "stand_up": _FamilyPolicy("character_state", "posture", "standing"),
    "restrain": _FamilyPolicy("character_state", "restraint", "restrained"),
    "release": _FamilyPolicy("character_state", "restraint", "free"),
    "injure_minor": _FamilyPolicy("character_state", "injury", "minor"),
    "injure_major": _FamilyPolicy("character_state", "injury", "major"),
    "injure_critical": _FamilyPolicy("character_state", "injury", "critical"),
    "heal": _FamilyPolicy("character_state", "injury", "none"),
    "open": _FamilyPolicy("object_state", "open", True),
    "close": _FamilyPolicy("object_state", "open", False),
    "lock": _FamilyPolicy("object_state", "locked", True),
    "unlock": _FamilyPolicy("object_state", "locked", False),
    "break": _FamilyPolicy("object_state", "broken", True),
    "repair": _FamilyPolicy("object_state", "broken", False),
    "pick_up": _FamilyPolicy("inventory", effect_kind="move"),
    "transfer": _FamilyPolicy("inventory", effect_kind="move"),
    "drop": _FamilyPolicy("inventory", effect_kind="move"),
    "consume": _FamilyPolicy("inventory", effect_kind="consume"),
    "travel": _FamilyPolicy("location", effect_kind="enter"),
}


def effective_persistence_intent(adjudication: ActionAdjudication) -> PersistenceIntent:
    """返回裁决声明的意图；受控动作族用于复核非 none 的声明。"""

    return adjudication.persistence_intent


def validate_persistent_effects(
    adjudication: ActionAdjudication,
) -> PersistentEffectProblem | None:
    """检查自由裁决成功分支是否完整表达声明的持久结果。"""

    intent = effective_persistence_intent(adjudication)
    policy = _FAMILY_POLICIES.get(adjudication.method.family.strip().lower())
    # 新模型显式写 none 不能把明显持久动作降级成普通叙事；旧存量裁决没有
    # explicit 标记，继续按兼容语义读取 none。
    if adjudication.persistence_intent_explicit and policy is not None:
        intent = policy.intent
    if intent == "none":
        return None
    meaningful = tuple(
        effect
        for effect in adjudication.success_effects
        if not isinstance(effect, NarrativeOnlyEffect)
    )
    if not meaningful:
        return PersistentEffectProblem(
            "PERSISTENT_EFFECT_REQUIRED",
            "该行动需要可提交的持久结果，请补充对应效果",
        )

    if policy is not None and policy.intent != adjudication.persistence_intent:
        return PersistentEffectProblem(
            "PERSISTENT_EFFECT_MISMATCH",
            "行动的持久结果类别与所用方式不一致，请重新裁决",
        )
    if _has_matching_effect(adjudication, meaningful, intent, policy):
        return None
    return PersistentEffectProblem(
        "PERSISTENT_EFFECT_MISMATCH",
        "持久结果的效果类型、目标或状态值与行动意图不一致",
    )


def _has_matching_effect(
    adjudication: ActionAdjudication,
    effects: tuple[ActionEffect, ...],
    intent: PersistenceIntent,
    policy: _FamilyPolicy | None,
) -> bool:
    """对首期五类意图执行目标、效果类型及状态白名单的精确匹配。"""

    target_id = adjudication.target.id
    if intent in {"character_state", "object_state"}:
        allowed = (
            CHARACTER_STATE_VALUES
            if intent == "character_state"
            else OBJECT_STATE_VALUES
        )
        for effect in effects:
            if not isinstance(effect, ChangeEntityStateEffect):
                continue
            if effect.entity_id != target_id or effect.key not in allowed:
                continue
            if effect.value not in allowed[effect.key]:
                continue
            if policy is None or (
                effect.key == policy.state_key and effect.value == policy.state_value
            ):
                return True
        return False
    if intent == "inventory":
        # 新物品在裁决提交前还不存在，因此不能作为 ActionTarget。允许原版的
        # ensure_runtime_entity -> move/consume 原子序列；实际存在性和先后顺序仍由
        # Engine._validate_effect_sequence 确定性校验。
        eligible_entity_ids = {
            target_id,
            *(
                effect.entity_id
                for effect in effects
                if isinstance(effect, EnsureRuntimeEntityEffect)
                and effect.entity_kind == "object"
            ),
        }
        family = adjudication.method.family.strip().lower()
        for effect in effects:
            if (
                isinstance(effect, MoveEntityEffect)
                and effect.entity_id in eligible_entity_ids
                and (policy is None or policy.effect_kind == "move")
            ):
                if (
                    family == "pick_up"
                    and effect.holder_actor_id != adjudication.actor_id
                ):
                    continue
                if family == "transfer" and effect.holder_actor_id is None:
                    continue
                if family == "drop" and effect.location_id is None:
                    continue
                return True
            if (
                isinstance(effect, ConsumeEntityEffect)
                and effect.entity_id in eligible_entity_ids
                and (policy is None or policy.effect_kind == "consume")
            ):
                return True
        return False
    if intent == "location":
        # 动态地点与动态物品相同：新 id 只能先由 ensure_runtime_location 引入，
        # ActionTarget 仍是已有连接锚点。不要把“主目标必须等于最终目的地”强加给
        # 这种合法的顺序效果。
        eligible_location_ids = {
            target_id,
            *(
                effect.location_id
                for effect in effects
                if isinstance(effect, EnsureRuntimeLocationEffect)
            ),
        }
        return any(
            isinstance(effect, EnterLocationEffect)
            and effect.location_id in eligible_location_ids
            and (policy is None or policy.effect_kind == "enter")
            for effect in effects
        )
    return False


def is_public_standard_state(effect: ActionEffect) -> bool:
    """判断某个状态效果是否属于首期允许公开的标准状态。"""

    if not isinstance(effect, ChangeEntityStateEffect):
        return False
    allowed = CHARACTER_STATE_VALUES.get(effect.key) or OBJECT_STATE_VALUES.get(
        effect.key
    )
    return allowed is not None and effect.value in allowed


def committed_results_from_events(
    events: tuple[DomainEvent, ...],
) -> tuple[CommittedResult, ...]:
    """只从公开、已应用的高层 DomainEvent 生成玩家安全证据摘要。"""

    results: list[CommittedResult] = []
    for event in events:
        if event.visibility != "public":
            continue
        payload = event.payload
        if event.type == "entity.state_changed":
            target_id = payload.get("entity_id")
            key = payload.get("key")
            value = payload.get("value")
            allowed = (
                CHARACTER_STATE_VALUES.get(key) or OBJECT_STATE_VALUES.get(key)
                if isinstance(key, str)
                else None
            )
            if (
                not isinstance(target_id, str)
                or allowed is None
                or value not in allowed
            ):
                continue
            assert isinstance(key, str)
            results.append(
                CommittedResult(
                    kind="character_state"
                    if key in CHARACTER_STATE_VALUES
                    else "object_state",
                    target_id=target_id,
                    state_key=key,
                    state_value=value,
                    event_ref=event.event_id,
                )
            )
        elif event.type == "entity.moved" and isinstance(payload.get("entity_id"), str):
            entity_id = payload.get("entity_id")
            assert isinstance(entity_id, str)
            results.append(
                CommittedResult(
                    kind="inventory",
                    target_id=entity_id,
                    event_ref=event.event_id,
                )
            )
        elif event.type == "entity.consumed" and isinstance(
            payload.get("entity_id"), str
        ):
            entity_id = payload.get("entity_id")
            assert isinstance(entity_id, str)
            results.append(
                CommittedResult(
                    kind="inventory",
                    target_id=entity_id,
                    event_ref=event.event_id,
                )
            )
        elif event.type == "location.entered" and isinstance(
            payload.get("location_id"), str
        ):
            location_id = payload.get("location_id")
            assert isinstance(location_id, str)
            results.append(
                CommittedResult(
                    kind="location",
                    target_id=location_id,
                    event_ref=event.event_id,
                )
            )
    return tuple(results)
