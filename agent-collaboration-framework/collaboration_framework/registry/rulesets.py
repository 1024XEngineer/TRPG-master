"""World-scoped ruleset adapters (#485 PR 1).

The generic Engine owns orchestration, transactions, events, and recovery. A
ruleset adapter owns the meanings that vary by ``world_ref``: check profiles,
check outcome handlers, and world actions. Keeping all three collections on
one adapter prevents a profile from one game system being accidentally used by
another system with the same string id.

This is a static registry shipped with the Engine. It is intentionally not a
plugin loader and does not import the Engine, persistence, or module content.
Adding an entry is a claim that the corresponding runtime capability exists;
the CoC7 adapter therefore registers only the already executable
``coc7.sanity`` profile and the executable ``coc7.apply_condition`` action.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .check_profiles import COC7_CHECK_PROFILES, CheckProfileRegistration


class RulesetRegistryError(LookupError):
    """Raised when a world or a world-owned capability is not registered."""


class RulesetActionError(ValueError):
    """A registered action rejected its parameters or current state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RulesetActionContext:
    state: Any
    actor_id: str
    actor_binding: str
    parameters: Mapping[str, Any]
    request_id: str
    operation_key: str


@dataclass(frozen=True)
class RulesetActionResult:
    state: Any
    event_type: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


RulesetAction = Any


COC7_CONDITION_IDS: frozenset[str] = frozenset(
    {
        "unconscious",
        "unconscious_until_night",
        "arrested_during_prohibition",
        "drowning",
        "full_frog_transformation",
        "happiness_vision_skip_one_turn",
        "james_withdrawal_symptoms",
        "periodic_happiness_hallucinations",
        "pond_water_craving",
        "psychological_dependency",
        "converted_staff_coordination_bonus_10",
        "garden_spike_wound",
        "giant_spider_bite",
        "injured_foot",
        "mythos_book_obsession_if_insane",
        "passage_fall",
    }
)


def _coc7_apply_condition(context: RulesetActionContext) -> RulesetActionResult:
    if context.actor_binding != "actor":
        raise RulesetActionError(
            "RULESET_ACTION_BINDING_UNSUPPORTED",
            "coc7.apply_condition 目前只支持 actor binding",
        )
    condition_id = context.parameters.get("condition")
    if not isinstance(condition_id, str) or not condition_id.strip():
        raise RulesetActionError(
            "RULESET_ACTION_INVALID_PARAMETERS",
            "coc7.apply_condition 必须提供非空 condition",
        )
    if condition_id not in COC7_CONDITION_IDS:
        raise RulesetActionError(
            "RULESET_CONDITION_UNKNOWN",
            f"未注册的 CoC7 condition: {condition_id}",
        )
    reason = context.parameters.get("reason", "ruleset_action")
    if not isinstance(reason, str) or not reason.strip():
        raise RulesetActionError(
            "RULESET_ACTION_INVALID_PARAMETERS",
            "condition reason 必须是非空字符串",
        )
    expiry_value = context.parameters.get("expiry", context.parameters.get("lifecycle_ref"))
    expiry = None
    if expiry_value is not None:
        if not isinstance(expiry_value, dict):
            raise RulesetActionError(
                "RULESET_ACTION_INVALID_PARAMETERS",
                "expiry 必须是结构化对象",
            )
        try:
            kind = expiry_value.get("kind")
            reference_id = expiry_value.get("reference_id")
            if kind not in {"time_point", "time_task"} or not isinstance(
                reference_id, str
            ) or not reference_id.strip():
                raise ValueError("invalid expiry")
            expiry = {"kind": kind, "reference_id": reference_id}
        except ValueError as exc:
            raise RulesetActionError(
                "RULESET_ACTION_INVALID_PARAMETERS",
                "expiry 必须包含合法的 kind/reference_id",
            ) from exc
    actor = context.state.actors.get(context.actor_id)
    if actor is None:
        raise RulesetActionError("RULESET_ACTION_TARGET_UNKNOWN", "规则动作目标角色不存在")
    records = list(actor.condition_states)
    existing = next(
        (item for item in records if item.application_key == context.operation_key),
        None,
    )
    if existing is not None or any(
        item.condition_id == condition_id and item.status == "active" for item in records
    ):
        return RulesetActionResult(state=context.state)
    record = {
        "condition_id": condition_id,
        "source": "coc7.apply_condition",
        "application_reason": reason,
        "application_key": context.operation_key,
        "status": "active",
        "expiry": expiry,
    }
    actor_payload = actor.model_dump(mode="python")
    actor_payload["condition_states"] = [*records, record]
    actor_payload["conditions"] = list(
        dict.fromkeys(
            [
                *(item.condition_id for item in records if item.status == "active"),
                condition_id,
            ]
        )
    )
    updated_actor = actor.__class__.model_validate(actor_payload)
    actors = dict(context.state.actors)
    actors[context.actor_id] = updated_actor
    updated_state = context.state.model_copy(update={"actors": actors}, deep=True)
    return RulesetActionResult(
        state=updated_state,
        event_type="actor.condition_applied",
        payload={
            "actor_id": context.actor_id,
            "condition_id": condition_id,
            "source": "coc7.apply_condition",
            "application_reason": reason,
            "application_key": context.operation_key,
            "expiry": expiry,
        },
    )


