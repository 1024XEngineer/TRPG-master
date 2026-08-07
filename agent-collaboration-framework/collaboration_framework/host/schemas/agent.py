"""Framework-independent contracts for the Host Agent intent stage."""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, JsonValue, RootModel, model_validator

from collaboration_framework.contracts import (
    ContractModel,
    KeeperCapabilityView,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.host.schemas.history import RecentTurnContext


def _validate_keeper_scope(
    capabilities: KeeperCapabilityView | None,
    player_view: PlayerView,
) -> None:
    """Keep the two views describing the same actor at the same revision.

    Pairing a Keeper capability list with a PlayerView from another revision
    would let the Agent target something that no longer exists, or miss
    something that just appeared.
    """

    if capabilities is None:
        return
    if (
        capabilities.room_id != player_view.room_id
        or capabilities.actor_id != player_view.actor_id
    ):
        raise ValueError("KeeperCapabilityView scope 与 PlayerView 不一致")
    if capabilities.revision != player_view.revision:
        raise ValueError("KeeperCapabilityView revision 与 PlayerView 不一致")

HostAgentTerminationReason: TypeAlias = Literal[
    "completed",
    "max_turns",
    "timeout",
    "invalid_output",
    "tool_budget_exceeded",
    "internal_error",
]
HostAgentFailureCode: TypeAlias = Literal[
    "HOST_AGENT_MAX_TURNS",
    "HOST_AGENT_TIMEOUT",
    "HOST_AGENT_INVALID_OUTPUT",
    "HOST_AGENT_TOOL_BUDGET_EXCEEDED",
    "HOST_AGENT_INTERNAL_ERROR",
]
HostAgentRawOutput: TypeAlias = dict[str, JsonValue]


class HostAgentContext(ContractModel):
    """Trusted player input paired with B's player-safe scoped view."""

    player_input: PlayerInput
    player_view: PlayerView
    recent_history: RecentTurnContext
    # Controlled Keeper-side capability list. Optional so offline/fake
    # compositions and older callers keep working; when absent the Agent can
    # still only name what the player-safe view exposes.
    keeper_capabilities: KeeperCapabilityView | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> HostAgentContext:
        mismatches = [
            field_name
            for field_name in ("room_id", "player_id", "actor_id")
            if getattr(self.player_input, field_name)
            != getattr(self.player_view, field_name)
        ]
        if mismatches:
            raise ValueError("HostAgentContext scope 不一致: " + ", ".join(mismatches))
        _validate_keeper_scope(self.keeper_capabilities, self.player_view)
        self.recent_history.validate_for(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        return self


class HostAgentUsage(ContractModel):
    """Provider-neutral measurements for one Host Agent invocation.

    ``None`` means the provider did not report that token metric. A reported zero
    remains ``0`` so missing data is never silently converted into measured usage.
    """

    model_rounds: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    termination_reason: HostAgentTerminationReason


class HostAgentToolStarted(ContractModel):
    type: Literal["tool.started"]
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)


class HostAgentToolCompleted(ContractModel):
    type: Literal["tool.completed"]
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: Literal["success", "error"]


class HostAgentCompleted(ContractModel):
    type: Literal["agent.completed"]
    raw_output: HostAgentRawOutput
    usage: HostAgentUsage

    @model_validator(mode="after")
    def validate_completion(self) -> HostAgentCompleted:
        if self.usage.termination_reason != "completed":
            raise ValueError(
                "agent.completed usage.termination_reason 必须为 completed"
            )
        json.dumps(self.raw_output, ensure_ascii=False, allow_nan=False)
        return self


_FAILURE_REASON_BY_CODE: dict[HostAgentFailureCode, HostAgentTerminationReason] = {
    "HOST_AGENT_MAX_TURNS": "max_turns",
    "HOST_AGENT_TIMEOUT": "timeout",
    "HOST_AGENT_INVALID_OUTPUT": "invalid_output",
    "HOST_AGENT_TOOL_BUDGET_EXCEEDED": "tool_budget_exceeded",
    "HOST_AGENT_INTERNAL_ERROR": "internal_error",
}


class HostAgentFailed(ContractModel):
    type: Literal["agent.failed"]
    code: HostAgentFailureCode
    retryable: bool
    usage: HostAgentUsage | None = None

    @model_validator(mode="after")
    def validate_failure(self) -> HostAgentFailed:
        if self.usage is None:
            return self
        expected_reason = _FAILURE_REASON_BY_CODE[self.code]
        if self.usage.termination_reason != expected_reason:
            raise ValueError("agent.failed code 与 usage.termination_reason 不一致")
        return self


HostAgentTerminalEvent: TypeAlias = HostAgentCompleted | HostAgentFailed
HostAgentEvent: TypeAlias = Annotated[
    HostAgentToolStarted
    | HostAgentToolCompleted
    | HostAgentCompleted
    | HostAgentFailed,
    Field(discriminator="type"),
]


class HostAgentEventSchema(RootModel[HostAgentEvent]):
    """Schema-export root for the discriminated ``HostAgentEvent`` union."""

    model_config = ConfigDict(title="HostAgentEvent")
