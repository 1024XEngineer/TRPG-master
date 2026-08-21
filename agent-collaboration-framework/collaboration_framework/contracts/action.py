"""Stable host-to-engine action contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, ValidationInfo, model_validator

from .common import ContractModel
from .player_view import VisibleFact

ENGINE_AUTHORED_INTENT_CONTEXT: dict[str, str] = {"intent_source": "engine"}
"""The only validation context allowed to construct an engine-initiated Intent.

`initiated_by_target` is authority-bearing: a player-sourced Intent that carried
it would let untrusted model output pick which authored rules fire. Requiring
this context makes the invariant fail closed — a call site that bypasses the Host
aligner and validates raw model output is rejected rather than silently trusted.

Its only reader used to be the v2 string-expression evaluator, which exposed the
flag as a rule variable; that evaluator was deleted with the v2 arm (#384), and
v3 rules match through registered predicates rather than scripts (#226 §1). So
nothing reads the flag today. The guard stays because the field is still on the
wire: dropping it while leaving the field settable is exactly the ordering that
turns an unread flag into an authority hole the day something starts reading it.

Engine-internal construction opts in explicitly::

    Intent.model_validate(payload, context=ENGINE_AUTHORED_INTENT_CONTEXT)
"""


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
    verb: str = Field(
        min_length=1,
        description=(
            "Rule Engine action id. For a module check, copy the trusted "
            "checkpoint action_hint exactly; never translate it."
        ),
    )
    target: IntentTarget
    check: CheckProposal
    approach: str | None = None
    declarations: tuple[str, ...] = Field(
        default=(),
        description=(
            "Exact declaration option ids selected from the current trusted "
            "module checkpoint; empty for non-module actions."
        ),
    )
    initiated_by_target: bool = Field(
        default=False,
        description=(
            "Authority-bearing Engine flag. It is always false for "
            "player-submitted Intent, and setting it true requires validating "
            "with ENGINE_AUTHORED_INTENT_CONTEXT."
        ),
    )
    summary: str = Field(
        min_length=1,
        description="Short semantic summary; it is not an authoritative game fact.",
    )
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_shape(self, info: ValidationInfo) -> Intent:
        if self.initiated_by_target:
            context = info.context if isinstance(info.context, dict) else {}
            if context.get("intent_source") != "engine":
                raise ValueError(
                    "initiated_by_target 是 Engine 授权标记，"
                    "玩家来源的 Intent 必须为 False"
                )
        if self.kind == "unknown":
            if not isinstance(self.target, UnmatchedTarget):
                raise ValueError("unknown Intent 必须使用 unmatched target")
            if not isinstance(self.check, NoCheck):
                raise ValueError("unknown Intent 不能提议检定")
            if not self.clarification_question:
                raise ValueError("unknown Intent 必须提供 clarification_question")
        elif self.kind == "dialogue" and isinstance(self.target, UnmatchedTarget):
            if not isinstance(self.check, NoCheck):
                raise ValueError("无目标 dialogue Intent 不能提议检定")
            if self.clarification_question is not None:
                raise ValueError(
                    "无目标 dialogue Intent 不得携带 clarification_question"
                )
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
    input_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Opaque SHA-256 identity of the normalized PlayerInput that created "
            "this command; used to reject request_id reuse with different input."
        ),
    )
    intent: Intent
    roll_value: int | None = Field(default=None, ge=1, le=100)


ActionResolution: TypeAlias = Literal[
    "checkpoint",
    "direct",
    "blocked",
    "unrecognized",
]
ActionOutcome: TypeAlias = Literal["success", "failure", "not_applicable"]


CheckSuccessLevel: TypeAlias = Literal[
    "critical",
    "extreme",
    "hard",
    "regular",
    "failure",
    "fumble",
]


class RuleCheckResult(ContractModel):
    """Player-safe evidence for one authoritative percentile check."""

    checkpoint_id: str | None = None
    skill_id: str = Field(min_length=1)
    target_value: int = Field(ge=0)
    roll_value: int = Field(ge=1, le=100)
    difficulty: Literal["regular", "hard", "extreme"]
    success_level: CheckSuccessLevel
    passed: bool


class ActionResult(ContractModel):
    """Player-safe result; engine state changes and Event payloads are excluded."""

    request_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    resolution: ActionResolution
    outcome: ActionOutcome
    check_result: RuleCheckResult | None = None
    visible_facts: tuple[VisibleFact, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    view_revision: str = Field(min_length=1)
    event_refs: tuple[str, ...] = ()
