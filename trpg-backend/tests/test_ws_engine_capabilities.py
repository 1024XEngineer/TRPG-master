"""Issue #212 capabilities must survive the whole round trip to the client.

`tests/test_engine_capability_projection.py` (framework) proves the Engine
commits each registered effect and the projection shows it. These tests close
the loop the player actually experiences: an Agent proposes the effect, the
WebSocket turn commits it, and the `PlayerView` pushed to the browser carries
the change.

The Agent is scripted rather than a real model, so the assertions are about the
plumbing (Agent -> Engine -> projection -> transport), not about how well a model
chooses effects.
"""

from __future__ import annotations

from typing import Any

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceTimeEffect,
    CommitTerminalEndingEffect,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    MarkCoreResolvedEffect,
    NoAdjudicationCheck,
    RevealInformationEffect,
    SetEndingAvailabilityEffect,
    SingleActionDecision,
)
from starlette.testclient import TestClient

from app.controller import ws as ws_controller
from app.main import app
from tests.test_ws import (
    advance_to_building,
    complete_character,
    create_room,
    receive_replayed_opening,
    receive_until,
    register_and_login,
    start_game,
)


@pytest.fixture
def sync_client() -> TestClient:
    # `sync_client` lives in test_ws.py as a fixture, and pytest fixtures are
    # not importable across modules; the body is a one-liner, so redeclare it.
    return TestClient(app)

# Paper Chase, the module the WebSocket suite loads: the opening scene, a
# keeper-only Information nobody has discovered yet, and one declared Ending.
OPENING_SCENE = "client_briefing"
KEEPER_INFORMATION = "lyla_cemetery_sighting"
# A second keeper-only Information no test ever reveals, used to prove the
# capability list does not leak what the turn did not release.
UNDISCLOSED_INFORMATION = "douglas_true_nature"
ENDING_ID = "ending_douglas_departs"


class _ScriptedEffectPlanner:
    """Return one single action whose success_effects are fixed by the test."""

    def __init__(self, *effects) -> None:
        self._effects = tuple(effects)
        self.contexts: list[Any] = []

    async def generate(self, context) -> SingleActionDecision:
        self.contexts.append(context)
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=context.player_input.utterance,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(
                    family="action",
                    description=context.player_input.utterance,
                ),
                check=NoAdjudicationCheck(),
                success_effects=self._effects,
            )
        )


def _play_one_action(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    account: str,
    *effects,
) -> tuple[dict, _ScriptedEffectPlanner]:
    """Run a single scripted action and return the turn's authoritative PlayerView."""

    token = register_and_login(sync_client, account)
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    planner = _ScriptedEffectPlanner(*effects)
    monkeypatch.setattr(ws_controller.action_plan_turn_application, "_planner", planner)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        receive_replayed_opening(ws)
        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": f"{account}-action",
                    "utterance": "我按自己的想法行动",
                },
            }
        )
        completed, seen = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=40,
        )

    assert all(message.get("type") != "turn.failed" for message in seen), seen
    return completed["payload"]["player_view"], planner


def test_revealed_information_reaches_the_client(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_reveal",
        RevealInformationEffect(information_id=KEEPER_INFORMATION),
    )

    assert KEEPER_INFORMATION in {item["id"] for item in view["known_information"]}


def test_runtime_entity_reaches_the_client_scene(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_entity",
        EnsureRuntimeEntityEffect(
            entity_id="briefing_clerk",
            entity_kind="npc",
            name="送信来的信差",
            location_id=OPENING_SCENE,
        ),
    )

    clerk = next(
        entity for entity in view["scene"]["visible_entities"] if entity["id"] == "briefing_clerk"
    )
    assert clerk["name"] == "送信来的信差"
    assert clerk["kind"] == "npc"


def test_runtime_location_is_created_entered_and_projected(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One atomic adjudication may create a location and move the actor into it."""

    view, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_location",
        EnsureRuntimeLocationEffect(
            location_id="briefing_street",
            name="会客室外的街道",
            connected_location_id=OPENING_SCENE,
        ),
        EnterLocationEffect(location_id="briefing_street"),
    )

    assert view["scene_id"] == "briefing_street"
    assert view["scene"]["name"] == "会客室外的街道"
    assert OPENING_SCENE in {
        exit_["destination"]["scene_id"]
        for exit_ in view["scene"]["available_exits"]
        if exit_["destination"] is not None
    }


def test_advanced_time_reaches_the_client(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_time",
        AdvanceTimeEffect(minutes=13 * 60, reason="整个下午都在走访"),
    )

    assert view["world"]["elapsed_minutes"] == 13 * 60
    assert view["world"]["time_of_day"] == "night"


def test_ending_availability_and_confirmation_reach_the_client(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_ending_open",
        MarkCoreResolvedEffect(),
        SetEndingAvailabilityEffect(available=True),
    )

    assert opened["world"]["core_resolved"] is True
    assert opened["world"]["ending_available"] is True
    assert opened["world"]["ending_id"] is None
    assert opened["phase"] == "playing"

    confirmed, _ = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_ending_confirm",
        MarkCoreResolvedEffect(),
        SetEndingAvailabilityEffect(available=True),
        CommitTerminalEndingEffect(ending_id=ENDING_ID),
    )

    assert confirmed["world"]["ending_id"] == ENDING_ID
    assert confirmed["phase"] == "ended"


def test_planner_receives_keeper_capabilities_but_the_client_never_does(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Agent gets the Canon vocabulary; the transport payload must not."""

    view, planner = _play_one_action(
        sync_client,
        monkeypatch,
        "cap_keeper_view",
        RevealInformationEffect(information_id=KEEPER_INFORMATION),
    )

    capabilities = planner.contexts[0].keeper_capabilities
    assert capabilities is not None
    assert capabilities.revision == planner.contexts[0].player_view.revision
    assert KEEPER_INFORMATION in {item.id for item in capabilities.information}
    assert ENDING_ID in {item.id for item in capabilities.endings}
    # Keeper-only content is what the Agent judges with; anything this turn did
    # not release must not ride along to the browser in any shape.
    undisclosed = next(
        item for item in capabilities.information if item.id == UNDISCLOSED_INFORMATION
    )
    assert "keeper_capabilities" not in view
    assert UNDISCLOSED_INFORMATION not in str(view)
    assert undisclosed.content not in str(view)
