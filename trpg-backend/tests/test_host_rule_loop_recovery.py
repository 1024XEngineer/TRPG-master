"""Focused regression coverage for composite keeper action recovery (#489)."""

from __future__ import annotations

import pytest
from collaboration_framework.contracts import (
    KeeperCapabilityView,
    KeeperRuleCandidate,
    KeeperRuleOption,
    PlayerInput,
)
from collaboration_framework.host.schemas import ActionPlanNarrationOutput
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller import ws as ws_controller
from app.core.action_plan_turn import ActionPlanTurnResult
from app.core.host_entry import HostEntryContext, HostEntryDecision, HostPublicContext
from app.core.host_rule_loop import RuleLoopStep, new_rule_loop
from app.dto.ws import ActionRecipientPayload
from app.models.event import Event
from app.service import host_action_queue
from tests.test_engine_runtime import _start_room


@pytest.mark.asyncio
async def test_composite_loop_runs_two_steps_before_one_outer_completion(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, players, _ = await _start_room(
        db_session, room_number=4891, player_count=1, prepare_checkpoint=False
    )
    player = players[0]
    views = [
        await ws_controller.session_view_application.current_player_view(
            room_id=room.id, player_id=player.id
        )
    ]
    views.append(views[0].model_copy(update={"revision": "2"}))
    views.append(views[0].model_copy(update={"revision": "3"}))
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=player.id,
        actor_id=views[0].self_actor.id,
        client_action_id="composite-two-steps",
        utterance="先检查门，然后翻看桌面",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    await host_action_queue.save_execution_route(
        db_session,
        item,
        route="composite_rule",
        text=None,
        provenance="test",
    )
    await host_action_queue.save_rule_loop(
        db_session,
        item,
        new_rule_loop(
            client_action_id=item.client_action_id,
            player_id=item.player_id,
            actor_id=item.actor_id,
        ),
    )
    item = await host_action_queue.claim(db_session, item, recipient_kind="keeper")
    assert item is not None

    candidate = KeeperRuleCandidate(
        rule_id="observe",
        question_kind="action_declaration",
        target_kinds=("location",),
        options=(
            KeeperRuleOption(id="door", requires_check=False),
            KeeperRuleOption(id="desk", requires_check=False),
        ),
    )
    capabilities = KeeperCapabilityView(
        room_id=room.id,
        actor_id=views[0].self_actor.id,
        revision="1",
        rule_candidates=(candidate,),
    )

    async def host_context(**kwargs):  # noqa: ANN003, ARG001
        return HostEntryContext(public=HostPublicContext(current_keeper_text="复合行动"))

    monkeypatch.setattr(ws_controller, "_host_entry_context", host_context)

    async def fake_capabilities(player_input, player_view):  # noqa: ANN001
        return capabilities.model_copy(
            update={"revision": player_view.revision, "actor_id": player_input.actor_id}
        )

    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "_keeper_capabilities",
        fake_capabilities,
    )
    router_calls: list[int] = []

    class Router:
        async def decide(self, context):  # noqa: ANN001
            index = len(router_calls)
            router_calls.append(index)
            if index < 2:
                return HostEntryDecision(
                    route="rule_once",
                    rule_id="observe",
                    option_id=("door" if index == 0 else "desk"),
                    target_kind="location",
                    target_id=views[0].scene.id,
                ), "test"
            return HostEntryDecision(route="direct_response", text="行动处理完毕。"), "test"

    monkeypatch.setattr(ws_controller, "_get_host_entry_router", lambda: Router())
    view_calls = 0

    async def current_view(_self, *, room_id: str, player_id: str):  # noqa: ARG001
        nonlocal view_calls
        view = views[min(view_calls, len(views) - 1)]
        view_calls += 1
        return view

    monkeypatch.setattr(
        type(ws_controller.session_view_application), "current_player_view", current_view
    )
    starts: list[str] = []

    async def fake_start_rule_once(**kwargs):  # noqa: ANN003
        starts.append(kwargs["step_request_id"])
        index = len(starts) - 1
        return ActionPlanTurnResult(
            player_input=PlayerInput(
                room_id=room.id,
                player_id=player.id,
                actor_id=views[0].self_actor.id,
                client_action_id=kwargs["step_request_id"],
                utterance=item.utterance,
            ),
            player_view=views[index],
            status="completed",
            narration=ActionPlanNarrationOutput(
                kind="narration", text=f"第 {index + 1} 步已确认。"
            ),
            plan_id=f"plan-{index}",
        )

    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "start_rule_once",
        fake_start_rule_once,
    )

    async def noop_async(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "mark_narration_persisted",
        noop_async,
    )
    monkeypatch.setattr(ws_controller.time_advance_service, "mark_narration_persisted", noop_async)
    monkeypatch.setattr(
        ws_controller.scene_transition_service, "mark_narration_persisted", noop_async
    )

    outer_room_id = room.id
    await ws_controller._run_composite_rule_action(db_session, item, views[0], None)
    db_session.expire_all()
    completed = await host_action_queue.get_by_client_action(
        db_session, outer_room_id, "composite-two-steps"
    )
    events = (
        await db_session.scalars(
            select(Event)
            .where(Event.room_id == outer_room_id, Event.event_type == "narration.push")
            .order_by(Event.created_at, Event.id)
        )
    ).all()
    assert starts == ["composite-two-steps:rule:0", "composite-two-steps:rule:1"]
    assert router_calls == [0, 1, 2]
    assert completed is not None and completed.status == "completed"
    assert [event.correlation_id for event in events] == [
        "composite-two-steps:step:0",
        "composite-two-steps:step:1",
        "composite-two-steps",
    ]
    assert completed.rule_loop_json is not None
    assert completed.rule_loop_json["step_index"] == 2


