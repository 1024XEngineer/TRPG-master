from datetime import UTC, datetime, timedelta

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    Intent,
    MatchedTarget,
    NoCheck,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleFact,
)
from collaboration_framework.engine import EngineExecutionResult
from collaboration_framework.host.schemas import RecentHistoryBudget
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyRecentHistorySource
from app.models.engine import ActionExecution
from app.models.event import Event
from app.models.room import Player, Room

SECRET = "RECENT_HISTORY_SECRET_SENTINEL"


def current_scope(room_id: str, player_id: str) -> tuple[PlayerInput, PlayerView]:
    player_input = PlayerInput(
        room_id=room_id,
        player_id=player_id,
        actor_id="actor-viewer",
        client_action_id="current",
        utterance="是的",
    )
    player_view = PlayerView(
        room_id=room_id,
        player_id=player_id,
        actor_id="actor-viewer",
        background="玩家安全背景",
        scene_id="study",
        phase="playing",
        revision="9",
        self_actor=SelfActorView(id="actor-viewer", name="调查员"),
        scene=SceneView(id="study", name="书房", description="安静的书房"),
    )
    return player_input, player_view


def execution(
    *,
    room_id: str,
    player_id: str,
    actor_id: str,
    correlation_id: str,
    summary: str,
    secret: str = "",
    created_at: datetime | None = None,
) -> ActionExecution:
    request = ActionRequest(
        request_id=correlation_id,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        source_view_revision="4",
        intent=Intent(
            kind="dialogue",
            verb="talk",
            target=MatchedTarget(id="thomas"),
            check=NoCheck(),
            summary=summary,
        ),
    )
    result = EngineExecutionResult(
        action_result=ActionResult(
            request_id=correlation_id,
            action_id=f"action:{correlation_id}",
            resolution="direct",
            outcome="success",
            visible_facts=(VisibleFact(id=f"fact:{correlation_id}", text="托马斯听见了。"),),
            view_revision="5",
        ),
        confirmed_facts=(secret,) if secret else (),
        state_version=5,
    )
    return ActionExecution(
        room_id=room_id,
        request_id=correlation_id,
        request_json=request.to_json_dict(),
        result_json=result.to_json_dict(),
        committed_state_version=5,
        created_at=created_at or datetime.now(UTC),
    )


async def test_sql_history_projects_public_and_own_private_without_secret(
    db_session: AsyncSession,
    recent_history_source: SqlAlchemyRecentHistorySource,
) -> None:
    room_id = "50000000-0000-0000-0000-000000000001"
    viewer_id = "50000000-0000-0000-0000-000000000002"
    other_id = "50000000-0000-0000-0000-000000000003"
    db_session.add(Room(id=room_id, room_code="RH0168", room_name="近期历史", max_players=2))
    db_session.add_all(
        [
            Player(
                id=viewer_id,
                room_id=room_id,
                nickname="调查员",
                reconnect_token="50000000-0000-0000-0000-000000000012",
            ),
            Player(
                id=other_id,
                room_id=room_id,
                nickname="同伴",
                reconnect_token="50000000-0000-0000-0000-000000000013",
            ),
        ]
    )
    base = datetime(2026, 7, 29, tzinfo=UTC)
    own_correlation = "own-prior"
    other_correlation = "other-prior"
    events = [
        Event(
            id="50000000-0000-0000-0000-000000000101",
            room_id=room_id,
            player_id=other_id,
            event_type="action.broadcast",
            correlation_id=other_correlation,
            visibility="public",
            actor_id="actor-other",
            scene_id="study",
            view_revision="3",
            payload={"utterance": "我去查看那些书"},
            created_at=base,
        ),
        Event(
            id="50000000-0000-0000-0000-000000000102",
            room_id=room_id,
            player_id=other_id,
            event_type="narration.push",
            correlation_id=other_correlation,
            visibility="player_scoped",
            actor_id="actor-other",
            scene_id="study",
            view_revision="4",
            payload={"text": SECRET},
            created_at=base + timedelta(seconds=1),
        ),
        Event(
            id="50000000-0000-0000-0000-000000000103",
            room_id=room_id,
            player_id=viewer_id,
            event_type="action.broadcast",
            correlation_id=own_correlation,
            visibility="public",
            actor_id="actor-viewer",
            scene_id="study",
            view_revision="4",
            payload={"utterance": "五本书被叔叔一起带走"},
            created_at=base + timedelta(seconds=2),
        ),
        Event(
            id="50000000-0000-0000-0000-000000000104",
            room_id=room_id,
            player_id=viewer_id,
            event_type="narration.push",
            correlation_id=own_correlation,
            visibility="player_scoped",
            actor_id="actor-viewer",
            scene_id="study",
            view_revision="5",
            payload={"text": "托马斯问你是否确定。"},
            created_at=base + timedelta(seconds=3),
        ),
        Event(
            id="50000000-0000-0000-0000-000000000105",
            room_id=room_id,
            player_id=viewer_id,
            event_type="action.broadcast",
            correlation_id="current",
            visibility="public",
            actor_id="actor-viewer",
            scene_id="study",
            view_revision="9",
            payload={"utterance": "是的"},
            created_at=base + timedelta(seconds=4),
        ),
    ]
    db_session.add_all(events)
    db_session.add_all(
        [
            execution(
                room_id=room_id,
                player_id=other_id,
                actor_id="actor-other",
                correlation_id=other_correlation,
                summary="其他玩家的私有语义",
                secret=SECRET,
                created_at=base + timedelta(seconds=1),
            ),
            execution(
                room_id=room_id,
                player_id=viewer_id,
                actor_id="actor-viewer",
                correlation_id=own_correlation,
                summary="告诉托马斯五本书被叔叔带走",
                created_at=base + timedelta(seconds=3),
            ),
        ]
    )
    await db_session.commit()
    player_input, player_view = current_scope(room_id, viewer_id)

    context = await recent_history_source.read(
        player_input=player_input,
        player_view=player_view,
        exclude_correlation_id="current",
        budget=RecentHistoryBudget(max_turns=6, max_chars=6000),
    )

    assert [turn.correlation_id for turn in context.turns] == [
        other_correlation,
        own_correlation,
    ]
    other, own = context.turns
    assert other.accepted_intent_summary is None
    assert other.player_safe_result is None
    assert other.published_narration is None
    assert own.accepted_intent_summary == "告诉托马斯五本书被叔叔带走"
    assert own.player_safe_result is not None
    assert own.published_narration is not None
    assert own.published_narration.visibility == "player_scoped"
    assert "current" not in {turn.correlation_id for turn in context.turns}
    assert SECRET not in context.model_dump_json()

    db_session.add(
        Event(
            id="50000000-0000-0000-0000-000000000106",
            room_id=room_id,
            player_id=other_id,
            event_type="action.broadcast",
            correlation_id="later-action",
            visibility="public",
            actor_id="actor-other",
            scene_id="study",
            view_revision="10",
            payload={"utterance": "当前动作之后才发生的回合"},
            created_at=base + timedelta(seconds=5),
        )
    )
    await db_session.commit()
    retried = await recent_history_source.read(
        player_input=player_input,
        player_view=player_view,
        exclude_correlation_id="current",
        budget=RecentHistoryBudget(max_turns=6, max_chars=6000),
    )
    assert retried.model_dump_json() == context.model_dump_json()


