"""Opt-in smoke test for a configured real opening-narration provider.

CI intentionally keeps using deterministic fakes. Local/preview verification can load a
real provider key and set ``RUN_OPENING_PROVIDER_SMOKE=1`` to exercise the complete
``game.start`` WebSocket, persistence, retry, and history path.
"""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import app
from tests.test_ws import (
    ROOMS_BASE,
    advance_to_building,
    complete_character,
    create_room,
    receive_until,
    register_and_login,
)

RUN_OPENING_PROVIDER_SMOKE = os.getenv("RUN_OPENING_PROVIDER_SMOKE") == "1"


@pytest.mark.skipif(
    not RUN_OPENING_PROVIDER_SMOKE,
    reason="set RUN_OPENING_PROVIDER_SMOKE=1 with a real provider key",
)
def test_configured_provider_generates_one_authoritative_opening() -> None:
    settings = Settings()
    assert settings.host_model_provider in {"deepseek", "qwen", "openai"}

    client = TestClient(app)
    try:
        token = register_and_login(client, f"opening_{settings.host_model_provider}")
        room = create_room(client, token)
        advance_to_building(client, room)
        complete_character(
            client,
            room["roomId"],
            room["reconnectToken"],
            name="陈探员",
        )

        with client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
            ws.send_json(
                {
                    "type": "room.join",
                    "playerId": room["playerId"],
                    "payload": {"reconnectToken": room["reconnectToken"]},
                }
            )
            assert ws.receive_json()["type"] == "session.bound"
            ws.send_json(
                {
                    "type": "game.start",
                    "playerId": room["playerId"],
                    "payload": {},
                }
            )
            opening, progress = receive_until(
                ws,
                lambda message: message.get("type") == "narration.push",
            )

            ws.send_json(
                {
                    "type": "game.start",
                    "playerId": room["playerId"],
                    "payload": {},
                }
            )
            ws.send_json(
                {
                    "type": "room.join",
                    "playerId": room["playerId"],
                    "payload": {"reconnectToken": room["reconnectToken"]},
                }
            )
            _, retry_progress = receive_until(
                ws,
                lambda message: message.get("type") == "session.bound",
            )

        assert any(message.get("type") == "opening.started" for message in progress)
        assert opening["payload"]["messageId"] == "game-opening"
        assert "陈探员" in opening["payload"]["text"]
        assert not any(
            message.get("type") in {"opening.started", "narration.push"}
            for message in retry_progress
        )

        conversation = client.get(
            f"{ROOMS_BASE}/{room['roomId']}/conversation",
            headers={"X-Reconnect-Token": room["reconnectToken"]},
        ).json()["data"]
        openings = [
            event
            for event in conversation
            if event["type"] == "narration.push"
            and event["payload"].get("messageId") == "game-opening"
        ]
        assert len(openings) == 1
        assert openings[0]["id"] == "game-opening"
        assert openings[0]["payload"] == opening["payload"]

        replay = client.get(
            f"{ROOMS_BASE}/{room['roomId']}/replay",
            headers={"X-Reconnect-Token": room["reconnectToken"]},
        ).json()["data"]
        persisted_openings = [
            event
            for event in replay
            if event["eventType"] == "narration.push"
            and event["payload"].get("messageId") == "game-opening"
        ]
        assert len(persisted_openings) == 1
        assert persisted_openings[0]["playerId"] is None
        assert persisted_openings[0]["payload"] == opening["payload"]
    finally:
        client.close()