@dataclass(frozen=True)
class RulesetAdapter:
    """The runtime capability catalogue owned by one ``world_ref``.

    Handler and executor values are intentionally typed as ``Any`` in this
    boundary. Their concrete call contracts belong to the Engine and will be
    narrowed when the corresponding capabilities are implemented. The
    registry still gives those capabilities a stable, world-scoped home now.
    """

    world_ref: str
    check_profiles: Mapping[str, CheckProfileRegistration] = field(
        default_factory=dict
    )
    check_outcome_handlers: Mapping[str, Any] = field(default_factory=dict)
    world_actions: Mapping[str, RulesetAction] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.world_ref.strip():
            raise ValueError("ruleset adapter world_ref cannot be blank")
        for field_name in (
            "check_profiles",
            "check_outcome_handlers",
            "world_actions",
        ):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, MappingProxyType(dict(value)))

    def check_profile_for(self, profile_id: str) -> CheckProfileRegistration | None:
        return self.check_profiles.get(profile_id)

    def check_outcome_handler_for(self, profile_id: str) -> Any | None:
        return self.check_outcome_handlers.get(profile_id)

    def world_action_for(self, action_id: str) -> Any | None:
        return self.world_actions.get(action_id)


class RulesetAdapterRegistry:
    """Immutable lookup table for the adapters bundled with the Engine."""

    def __init__(self, adapters: Iterable[RulesetAdapter]) -> None:
        by_world: dict[str, RulesetAdapter] = {}
        for adapter in adapters:
            if adapter.world_ref in by_world:
                raise ValueError(
                    f"duplicate ruleset adapter for world_ref={adapter.world_ref}"
                )
            by_world[adapter.world_ref] = adapter
        self._adapters: Mapping[str, RulesetAdapter] = MappingProxyType(by_world)

    @property
    def world_refs(self) -> frozenset[str]:
        return frozenset(self._adapters)

    @property
    def adapters(self) -> Mapping[str, RulesetAdapter]:
        return self._adapters

    def is_registered(self, world_ref: str) -> bool:
        return world_ref in self._adapters

    def adapter_for(self, world_ref: str) -> RulesetAdapter | None:
        return self._adapters.get(world_ref)

    def __contains__(self, world_ref: str) -> bool:
        return self.is_registered(world_ref)

    def __getitem__(self, world_ref: str) -> RulesetAdapter:
        return self.require_adapter(world_ref)

    def require_adapter(self, world_ref: str) -> RulesetAdapter:
        adapter = self.adapter_for(world_ref)
        if adapter is None:
            raise RulesetRegistryError(
                f"no ruleset adapter is registered for world_ref={world_ref!r}"
            )
        return adapter

    def check_profile_for(
        self,
        world_ref: str,
        profile_id: str,
    ) -> CheckProfileRegistration | None:
        adapter = self.adapter_for(world_ref)
        return adapter.check_profile_for(profile_id) if adapter is not None else None

    def require_check_profile(
        self,
        world_ref: str,
        profile_id: str,
    ) -> CheckProfileRegistration:
        profile = self.check_profile_for(world_ref, profile_id)
        if profile is None:
            raise RulesetRegistryError(
                f"no check profile {profile_id!r} is registered for "
                f"world_ref={world_ref!r}"
            )
        return profile

    def check_outcome_handler_for(self, world_ref: str, profile_id: str) -> Any | None:
        adapter = self.adapter_for(world_ref)
        return (
            adapter.check_outcome_handler_for(profile_id)
            if adapter is not None
            else None
        )

    def require_check_outcome_handler(self, world_ref: str, profile_id: str) -> Any:
        handler = self.check_outcome_handler_for(world_ref, profile_id)
        if handler is None:
            raise RulesetRegistryError(
                f"no check outcome handler for profile {profile_id!r} is registered "
                f"for world_ref={world_ref!r}"
            )
        return handler

    def world_action_for(self, world_ref: str, action_id: str) -> Any | None:
        adapter = self.adapter_for(world_ref)
        return adapter.world_action_for(action_id) if adapter is not None else None

    def require_world_action(self, world_ref: str, action_id: str) -> Any:
        action = self.world_action_for(world_ref, action_id)
        if action is None:
            raise RulesetRegistryError(
                f"no world action {action_id!r} is registered for "
                f"world_ref={world_ref!r}"
            )
        return action