async def test_sql_history_selection_keeps_adjacent_then_prefers_same_scene(
    db_session: AsyncSession,
    recent_history_source: SqlAlchemyRecentHistorySource,
) -> None:
    room_id = "60000000-0000-0000-0000-000000000001"
    viewer_id = "60000000-0000-0000-0000-000000000002"
    db_session.add(Room(id=room_id, room_code="RH0169", room_name="裁剪历史", max_players=1))
    db_session.add(
        Player(
            id=viewer_id,
            room_id=room_id,
            nickname="调查员",
            reconnect_token="60000000-0000-0000-0000-000000000012",
        )
    )
    base = datetime(2026, 7, 29, tzinfo=UTC)
    rows: list[Event] = []
    for index in range(8):
        rows.append(
            Event(
                id=f"60000000-0000-0000-0000-{index + 100:012d}",
                room_id=room_id,
                player_id=viewer_id,
                event_type="action.broadcast",
                correlation_id=f"prior-{index}",
                visibility="public",
                actor_id="actor-viewer",
                scene_id="study" if index in {1, 3, 5} else "street",
                view_revision=str(index),
                payload={"utterance": f"第{index}回合" + ("甲" * 1000)},
                created_at=base + timedelta(seconds=index),
            )
        )
    rows.append(
        Event(
            id="60000000-0000-0000-0000-000000000200",
            room_id=room_id,
            player_id=viewer_id,
            event_type="action.broadcast",
            correlation_id="current",
            visibility="public",
            actor_id="actor-viewer",
            scene_id="study",
            view_revision="9",
            payload={"utterance": "继续"},
            created_at=base + timedelta(seconds=9),
        )
    )
    db_session.add_all(rows)
    await db_session.commit()
    player_input, player_view = current_scope(room_id, viewer_id)

    context = await recent_history_source.read(
        player_input=player_input,
        player_view=player_view,
        exclude_correlation_id="current",
        budget=RecentHistoryBudget(max_turns=3, max_chars=6000),
    )

    assert [turn.correlation_id for turn in context.turns] == [
        "prior-3",
        "prior-5",
        "prior-7",
    ]
    assert all(
        len(turn.player_utterance.text) == 800 and turn.player_utterance.text.endswith("…")
        for turn in context.turns
    )

    default_budget_context = await recent_history_source.read(
        player_input=player_input,
        player_view=player_view,
        exclude_correlation_id="current",
        budget=RecentHistoryBudget(max_turns=6, max_chars=6000),
    )
    assert len(default_budget_context.turns) == 6
    assert default_budget_context.turns[-1].correlation_id == "prior-7"
    assert len(default_budget_context.model_dump_json()) > 0
    assert sum(len(turn.player_utterance.text) for turn in default_budget_context.turns) <= 6000

    minimum_budget_context = await recent_history_source.read(
        player_input=player_input,
        player_view=player_view,
        exclude_correlation_id="current",
        budget=RecentHistoryBudget(max_turns=6, max_chars=2),
    )
    assert [turn.correlation_id for turn in minimum_budget_context.turns] == ["prior-7"]
    assert sum(len(turn.player_utterance.text) for turn in minimum_budget_context.turns) <= 2
