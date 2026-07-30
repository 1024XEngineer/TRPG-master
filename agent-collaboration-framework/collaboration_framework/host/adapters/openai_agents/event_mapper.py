"""Map SDK-native stream events into safe project observations."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent

from collaboration_framework.host.schemas import (
    HostAgentToolCompleted,
    HostAgentToolStarted,
)


class SDKEventMappingError(RuntimeError):
    """An SDK event did not contain the identity required by our contract."""


@dataclass(slots=True)
class UsageObservation:
    model_rounds: int = 0
    _input_token_reports: list[int | None] = field(default_factory=list)
    _output_token_reports: list[int | None] = field(default_factory=list)

    @property
    def input_tokens(self) -> int | None:
        return _sum_complete_reports(
            self.model_rounds,
            self._input_token_reports,
        )

    @property
    def output_tokens(self) -> int | None:
        return _sum_complete_reports(
            self.model_rounds,
            self._output_token_reports,
        )

    def record(self, event: RawResponsesStreamEvent) -> None:
        if getattr(event.data, "type", "") != "response.completed":
            return

        self.model_rounds += 1
        response = getattr(event.data, "response", None)
        usage = getattr(response, "usage", None)
        self._input_token_reports.append(
            _optional_non_negative_int(usage, "input_tokens")
        )
        self._output_token_reports.append(
            _optional_non_negative_int(usage, "output_tokens")
        )


@dataclass(slots=True)
class EventObservation:
    usage: UsageObservation = field(default_factory=UsageObservation)
    pending_tools: dict[str, str] = field(default_factory=dict)
    completed_call_ids: set[str] = field(default_factory=set)
    tool_calls: int = 0

    def map_event(
        self,
        event: object,
    ) -> HostAgentToolStarted | HostAgentToolCompleted | None:
        if isinstance(event, RawResponsesStreamEvent):
            self.usage.record(event)
            return None
        if not isinstance(event, RunItemStreamEvent):
            return None
        if event.name == "tool_called":
            call_id, tool_name = _tool_call_identity(event.item.raw_item)
            if (
                call_id in self.pending_tools
                or call_id in self.completed_call_ids
            ):
                raise SDKEventMappingError("duplicate SDK tool call identity")
            self.tool_calls += 1
            self.pending_tools[call_id] = tool_name
            return HostAgentToolStarted(
                type="tool.started",
                call_id=call_id,
                tool_name=tool_name,
            )
        if event.name == "tool_output":
            call_id = _tool_output_call_id(event.item.raw_item)
            tool_name = self.pending_tools.pop(call_id, None)
            if tool_name is None:
                raise SDKEventMappingError(
                    "SDK tool output has no matching tool call"
                )
            self.completed_call_ids.add(call_id)
            return HostAgentToolCompleted(
                type="tool.completed",
                call_id=call_id,
                tool_name=tool_name,
                status=_tool_output_status(event.item.output),
            )
        return None

    def close_pending_tools(self) -> tuple[HostAgentToolCompleted, ...]:
        events = tuple(
            HostAgentToolCompleted(
                type="tool.completed",
                call_id=call_id,
                tool_name=tool_name,
                status="error",
            )
            for call_id, tool_name in self.pending_tools.items()
        )
        self.completed_call_ids.update(self.pending_tools)
        self.pending_tools.clear()
        return events


def _tool_call_identity(raw_item: object) -> tuple[str, str]:
    call_id = _read_value(raw_item, "call_id") or _read_value(raw_item, "id")
    tool_name = _read_value(raw_item, "name")
    if not isinstance(call_id, str) or not call_id:
        raise SDKEventMappingError("SDK tool call is missing call_id")
    if not isinstance(tool_name, str) or not tool_name:
        raise SDKEventMappingError("SDK tool call is missing tool name")
    return call_id, tool_name


def _tool_output_call_id(raw_item: object) -> str:
    call_id = _read_value(raw_item, "call_id")
    if not isinstance(call_id, str) or not call_id:
        raise SDKEventMappingError("SDK tool output is missing call_id")
    return call_id


def _read_value(value: object, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _tool_output_status(value: object) -> str:
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return "error"
    if isinstance(decoded, dict) and isinstance(decoded.get("error"), dict):
        return "error"
    return "success"


def _optional_non_negative_int(value: object, name: str) -> int | None:
    raw = _read_value(value, name)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def _sum_complete_reports(
    model_rounds: int,
    reports: list[int | None],
) -> int | None:
    if model_rounds == 0 or len(reports) != model_rounds:
        return None
    if any(report is None for report in reports):
        return None
    return sum(report for report in reports if report is not None)
