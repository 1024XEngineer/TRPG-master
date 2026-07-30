from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from collaboration_framework.contracts import (
    ActorValueView,
    AvailableExitView,
    CheckpointOption,
    DefaultCheck,
    JsonObject,
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
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
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


def dialogue_acknowledgement() -> HostAgentCompleted:
    return HostAgentCompleted(
        type="agent.completed",
        raw_output={
            "kind": "dialogue",
            "verb": "acknowledge",
            "target": {"matched": False, "raw": "好的，谢谢"},
            "check": {"route": "none"},
            "summary": "确认并致谢",
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
async def test_resolver_accepts_targetless_dialogue_acknowledgement() -> None:
    port = ScriptedPort((dialogue_acknowledgement(),))
    intent = await HostAgentIntentResolver(port).resolve(context())

    assert intent.kind == "dialogue"
    assert intent.target.matched is False
    assert intent.target.raw == "好的，谢谢"
    assert intent.check.route == "none"
    assert intent.clarification_question is None


@pytest.mark.parametrize(
    "raw",
    (
        {
            "kind": "unknown",
            "verb": "unknown",
            "target": {
                "matched": False,
                "raw": "那我去老橡那看一下有没有什么线索",
            },
            "check": {"route": "none"},
            "summary": "那我去老橡那看一下有没有什么线索",
            "clarification_question": "你想对当前场景中的哪个人物、物品或地点做什么？",
        },
        {
            "kind": "action",
            "verb": "search",
            "target": {"matched": True, "id": "old_oak"},
            "check": {"route": "default", "proposed_skills": ["spot-hidden"]},
            "summary": "在老橡树附近寻找线索",
        },
    ),
)
def test_same_scene_narration_only_detail_becomes_safe_scene_search(
    raw: JsonObject,
) -> None:
    base = context()
    player_input = base.player_input.model_copy(
        update={"utterance": "那我去老橡那看一下有没有什么线索"}
    )
    recent_history = RecentTurnContext(
        room_id=base.player_view.room_id,
        viewer_player_id=base.player_view.player_id,
        as_of_revision=base.player_view.revision,
        turns=(
            RecentTurn(
                correlation_id="prior-turn",
                source_player_id=base.player_view.player_id,
                source_actor_id=base.player_view.actor_id,
                scene_id=base.player_view.scene_id,
                player_utterance=VisibleHistoryText(
                    text="询问道格拉斯以前常去哪里",
                    visibility="public",
                ),
                published_narration=VisibleHistoryText(
                    text="守墓人说，道格拉斯以前常坐在北边那棵老橡树下看书。",
                    visibility="public",
                ),
            ),
            RecentTurn(
                correlation_id="clarification-turn",
                source_player_id=base.player_view.player_id,
                source_actor_id=base.player_view.actor_id,
                scene_id=base.player_view.scene_id,
                player_utterance=VisibleHistoryText(
                    text="那我去老橡那看一下有没有什么线索",
                    visibility="public",
                ),
                published_narration=VisibleHistoryText(
                    text="你想对当前场景中的哪个人物、物品或地点做什么？",
                    visibility="player_scoped",
                ),
            ),
        ),
    )
    parsed = IntentParser.parse(
        raw,
        IntentContext(
            player_input=player_input,
            player_view=base.player_view,
            recent_history=recent_history,
        ),
    )

    assert parsed.kind == "action"
    assert parsed.target.id == base.player_view.scene.id
    assert parsed.check.route == "default"
    assert parsed.check.proposed_skills == ("spot-hidden",)


def test_narration_only_detail_is_not_recovered_across_scene_boundary() -> None:
    base = context()
    player_input = base.player_input.model_copy(
        update={"utterance": "那我去老橡那看一下有没有什么线索"}
    )
    recent_history = RecentTurnContext(
        room_id=base.player_view.room_id,
        viewer_player_id=base.player_view.player_id,
        as_of_revision=base.player_view.revision,
        turns=(
            RecentTurn(
                correlation_id="prior-visit",
                source_player_id=base.player_view.player_id,
                source_actor_id=base.player_view.actor_id,
                scene_id=base.player_view.scene_id,
                player_utterance=VisibleHistoryText(
                    text="询问道格拉斯以前常去哪里",
                    visibility="public",
                ),
                published_narration=VisibleHistoryText(
                    text="守墓人说，道格拉斯以前常坐在北边那棵老橡树下看书。",
                    visibility="public",
                ),
            ),
            RecentTurn(
                correlation_id="different-scene",
                source_player_id=base.player_view.player_id,
                source_actor_id=base.player_view.actor_id,
                scene_id="cemetery",
                player_utterance=VisibleHistoryText(
                    text="去墓园转了一圈又回来",
                    visibility="public",
                ),
                published_narration=VisibleHistoryText(
                    text="你重新回到了图书馆。",
                    visibility="public",
                ),
            ),
        ),
    )
    raw = {
        "kind": "action",
        "verb": "search",
        "target": {"matched": True, "id": "old_oak"},
        "check": {"route": "default", "proposed_skills": ["spot-hidden"]},
        "summary": "在老橡树附近寻找线索",
    }

    coerced = coerce_intent_payload(
        raw,
        IntentContext(
            player_input=player_input,
            player_view=base.player_view,
            recent_history=recent_history,
        ),
    )

    assert coerced == raw


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
    base = context()
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "调查",
            "target": {"matched": True, "id": "书架"},
            "check": {"route": "default", "proposed_skills": ["侦察"]},
            "summary": "调查书架",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=base.player_view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.target.id == "shelf"
    assert isinstance(parsed.check, DefaultCheck)
    assert parsed.check.proposed_skills == ("spot-hidden",)


def test_parser_normalizes_visible_alias_and_attribute_label() -> None:
    base = context()
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "推开",
            "target": {"matched": True, "id": "看守"},
            "check": {"route": "default", "proposed_skills": ["力量"]},
            "summary": "用力量推开看守",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=base.player_view,
            recent_history=base.recent_history,
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
        IntentContext(
            player_input=base.player_input,
            player_view=base.player_view,
            recent_history=base.recent_history,
        ),
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
        IntentContext(
            player_input=base.player_input,
            player_view=base.player_view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.target.id == "cemetery_exit"
    assert parsed.verb == "go"
    assert parsed.check.route == "none"


def test_enter_exit_is_canonicalized_to_go_without_dropping_explicit_check() -> None:
    base = context()
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "进入",
            "target": {"matched": True, "id": "cemetery_exit"},
            "check": {"route": "default", "proposed_skills": ["STR"]},
            "approach": "用力前进",
            "summary": "进入墓地",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=base.player_view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.target.id == "cemetery_exit"
    assert parsed.verb == "go"
    assert isinstance(parsed.check, DefaultCheck)
    assert parsed.check.proposed_skills == ("STR",)
    assert parsed.approach == "用力前进"


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
        IntentContext(
            player_input=base.player_input,
            player_view=view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.target.id == "shelf"
    assert isinstance(parsed.check, ModuleCheck)
    assert parsed.check.checkpoint_id == "inspect_shelf"
    assert parsed.check.proposed_skills == ("spot-hidden",)


def test_travel_entity_reference_is_canonicalized_to_matching_exit() -> None:
    base = context()
    view = base.player_view.model_copy(
        update={
            "scene": base.player_view.scene.model_copy(
                update={
                    "available_exits": (
                        AvailableExitView(
                            id="cemetery_exit",
                            name="公共墓地入口",
                            target_id="caretaker",
                        ),
                    )
                }
            )
        }
    )
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "靠近",
            "target": {"matched": True, "id": "caretaker"},
            "check": {"route": "none"},
            "summary": "靠近它",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.target.id == "cemetery_exit"
    assert parsed.check.route == "none"


def test_matching_checkpoint_promotes_default_check_to_module_check() -> None:
    base = context()
    view = base.player_view.model_copy(
        update={
            "checkpoint_options": (
                CheckpointOption(
                    id="move_slab",
                    target_id="shelf",
                    action_hint="move",
                    skills=("STR",),
                ),
            )
        }
    )
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "移动",
            "target": {"matched": True, "id": "shelf"},
            "check": {"route": "default", "proposed_skills": ["STR"]},
            "summary": "移动书架",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=view,
            recent_history=base.recent_history,
        ),
    )

    assert isinstance(parsed.check, ModuleCheck)
    assert parsed.check.checkpoint_id == "move_slab"
    assert parsed.verb == "move"


def test_enter_checkpoint_overrides_default_dodge_check() -> None:
    base = context()
    view = base.player_view.model_copy(
        update={
            "checkpoint_options": (
                CheckpointOption(
                    id="move_slab",
                    target_id="shelf",
                    action_hint="move",
                    skills=("STR",),
                ),
                CheckpointOption(
                    id="enter_crypt",
                    target_id="shelf",
                    action_hint="enter",
                ),
            )
        }
    )
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "穿过缝隙进入洞中",
            "target": {"matched": True, "id": "shelf"},
            "check": {"route": "default", "proposed_skills": ["spot-hidden"]},
            "summary": "穿过缝隙进入洞中",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=view,
            recent_history=base.recent_history,
        ),
    )

    assert isinstance(parsed.check, ModuleCheck)
    assert parsed.check.checkpoint_id == "enter_crypt"
    assert parsed.check.proposed_skills == ()
    assert parsed.verb == "enter"


def test_default_check_is_blocked_when_target_has_no_matching_checkpoint() -> None:
    base = context()
    view = base.player_view.model_copy(
        update={
            "checkpoint_options": (
                CheckpointOption(
                    id="enter_crypt",
                    target_id="shelf",
                    action_hint="enter",
                ),
            )
        }
    )
    parsed = IntentParser.parse(
        {
            "kind": "action",
            "verb": "调查",
            "target": {"matched": True, "id": "shelf"},
            "check": {"route": "default", "proposed_skills": ["spot-hidden"]},
            "summary": "调查书架",
        },
        IntentContext(
            player_input=base.player_input,
            player_view=view,
            recent_history=base.recent_history,
        ),
    )

    assert parsed.kind == "unknown"
    assert parsed.target.raw == "书架"
    assert parsed.check.route == "none"
    assert parsed.clarification_question == "你想如何处理书架？"
