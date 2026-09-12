"""Immediate and queued keeper requests must execute the same frozen rule."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    EnterLocationEffect,
    ModuleContentV3,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from sqlalchemy import func, select
from starlette.testclient import TestClient

from app.controller import ws as ws_controller
from app.core.host_entry import HostEntryRouter
from app.dto.ws import ActionRecipientPayload
from app.models.engine import GameEvent, GameSession
from app.models.event import Event
from app.service import host_action_queue
from app.service.action_lock import action_lock_manager
from tests.test_accompanying_host import FIXTURE
from tests.test_ws import (
    complete_character,
    create_room,
    receive_until,
    register_and_login,
    start_game,
)
from tests.test_ws import sync_client as sync_client

ACTION_ID = "frozen-rule-request"
UTTERANCE = "把詹姆斯带出大门"
KEEPER = ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True)


class _RuleEntryModel:
    def __init__(self):
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        assert context.rule_match is not None
        assert any(
            rule.rule_id == "force_james_out_of_resort"
            for rule in context.rule_match.rule_candidates
        )
        return {
            "route": "rule_once",
            "rule_id": "force_james_out_of_resort",
            "option_id": "force-james-out",
            "target_kind": "entity",
            "target_id": "james",
            "summary": "强行把詹姆斯带出度假村",
        }


def _prepare_room(client, monkeypatch):
    content = ModuleContentV3.model_validate_json(FIXTURE.read_text())
    token = register_and_login(client, "rule_once_host")
    room = create_room(client, token)
    headers = {"X-Reconnect-Token": room["reconnectToken"]}
    base = f"/api/v1/rooms/{room['roomId']}"
    response = client.post(
        f"{base}/module",
        json={"moduleId": content.module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    assert response.status_code == 200
    assert client.post(f"{base}/start-story", headers=headers).status_code == 200
    complete_character(client, room["roomId"], room["reconnectToken"])
    start_game(client, room, token)
    model = _RuleEntryModel()
    router = HostEntryRouter(model)
    monkeypatch.setattr(ws_controller, "_get_host_entry_router", lambda: router)
    # Drain explicitly so timing cannot accidentally test the immediate path.
    monkeypatch.setattr(ws_controller, "schedule_host_action_drain", lambda _: None)
    application = ws_controller.action_plan_turn_application
    planner = AsyncMock(side_effect=AssertionError("rule_once must not replan"))
    adjudicator = AsyncMock(side_effect=AssertionError("rule_once already has a rule"))
    monkeypatch.setattr(application, "_semantic_planner", SimpleNamespace(generate=planner))
    monkeypatch.setattr(application._orchestrator.adjudicator, "adjudicate", adjudicator)
    return room, token, model, planner, adjudicator


async def _place_party(room_id):
    application = ws_controller.session_view_application
    async with application.store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    actor = next(actor for actor in runtime.game_state.actors.values() if actor.player_id)
    assert actor.player_id is not None
    # The reception layout is revealed by arrival, not by a bare scene_id edit.
    for destination in ("frog_resort", "resort_reception"):
        view = await application.current_player_view(room_id=room_id, player_id=actor.player_id)
        await ws_controller.adjudication_engine_service.submit(
            SubmitAdjudicationRequest(
                room_id=room_id,
                player_id=actor.player_id,
                adjudication=ActionAdjudication(
                    request_id=f"setup-{destination}",
                    source_revision=view.revision,
                    actor_id=view.self_actor.id,
                    summary="沿公开路线抵达前台",
                    target=ActionTarget(kind="location", id=destination),
                    method=ActionMethod(family="travel", description="前往前台"),
                    persistence_intent="location",
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id=destination),),
                ),
            )
        )


async def _snapshot(room_id):
    async with ws_controller.async_session_factory() as db:
        session = await db.get(GameSession, room_id)
        assert session is not None
        events = await db.scalar(
            select(func.count()).select_from(GameEvent).where(GameEvent.room_id == room_id)
        )
        item = await host_action_queue.get_by_client_action(db, room_id, ACTION_ID)
        narrations = await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.room_id == room_id,
                Event.event_type == "narration.push",
                Event.correlation_id == ACTION_ID,
            )
        )
        return session.state_json, session.state_version, events, item, narrations


def _join(ws, room):
    ws.send_json(
        {
            "type": "room.join",
            "playerId": room["playerId"],
            "payload": {"reconnectToken": room["reconnectToken"]},
        }
    )
    receive_until(ws, lambda message: message.get("type") == "view.updated")


def _submit(ws, room):
    ws.send_json(
        {
            "type": "action.plan.submit",
            "playerId": room["playerId"],
            "payload": {
                "clientActionId": ACTION_ID,
                "utterance": UTTERANCE,
                "recipient": KEEPER.model_dump(by_alias=True),
            },
        }
    )


def _execute(ws, room, path):
    lock_token = None
    if path == "queued":
        view = ws.portal.call(
            lambda: ws_controller.session_view_application.current_player_view(
                room_id=room["roomId"], player_id=room["playerId"]
            )
        )
        lock_token = action_lock_manager.try_acquire(
            room["roomId"],
            player_id=room["playerId"],
            actor_id=view.self_actor.id,
            client_action_id="other-action",
            revision=view.revision,
        )
        assert lock_token is not None
    try:
        _submit(ws, room)
        if path == "queued":
            receive_until(ws, lambda message: message.get("type") == "action.broadcast", limit=40)
    finally:
        if lock_token is not None:
            action_lock_manager.release(room["roomId"], lock_token)
    if path == "queued":
        ws.portal.call(ws_controller._drain_host_action_queue, room["roomId"])
    completed, seen = receive_until(
        ws,
        lambda message: (
            message.get("message_type") == "turn.completed"
            and message.get("correlation_id") == ACTION_ID
        ),
        limit=60,
    )
    assert not any(message.get("type") == "turn.failed" for message in seen)
    return completed


@pytest.mark.parametrize("path", ["immediate", "queued"])
def test_rule_once_executes_and_replays_without_replanning(
    sync_client: TestClient, monkeypatch, path
):
    room, token, model, planner, adjudicator = _prepare_room(sync_client, monkeypatch)
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.portal.call(_place_party, room["roomId"])
        _join(ws, room)
        completed = _execute(ws, room, path)
        text = completed["payload"]["narration"]["text"]
        assert "詹姆斯·莱恩已经死亡" in text
        assert "强行带离没能救回他" in text
        assert "城郊道路" in text
        before = ws.portal.call(_snapshot, room["roomId"])
        state, _, _, item, narrations = before
        assert state["entities"]["james"]["under_forced_custody"] is True
        assert state["entities"]["james"]["consciousness"] == "dead"
        assert item is not None and item.execution_route == "rule_once"
        assert item.status == "completed"
        assert narrations == 1
        # Resume after effects advanced the revision and removed rule candidates.
        ws.portal.call(ws_controller._start_keeper_action, item, None)
        _submit(ws, room)
        receive_until(ws, lambda message: message.get("message_type") == "turn.completed")
        after = ws.portal.call(_snapshot, room["roomId"])
        assert after[:3] == before[:3]
        assert after[4] == 1
    assert model.calls == 1
    planner.assert_not_called()
    adjudicator.assert_not_called()


@pytest.mark.parametrize("path", ["immediate", "queued"])
def test_stale_rule_is_closed_and_replayed_without_execution(
    sync_client: TestClient, monkeypatch, path
):
    room, token, model, planner, adjudicator = _prepare_room(sync_client, monkeypatch)
    route = ws_controller._route_keeper_queue_item

    async def make_stale(db, item, view):
        result = await route(db, item, view)
        item.rule_request_json = {**item.rule_request_json, "source_revision": "outdated"}
        await db.commit()
        return result

    monkeypatch.setattr(ws_controller, "_route_keeper_queue_item", make_stale)
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.portal.call(_place_party, room["roomId"])
        _join(ws, room)
        before = ws.portal.call(_snapshot, room["roomId"])
        completed = _execute(ws, room, path)
        assert "规则条件" in completed["payload"]["narration"]["text"]
        _submit(ws, room)
        receive_until(ws, lambda message: message.get("message_type") == "turn.completed")
        after = ws.portal.call(_snapshot, room["roomId"])
        assert after[:3] == before[:3]
        assert after[3].status == "completed"
        assert after[4] == 1
        run = ws.portal.call(
            ws_controller.action_plan_turn_application.get_plan, room["roomId"], ACTION_ID
        )
        assert run is None
    assert model.calls == 1
    planner.assert_not_called()
    adjudicator.assert_not_called()
