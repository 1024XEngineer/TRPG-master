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
``coc7.sanity`` profile in this PR. Outcome handlers and world actions remain
empty until their executors and recovery paths land in later PRs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .check_profiles import COC7_CHECK_PROFILES, CheckProfileRegistration


class RulesetRegistryError(LookupError):
    """Raised when a world or a world-owned capability is not registered."""


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
    world_actions: Mapping[str, Any] = field(default_factory=dict)

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
    "DEFAULT_RULESET_REGISTRY",
    "RULESET_ADAPTERS",
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
