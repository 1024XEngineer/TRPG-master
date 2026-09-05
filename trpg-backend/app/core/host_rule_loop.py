"""Player-safe durable cursor for composite keeper actions (#489)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuleLoopStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    step_id: str = Field(min_length=1, max_length=240)
    request_id: str = Field(min_length=1, max_length=240)
    source_revision: str = Field(min_length=1, max_length=200)
    rule_id: str = Field(min_length=1, max_length=100)
    option_id: str = Field(min_length=1, max_length=100)
    target_kind: Literal["information", "entity", "location", "actor", "world"] | None = None
    target_id: str | None = Field(default=None, max_length=200)
    adjudication_json: dict[str, object] | None = None
    status: Literal[
        "frozen",
        "waiting_for_player",
        "committed",
        "feedback_persisted",
        "stopped",
    ] = "frozen"
    execution_event_refs: tuple[str, ...] = ()
    feedback_correlation_id: str | None = None
    feedback_text: str | None = None
    stop_reason: str | None = None


class RuleLoopState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    status: Literal[
        "deciding",
        "awaiting_rule",
        "awaiting_player",
        "awaiting_feedback",
        "completed",
        "stopped",
        "failed",
    ] = "deciding"
    client_action_id: str = Field(min_length=1, max_length=200)
    player_id: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=200)
    step_index: int = Field(default=0, ge=0)
    max_steps: int = Field(default=8, ge=1, le=8)
    steps: tuple[RuleLoopStep, ...] = ()
    stop_reason: str | None = Field(default=None, max_length=120)

    def current(self) -> RuleLoopStep | None:
        return self.steps[-1] if self.steps else None

    def dump(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def new_rule_loop(*, client_action_id: str, player_id: str, actor_id: str) -> RuleLoopState:
    return RuleLoopState(
        client_action_id=client_action_id,
        player_id=player_id,
        actor_id=actor_id,
    )


__all__ = ["RuleLoopState", "RuleLoopStep", "new_rule_loop"]
