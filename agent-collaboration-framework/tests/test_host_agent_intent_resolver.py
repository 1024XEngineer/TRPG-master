from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from collaboration_framework.contracts import (
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleEntity,
)
from collaboration_framework.host.application import (
    HostAgentIntentResolver,
    TurnExecutionError,
)
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    HostAgentUsage,
)


def context() -> HostAgentContext:
    return HostAgentContext(
        player_input=PlayerInput(
            room_id="room",
            player_id="player",
            actor_id="actor",
            client_action_id="action",
            utterance="调查书架",
        ),
        player_view=PlayerView(
            room_id="room",
            player_id="player",
            actor_id="actor",
            scene_id="library",
            phase="playing",
            revision="4",
            self_actor=SelfActorView(id="actor", name="调查员"),
            scene=SceneView(
                id="library",
                name="图书馆",
                description="安静的图书馆。",
                visible_entities=(
                    VisibleEntity(
                        id="shelf",
                        kind="object",
                        name="书架",
                        description="一排旧书。",
                    ),
                ),
            ),
        ),
    )


def usage(reason: str = "completed") -> HostAgentUsage:
    return HostAgentUsage(
        model_rounds=1,
        tool_calls=0,
        duration_ms=1,
        termination_reason=reason,
    )


def completed(target_id: str = "shelf") -> HostAgentCompleted:
    return HostAgentCompleted(
        type="agent.completed",
        raw_output={
            "kind": "action",
            "verb": "investigate",
            "target": {"matched": True, "id": target_id},
            "check": {"route": "none"},
            "summary": "调查书架",
        },
        usage=usage(),
    )


class ScriptedPort:
    def __init__(self, events: tuple[HostAgentEvent, ...]) -> None:
        self.events = events
        self.calls = 0

    async def astream(
        self,
        host_context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]:
        assert host_context.player_view.revision == "4"
        self.calls += 1
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_resolver_forwards_safe_progress_and_parses_one_terminal() -> None:
    port = ScriptedPort(
        (
            HostAgentToolStarted(
                type="tool.started",
                call_id="private-call-id",
                tool_name="search_visible_entities",
            ),
            HostAgentToolCompleted(
                type="tool.completed",
                call_id="private-call-id",
                tool_name="search_visible_entities",
                status="success",
            ),
            completed(),
        )
    )
    observed: list[str] = []

    async def observe(event: HostAgentEvent) -> None:
        observed.append(event.type)

    intent = await HostAgentIntentResolver(port).resolve(
        context(),
        on_event=observe,
    )

    assert port.calls == 1
    assert intent.target.id == "shelf"
    assert observed == ["tool.started", "tool.completed", "agent.completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "code"),
    [
        ((), "HOST_AGENT_STREAM_INVALID"),
        ((completed(), completed()), "HOST_AGENT_STREAM_INVALID"),
        (
            (
                HostAgentFailed(
                    type="agent.failed",
                    code="HOST_AGENT_TIMEOUT",
                    retryable=True,
                    usage=usage("timeout"),
                ),
            ),
            "HOST_AGENT_TIMEOUT",
        ),
        ((completed("hidden-entity"),), "HOST_AGENT_INVALID_OUTPUT"),
    ],
)
async def test_resolver_fails_closed_for_invalid_stream_or_output(
    events: tuple[HostAgentEvent, ...],
    code: str,
) -> None:
    with pytest.raises(TurnExecutionError) as raised:
        await HostAgentIntentResolver(ScriptedPort(events)).resolve(context())
    assert raised.value.code == code
