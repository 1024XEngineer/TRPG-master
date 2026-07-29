from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from collaboration_framework.contracts import (
    ActorValueView,
    AvailableExitView,
    CheckpointOption,
    DefaultCheck,
    ModuleCheck,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleEntity,
)
from collaboration_framework.host.application import (
    HostAgentIntentResolver,
    IntentParser,
    TurnExecutionError,
)
from collaboration_framework.host.application.intent_parser import coerce_intent_payload
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    HostAgentUsage,
    IntentContext,
    RecentTurnContext,
)


def context() -> HostAgentContext:
    player_input = PlayerInput(
        room_id="room",
        player_id="player",
        actor_id="actor",
        client_action_id="action",
        utterance="调查书架",
    )
    player_view = PlayerView(
        room_id="room",
        player_id="player",
        actor_id="actor",
        background="玩家可见的测试背景。",
        scene_id="library",
        phase="playing",
        revision="4",
        self_actor=SelfActorView(
            id="actor",
            name="调查员",
            attributes=(ActorValueView(id="STR", name="力量", value=55),),
            skills=(ActorValueView(id="spot-hidden", name="侦查", value=60),),
        ),
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
                VisibleEntity(
                    id="caretaker",
                    kind="npc",
                    name="梅洛迪亚斯",
                    aliases=("墓地看守", "看守"),
                    description="公共墓地的看守。",
                ),
            ),
            available_exits=(
                AvailableExitView(
                    id="cemetery_exit",
                    name="公共墓地",
                    aliases=("墓地",),
                ),
            ),
        ),
    )
    return HostAgentContext(
        player_input=player_input,
        player_view=player_view,
        recent_history=RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
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
    ],
)
async def test_resolver_fails_closed_for_invalid_stream_or_output(
    events: tuple[HostAgentEvent, ...],
    code: str,
) -> None:
    with pytest.raises(TurnExecutionError) as raised:
        await HostAgentIntentResolver(ScriptedPort(events)).resolve(context())
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_resolver_recovers_invalid_intent_as_clarification() -> None:
    resolution = await HostAgentIntentResolver(
        ScriptedPort((completed("hidden-entity"),))
    ).resolve_with_metadata(context())
    intent = resolution.intent

    assert resolution.recovered is True
    assert intent.kind == "unknown"
    assert intent.target.matched is False
    assert intent.check.route == "none"
    assert intent.clarification_question


@pytest.mark.asyncio
async def test_resolver_recovers_adapter_invalid_output_failure() -> None:
    resolution = await HostAgentIntentResolver(
        ScriptedPort(
            (
                HostAgentFailed(
                    type="agent.failed",
                    code="HOST_AGENT_INVALID_OUTPUT",
                    retryable=False,
                    usage=usage("invalid_output"),
                ),
            )
        )
    ).resolve_with_metadata(context())
    intent = resolution.intent

    assert resolution.recovered is True
    assert intent.kind == "unknown"
    assert intent.clarification_question


def test_parser_normalizes_visible_names_and_skill_labels() -> None:
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "调查",
            "target": {"matched": True, "id": "书架"},
            "check": {"route": "default", "proposed_skills": ["侦察"]},
            "summary": "调查书架",
        },
        IntentContext(
            player_input=context().player_input, player_view=context().player_view
        ),
    )

    assert parsed.target.id == "shelf"
    assert isinstance(parsed.check, DefaultCheck)
    assert parsed.check.proposed_skills == ("spot-hidden",)


def test_parser_normalizes_visible_alias_and_attribute_label() -> None:
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "推开",
            "target": {"matched": True, "id": "看守"},
            "check": {"route": "default", "proposed_skills": ["力量"]},
            "summary": "用力量推开看守",
        },
        IntentContext(
            player_input=context().player_input, player_view=context().player_view
        ),
    )

    assert parsed.target.id == "caretaker"
    assert isinstance(parsed.check, DefaultCheck)
    assert parsed.check.proposed_skills == ("STR",)


def test_empty_default_check_gets_a_visible_actor_skill() -> None:
    base = context()
    payload = coerce_intent_payload(
        {
            "kind": "action",
            "verb": "调查",
            "target": {"matched": True, "id": "shelf"},
            "check": {"route": "default", "proposed_skills": []},
            "summary": "调查书架",
        },
        IntentContext(player_input=base.player_input, player_view=base.player_view),
    )

    assert payload["check"]["proposed_skills"] == ["spot-hidden"]


def test_empty_default_travel_check_normalizes_visible_exit_alias() -> None:
    base = context()
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "前往",
            "target": {"matched": True, "id": "墓地"},
            "check": {"route": "default", "proposed_skills": []},
            "summary": "前往墓地",
        },
        IntentContext(player_input=base.player_input, player_view=base.player_view),
    )

    assert parsed.target.id == "cemetery_exit"
    assert parsed.check.route == "none"


def test_parser_normalizes_checkpoint_and_skill_labels() -> None:
    base = context()
    view = base.player_view.model_copy(
        update={
            "checkpoint_options": (
                CheckpointOption(
                    id="inspect_shelf",
                    target_id="shelf",
                    action_hint="仔细检查书架",
                    skills=("spot-hidden",),
                ),
            )
        }
    )
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "侦察",
            "target": {"matched": True, "id": "书架"},
            "check": {
                "route": "module",
                "checkpoint_id": "调查书架",
                "proposed_skills": ["侦察"],
            },
            "summary": "侦察书架",
        },
        IntentContext(player_input=base.player_input, player_view=view),
    )

    assert parsed.target.id == "shelf"
    assert isinstance(parsed.check, ModuleCheck)
    assert parsed.check.checkpoint_id == "inspect_shelf"
    assert parsed.check.proposed_skills == ("spot-hidden",)