@pytest.mark.asyncio
async def test_composite_step_feedback_is_broadcast_once_after_persistence(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, players, _ = await _start_room(
        db_session, room_number=4892, player_count=1, prepare_checkpoint=False
    )
    view = await ws_controller.session_view_application.current_player_view(
        room_id=room.id, player_id=players[0].id
    )
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id=view.self_actor.id,
        client_action_id="composite-feedback-once",
        utterance="检查门",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    step = RuleLoopStep(
        index=0,
        step_id="composite-feedback-once:rule:0",
        request_id="composite-feedback-once:rule:0",
        source_revision=view.revision,
        rule_id="observe",
        option_id="door",
    )
    emitted: list[str] = []

    async def emit(*args, **kwargs):  # noqa: ANN002, ANN003
        emitted.append(kwargs["client_action_id"])

    monkeypatch.setattr(ws_controller, "_emit_turn_narration", emit)
    first = await ws_controller._persist_composite_step_feedback(
        db_session, item, view, step, "门保持关闭。", None
    )
    second = await ws_controller._persist_composite_step_feedback(
        db_session, item, view, first, "门保持关闭。", None
    )
    assert second.feedback_correlation_id == "composite-feedback-once:step:0"
    assert emitted == ["composite-feedback-once:step:0"]
    count = await db_session.scalar(
        select(Event.id).where(
            Event.room_id == room.id,
            Event.event_type == "narration.push",
            Event.correlation_id == "composite-feedback-once:step:0",
        )
    )
    assert count is not None


@pytest.mark.asyncio
async def test_composite_action_lookup_uses_outer_client_action_id(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session, room_number=4893, player_count=1, prepare_checkpoint=False
    )
    view = await ws_controller.session_view_application.current_player_view(
        room_id=room.id, player_id=players[0].id
    )
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id=view.self_actor.id,
        client_action_id="outer-action-id",
        utterance="检查门",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    await host_action_queue.save_execution_route(
        db_session, item, route="composite_rule", text=None, provenance="test"
    )
    step = RuleLoopStep(
        index=0,
        step_id="outer-action-id:rule:0",
        request_id="outer-action-id:rule:0",
        source_revision=view.revision,
        rule_id="observe",
        option_id="door",
    )
    await host_action_queue.save_rule_loop(
        db_session,
        item,
        new_rule_loop(
            client_action_id="outer-action-id",
            player_id=players[0].id,
            actor_id=view.self_actor.id,
        ).model_copy(update={"steps": (step,), "status": "awaiting_player"}),
    )
    resolved = await ws_controller._find_composite_action(db_session, room.id, "outer-action-id")
    assert resolved is not None
    assert resolved[2].step_id == "outer-action-id:rule:0"


@pytest.mark.asyncio
async def test_composite_failure_stops_without_removing_prior_feedback(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session, room_number=4894, player_count=1, prepare_checkpoint=False
    )
    view = await ws_controller.session_view_application.current_player_view(
        room_id=room.id, player_id=players[0].id
    )
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id=view.self_actor.id,
        client_action_id="composite-stop-safe",
        utterance="先检查门，然后翻看桌面",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    await host_action_queue.save_execution_route(
        db_session, item, route="composite_rule", text=None, provenance="test"
    )
    step = RuleLoopStep(
        index=0,
        step_id="composite-stop-safe:rule:0",
        request_id="composite-stop-safe:rule:0",
        source_revision=view.revision,
        rule_id="observe",
        option_id="door",
        status="feedback_persisted",
        feedback_correlation_id="composite-stop-safe:step:0",
        feedback_text="门保持关闭。",
    )
    loop = new_rule_loop(
        client_action_id=item.client_action_id,
        player_id=item.player_id,
        actor_id=item.actor_id,
    ).model_copy(update={"step_index": 1, "steps": (step,)})
    await host_action_queue.save_rule_loop(db_session, item, loop)
    await ws_controller._persist_composite_step_feedback(
        db_session, item, view, step, "门保持关闭。", None
    )
    await ws_controller._stop_composite_rule_action(
        db_session,
        item,
        view,
        None,
        stop_reason="rule_rejected",
    )
    outer_room_id = room.id
    db_session.expire_all()
    stopped = await host_action_queue.get_by_client_action(
        db_session, outer_room_id, "composite-stop-safe"
    )
    events = (
        await db_session.scalars(
            select(Event)
            .where(Event.room_id == outer_room_id, Event.event_type == "narration.push")
            .order_by(Event.created_at, Event.id)
        )
    ).all()
    assert stopped is not None and stopped.status == "completed"
    assert stopped.rule_loop_json is not None
    assert stopped.rule_loop_json["status"] == "stopped"
    assert [event.correlation_id for event in events] == [
        "composite-stop-safe:step:0",
        "composite-stop-safe",
    ]