COC7_ADAPTER = RulesetAdapter(
    world_ref="coc-7e",
    check_profiles=COC7_CHECK_PROFILES,
    world_actions={"coc7.apply_condition": _coc7_apply_condition},
)

DEFAULT_RULESET_REGISTRY = RulesetAdapterRegistry((COC7_ADAPTER,))

# Short alias for callers that want the bundled registry object.
RULESET_ADAPTERS = DEFAULT_RULESET_REGISTRY


def is_registered(world_ref: str) -> bool:
    return DEFAULT_RULESET_REGISTRY.is_registered(world_ref)


def adapter_for(world_ref: str) -> RulesetAdapter | None:
    return DEFAULT_RULESET_REGISTRY.adapter_for(world_ref)


def require_adapter(world_ref: str) -> RulesetAdapter:
    return DEFAULT_RULESET_REGISTRY.require_adapter(world_ref)


def check_profile_for(
    world_ref: str,
    profile_id: str,
) -> CheckProfileRegistration | None:
    return DEFAULT_RULESET_REGISTRY.check_profile_for(world_ref, profile_id)


def check_outcome_handler_for(world_ref: str, profile_id: str) -> Any | None:
    return DEFAULT_RULESET_REGISTRY.check_outcome_handler_for(world_ref, profile_id)


def require_check_outcome_handler(world_ref: str, profile_id: str) -> Any:
    return DEFAULT_RULESET_REGISTRY.require_check_outcome_handler(world_ref, profile_id)


def world_action_for(world_ref: str, action_id: str) -> Any | None:
    return DEFAULT_RULESET_REGISTRY.world_action_for(world_ref, action_id)


def require_world_action(world_ref: str, action_id: str) -> Any:
    return DEFAULT_RULESET_REGISTRY.require_world_action(world_ref, action_id)


__all__ = [
    "COC7_ADAPTER",
    "COC7_CONDITION_IDS",
    "DEFAULT_RULESET_REGISTRY",
    "RULESET_ADAPTERS",
    "RulesetActionContext",
    "RulesetActionError",
    "RulesetActionResult",
    "RulesetAdapter",
    "RulesetAdapterRegistry",
    "RulesetRegistryError",
    "adapter_for",
    "check_outcome_handler_for",
    "check_profile_for",
    "is_registered",
    "require_adapter",
    "require_check_outcome_handler",
    "require_world_action",
    "world_action_for",
]
