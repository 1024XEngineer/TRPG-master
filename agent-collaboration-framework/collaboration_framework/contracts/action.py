"""Stable host-to-engine action contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from .common import ContractModel
from .player_view import VisibleFact


class MatchedTarget(ContractModel):
    matched: Literal[True] = True
    id: str = Field(min_length=1)


class UnmatchedTarget(ContractModel):
    matched: Literal[False] = False
    raw: str = Field(min_length=1)


IntentTarget = Annotated[
    MatchedTarget | UnmatchedTarget,
    Field(discriminator="matched"),
]


class NoCheck(ContractModel):
    route: Literal["none"] = "none"


class ModuleCheck(ContractModel):
    route: Literal["module"] = "module"
    checkpoint_id: str = Field(min_length=1)
    proposed_skills: tuple[str, ...] = ()


class DefaultCheck(ContractModel):
    route: Literal["default"] = "default"
    proposed_skills: tuple[str, ...] = ()


CheckProposal = Annotated[
    NoCheck | ModuleCheck | DefaultCheck,
    Field(discriminator="route"),
]

IntentKind: TypeAlias = Literal["action", "dialogue", "unknown"]


class Intent(ContractModel):
    """Host semantic proposal; every valid instance is sent to ActionExecutor."""

    kind: IntentKind
    verb: str = Field(min_length=1)
    target: IntentTarget
    check: CheckProposal
    approach: str | None = None
    summary: str = Field(min_length=1)
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Intent:
        if self.kind == "unknown":
            if not isinstance(self.target, UnmatchedTarget):
                raise ValueError("unknown Intent 必须使用 unmatched target")
            if not isinstance(self.check, NoCheck):
                raise ValueError("unknown Intent 不能提议检定")
            if not self.clarification_question:
                raise ValueError("unknown Intent 必须提供 clarification_question")
        else:
            if not isinstance(self.target, MatchedTarget):
                raise ValueError("可执行 Intent 必须使用 matched target")
            if self.clarification_question is not None:
                raise ValueError("可执行 Intent 不得携带 clarification_question")
        return self


class ActionRequest(ContractModel):
    request_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    source_view_revision: str = Field(min_length=1)
    intent: Intent


ActionResolution: TypeAlias = Literal[
    "checkpoint",
    "direct",
    "blocked",
    "unrecognized",
]
ActionOutcome: TypeAlias = Literal["success", "failure", "not_applicable"]


class ActionResult(ContractModel):
    """Player-safe result; engine state changes and Event payloads are excluded."""

    request_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    resolution: ActionResolution
    outcome: ActionOutcome
    visible_facts: tuple[VisibleFact, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    view_revision: str = Field(min_length=1)
    event_refs: tuple[str, ...] = ()
