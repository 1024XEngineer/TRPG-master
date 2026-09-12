"""Player-safe durable cursor for composite keeper actions (#489)."""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleLoopStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    step_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
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

    schema_version: Literal[1] = 1
    cursor_version: int = Field(default=0, ge=0)
    status: Literal[
        "deciding",
        "awaiting_rule",
        "awaiting_player",
        "awaiting_feedback",
        "awaiting_clarification",
        "completed",
        "stopped",
        "failed",
    ] = "deciding"
    client_action_id: str = Field(min_length=1, max_length=200)
    player_id: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=200)
    step_index: int = Field(default=0, ge=0, le=8)
    max_steps: int = Field(default=8, ge=1, le=8)
    steps: tuple[RuleLoopStep, ...] = Field(default=(), max_length=8)
    stop_reason: str | None = Field(default=None, max_length=120)
    final_text: str | None = None
    clarification_asked: bool = False

    @model_validator(mode="after")
    def validate_step_cursor(self) -> Self:
        if self.step_index not in {len(self.steps), len(self.steps) - 1}:
            raise ValueError("复合行动游标与步骤数量不一致")
        for index, step in enumerate(self.steps):
            expected = rule_loop_id(self.client_action_id, "rule", index)
            if step.index != index or step.step_id != expected or step.request_id != expected:
                raise ValueError("复合步骤身份不属于当前行动")
            if step.feedback_correlation_id not in {
                None,
                rule_loop_id(self.client_action_id, "step", index),
            }:
                raise ValueError("复合步骤反馈不属于当前行动")
        return self

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


def rule_loop_id(client_action_id: str, kind: Literal["rule", "step"], index: int) -> str:
    """Keep derived IDs within existing engine and Event identity limits."""

    value = f"{client_action_id}:{kind}:{index}"
    # Step feedback can append an existing follow-up NPC suffix.
    if len(value) <= (180 if kind == "step" else 200):
        return value
    return f"host-{kind}-" + hashlib.sha256(value.encode()).hexdigest()


__all__ = ["RuleLoopState", "RuleLoopStep", "new_rule_loop", "rule_loop_id"]
