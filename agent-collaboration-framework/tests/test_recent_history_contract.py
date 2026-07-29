import json

import pytest
from pydantic import ValidationError

from collaboration_framework.contracts import (
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
)
from collaboration_framework.host.schemas import (
    HostAgentContext,
    RecentSafeResult,
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
)
from collaboration_framework.schema_export import rendered_schemas


def scope() -> tuple[PlayerInput, PlayerView]:
    player_input = PlayerInput(
        room_id="room",
        player_id="viewer",
        actor_id="viewer_actor",
        client_action_id="current",
        utterance="是的",
    )
    player_view = PlayerView(
        room_id="room",
        player_id="viewer",
        actor_id="viewer_actor",
        background="玩家安全背景",
        scene_id="study",
        phase="playing",
        revision="7",
        self_actor=SelfActorView(id="viewer_actor", name="调查员"),
        scene=SceneView(id="study", name="书房", description="安静的书房"),
    )
    return player_input, player_view


def own_turn() -> RecentTurn:
    return RecentTurn(
        correlation_id="prior",
        source_player_id="viewer",
        source_actor_id="viewer_actor",
        scene_id="study",
        source_view_revision="5",
        committed_view_revision="6",
        participants=("viewer_actor", "thomas"),
        player_utterance=VisibleHistoryText(
            text="五本书被叔叔一起带走",
            visibility="public",
        ),
        accepted_intent_summary="告诉托马斯五本书被叔叔带走",
        player_safe_result=RecentSafeResult(
            resolution="direct",
            outcome="success",
        ),
        published_narration=VisibleHistoryText(
            text="托马斯停顿片刻，问你是否确定。",
            visibility="player_scoped",
        ),
        evidence_refs=("transport_event:event-1", "action_execution:prior"),
    )


def test_recent_history_scope_and_host_contract_are_required() -> None:
    player_input, player_view = scope()
    recent_history = RecentTurnContext(
        room_id="room",
        viewer_player_id="viewer",
        as_of_revision="7",
        turns=(own_turn(),),
    )
    context = HostAgentContext(
        player_input=player_input,
        player_view=player_view,
        recent_history=recent_history,
    )

    assert context.recent_history.turns[0].accepted_intent_summary
    assert "recent_history" in HostAgentContext.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        HostAgentContext(player_input=player_input, player_view=player_view)
    with pytest.raises(ValidationError, match="as_of_revision"):
        HostAgentContext(
            player_input=player_input,
            player_view=player_view,
            recent_history=recent_history.model_copy(update={"as_of_revision": "6"}),
        )


def test_recent_history_rejects_cross_player_private_or_authoritative_fields() -> None:
    other_private = own_turn().model_copy(
        update={
            "source_player_id": "other",
            "source_actor_id": "other_actor",
        }
    )
    with pytest.raises(ValidationError, match="player_scoped"):
        RecentTurnContext(
            room_id="room",
            viewer_player_id="viewer",
            as_of_revision="7",
            turns=(other_private,),
        )

    other_public_with_result = other_private.model_copy(
        update={
            "published_narration": VisibleHistoryText(
                text="公共叙事",
                visibility="public",
            ),
            "accepted_intent_summary": "不应公开",
            "player_safe_result": RecentSafeResult(
                resolution="direct",
                outcome="success",
            ),
        }
    )
    with pytest.raises(ValidationError, match="Intent"):
        RecentTurnContext(
            room_id="room",
            viewer_player_id="viewer",
            as_of_revision="7",
            turns=(other_public_with_result,),
        )


def test_recent_history_schema_and_serialization_exclude_internal_engine_fields() -> (
    None
):
    schema = json.loads(rendered_schemas()["recent-turn-context.schema.json"])
    encoded = json.dumps(schema, ensure_ascii=False)

    assert schema["title"] == "RecentTurnContext"
    assert "confirmed_facts" not in encoded
    assert "state_changes" not in encoded
    assert '"events"' not in encoded
    assert "event_refs" not in encoded
