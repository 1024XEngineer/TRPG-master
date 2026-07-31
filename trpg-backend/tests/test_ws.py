from dataclasses import replace

import pytest
from collaboration_framework.contracts import ContractError, JsonObject
from collaboration_framework.host.adapters.fakes import FakeNarrationModel
from collaboration_framework.host.schemas import (
    IntentContext,
    NarrationContext,
    OpeningNarrationContext,
)
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.controller import ws as ws_controller
from app.core.turn import build_turn_application
from app.main import app

ROOMS_BASE = "/api/v1/rooms"


class _WsCandidateIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
        return {
            "kind": "action",
            "verb": "investigate",
            "target": {"matched": True, "id": context.player_view.scene.id},
            "check": {
                "route": "default",
                "proposed_skills": ["library-use", "stealth"],
            },
            "summary": context.player_input.utterance,
        }


class _WsAttackThenPlainIntentModel:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context: IntentContext) -> JsonObject:
        self.calls += 1
        if self.calls == 1:
            return {
                "kind": "action",
                "verb": "attack",
                "target": {"matched": True, "id": "thomas"},
                "check": {
                    "route": "default",
                    "proposed_skills": ["fighting-brawl"],
                },
                "summary": context.player_input.utterance,
            }
        return {
            "kind": "action",
            "verb": "talk",
            "target": {"matched": True, "id": "thomas"},
            "check": {"route": "none"},
            "summary": context.player_input.utterance,
        }


class _WsPlainIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
        return {
            "kind": "dialogue",
            "verb": "talk",
            "target": {"matched": True, "id": "thomas"},
            "check": {"route": "none"},
            "summary": context.player_input.utterance,
        }


class _WsInvalidTwiceThenSafeNarration:
    leaked_text = "托马斯看着你。 claimed_fact_ids: [],"

    def __init__(self) -> None:
        self.calls = 0
        self._fake = FakeNarrationModel()

    async def generate(self, context: NarrationContext) -> JsonObject:
        self.calls += 1
        if self.calls <= 2:
            return {
                "kind": "narration",
                "text": self.leaked_text,
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        return await self._fake.generate(context)


class _WsEscapedNewlineNarration:
    async def generate(self, context: NarrationContext) -> JsonObject:
        return {
            "kind": "narration",
            "text": "第一段\\r\\n第二段\\n第三段",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


class _WsMissingParticipantOpening:
    async def generate(self, context: OpeningNarrationContext) -> JsonObject:
        del context
        return {
            "kind": "narration",
            "text": "这段模型输出遗漏了所有在场角色姓名。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


@pytest.fixture
def sync_client() -> TestClient:
    # 用同一个 app 实例的同步 TestClient——HTTP 部分照常发请求准备房间/角色
    # 数据，WS 部分用它的 websocket_connect（httpx 异步 client 不支持 WS）。
    return TestClient(app)


def register_and_login(client: TestClient, account: str = "host1") -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": "secret1", "nickname": "房主"},
    )
    assert response.status_code == 201
    return response.json()["data"]["token"]


def create_room(client: TestClient, token: str, max_players: int = 1) -> dict:
    """建房（issue #106 起要求登录，房间会关联到这个账号）。"""
    response = client.post(
        ROOMS_BASE,
        json={
            "roomName": "WS测试房间",
            "nickname": "房主",
            "maxPlayers": max_players,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()["data"]


def join_as(client: TestClient, room_code: str, account: str, nickname: str = "访客") -> dict:
    """用一个**新账号**加入房间。

    必须是新账号：房间成员的幂等键是账号，拿房主的 token 再 join 会被当成重连、
    原样返回房主身份，测不出"两个人"。
    """
    token = register_and_login(client, account)
    response = client.post(
        f"{ROOMS_BASE}/{room_code}/join",
        json={"nickname": nickname},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    result = response.json()["data"]
    result["authToken"] = token
    return result


def complete_character(
    client: TestClient,
    room_id: str,
    reconnect_token: str,
    name: str = "陈探员",
) -> None:
    headers = {"X-Reconnect-Token": reconnect_token}
    draft = client.post(f"{ROOMS_BASE}/{room_id}/characters", headers=headers)
    character_id = draft.json()["data"]["characterId"]
    client.patch(
        f"{ROOMS_BASE}/{room_id}/characters/{character_id}",
        json={
            "name": name,
            "attributes": {
                "STR": 50,
                "CON": 50,
                "POW": 50,
                "DEX": 50,
                "APP": 50,
                "SIZ": 50,
                "INT": 50,
                "EDU": 50,
                "LUCK": 50,
            },
            "derivedStats": {"HP": 12},
            "skills": {},
            "equipment": [],
            "occupation": None,
            "background": "",
            "notes": "",
        },
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room_id}/characters/{character_id}/complete", headers=headers)


def advance_to_building(client: TestClient, room: dict) -> None:
    headers = {"X-Reconnect-Token": room["reconnectToken"]}
    preview = client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    max_players = preview["maxPlayers"]
    modules = client.get("/api/v1/modules").json()["data"]
    module_id = next(
        module["id"]
        for module in modules
        if module["playersMin"] <= max_players <= module["playersMax"]
    )
    client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room['roomId']}/start-story", headers=headers)


def start_game(client: TestClient, room: dict, token: str) -> None:
    with client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        narration, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )
        view = next(message for message in progress if message.get("type") == "view.updated")
        assert view["type"] == "view.updated"
        assert view["payload"]["playerId"] == room["playerId"]
        assert narration["payload"]["messageId"] == "game-opening"
        assert any(message.get("type") == "room.state" for message in progress)


def receive_until(ws, predicate, *, limit: int = 24):
    seen = []
    for _ in range(limit):
        message = ws.receive_json()
        seen.append(message)
        if predicate(message):
            return message, seen
    raise AssertionError(f"expected WebSocket event not found; seen={seen!r}")


def test_connect_without_token_is_rejected(sync_client: TestClient) -> None:
    room = create_room(sync_client, register_and_login(sync_client))

    with pytest.raises(WebSocketDisconnect), sync_client.websocket_connect(f"/ws/{room['roomId']}"):
        pass


def test_room_join_binds_session(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {
                    "reconnectToken": room["reconnectToken"],
                    "roomCode": room["roomCode"],
                    "nickname": "房主",
                },
            }
        )
        envelope = ws.receive_json()

    assert envelope == {
        "type": "session.bound",
        "payload": {"roomId": room["roomId"], "playerId": room["playerId"]},
    }


def test_room_join_with_unknown_player_closes_connection(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws,
    ):
        ws.send_json(
            {
                "type": "room.join",
                "playerId": "not-a-real-player",
                "payload": {"reconnectToken": "whatever"},
            }
        )
        ws.receive_json()
        ws.receive_json()


def test_room_join_rejects_wrong_reconnect_token(sync_client: TestClient) -> None:
    """拿对的 playerId 但错的 reconnect_token 不能绑定——否则任何登录账号都能
    用公开预览里暴露的 playerId 冒充别人（PR #78 review）。"""
    host_token = register_and_login(sync_client, "host_real")
    room = create_room(sync_client, host_token)
    # 一个"攻击者"账号，登录态有效，但没有房主的 reconnect_token。
    attacker_token = register_and_login(sync_client, "attacker")

    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={attacker_token}") as ws,
    ):
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],  # 房主的 playerId（预览里能拿到）
                "payload": {"reconnectToken": "not-the-real-token"},
            }
        )
        ws.receive_json()

    # 房主本人用正确的 token 仍然能正常绑定。
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={host_token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"


def test_player_ready_updates_room_state(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json(
            {"type": "player.ready", "playerId": room["playerId"], "payload": {"ready": True}}
        )

        # 让服务端处理完 player.ready 再去查——最简单的办法是紧接着发一条
        # room.join 强制走一次同步的事件处理再返回。
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["players"][0]["ready"] is True


def test_game_start_pushes_opening_narration_and_advances_phase(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        envelope, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
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

    view = next(message for message in progress if message.get("type") == "view.updated")
    room_state = next(message for message in progress if message.get("type") == "room.state")
    assert view["type"] == "view.updated"
    assert view["payload"]["playerView"]["scene"]["name"] == "托马斯的会客室"
    assert envelope["type"] == "narration.push"
    assert envelope["payload"]["messageId"] == "game-opening"
    assert "托马斯的会客室" in envelope["payload"]["text"]
    assert room_state["type"] == "room.state"
    assert room_state["payload"]["phase"] == "InGame"
    assert any(message.get("type") == "opening.started" for message in progress)
    assert any(message.get("type") == "view.updated" for message in retry_progress)
    assert any(message.get("type") == "room.state" for message in retry_progress)
    assert not any(
        message.get("type") in {"opening.started", "narration.push"} for message in retry_progress
    )

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "InGame"
    conversation = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/conversation",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    openings = [
        event
        for event in conversation
        if event["type"] == "narration.push" and event["payload"].get("messageId") == "game-opening"
    ]
    assert len(openings) == 1
    assert openings[0]["id"] == "game-opening"
    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    persisted_opening = next(
        event
        for event in replay
        if event["eventType"] == "narration.push"
        and event["payload"].get("messageId") == "game-opening"
    )
    assert persisted_opening["playerId"] is None
    assert persisted_opening["payload"] == envelope["payload"]


def test_invalid_opening_model_falls_back_after_room_enters_in_game(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "opening_fallback_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        replace(
            ws_controller.turn_application,
            opening_narration_model=_WsMissingParticipantOpening(),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        opening, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert opening["payload"]["messageId"] == "game-opening"
    assert "托马斯的会客室" in opening["payload"]["text"]
    assert "陈探员" in opening["payload"]["text"]
    room_state = next(message for message in progress if message.get("type") == "room.state")
    assert room_state["payload"]["phase"] == "InGame"


def test_game_start_rejects_non_host(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token, max_players=2)
    # 访客必须在 Lobby 阶段加入（join_room 只在这个阶段放行），所以先加入
    # 再推进到 Building，两人都建完卡后再让访客尝试 game.start。
    guest = join_as(sync_client, room["roomCode"], "guest_non_host")
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    complete_character(sync_client, room["roomId"], guest["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={guest['authToken']}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": guest["playerId"], "payload": {}})

        # 非房主发起 game.start 会被拒绝：收到一条 FORBIDDEN 的 error 事件
        # （issue #77 起明确告知发起者，不再像旧版那样静默忽略）；房间阶段
        # 维持 Building 不变，不会有 narration.push。
        envelope = ws.receive_json()

    assert envelope["type"] == "error"
    assert envelope["payload"]["code"] == "FORBIDDEN"
    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "Building"


def test_action_submit_broadcasts_narration_to_room_only(sync_client: TestClient) -> None:
    token_a = register_and_login(sync_client, "host_a")
    token_b = register_and_login(sync_client, "host_b")
    room_a = create_room(sync_client, token_a, max_players=2)
    room_b = create_room(sync_client, token_b)
    guest = join_as(sync_client, room_a["roomCode"], "guest_a")
    advance_to_building(sync_client, room_a)
    complete_character(sync_client, room_a["roomId"], room_a["reconnectToken"])
    complete_character(sync_client, room_a["roomId"], guest["reconnectToken"])
    start_game(sync_client, room_a, token_a)

    with (
        sync_client.websocket_connect(f"/ws/{room_a['roomId']}?token={token_a}") as ws_a,
        sync_client.websocket_connect(
            f"/ws/{room_a['roomId']}?token={guest['authToken']}"
        ) as ws_guest,
        sync_client.websocket_connect(f"/ws/{room_b['roomId']}?token={token_b}") as ws_b,
    ):
        ws_a.send_json(
            {
                "type": "room.join",
                "playerId": room_a["playerId"],
                "payload": {"reconnectToken": room_a["reconnectToken"]},
            }
        )
        ws_a.receive_json()  # session.bound
        ws_a.receive_json()  # current view.updated
        ws_guest.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        ws_guest.receive_json()  # session.bound
        ws_guest.receive_json()  # current view.updated
        ws_b.send_json(
            {
                "type": "room.join",
                "playerId": room_b["playerId"],
                "payload": {"reconnectToken": room_b["reconnectToken"]},
            }
        )
        ws_b.receive_json()  # session.bound

        ws_a.send_json(
            {
                "type": "action.submit",
                # 信封里的 playerId 不能切换身份，后端只使用已经绑定的 Player。
                "playerId": guest["playerId"],
                "payload": {
                    "clientActionId": "action-broadcast-122",
                    "utterance": "我看看托马斯",
                },
            }
        )
        completed, progress = receive_until(
            ws_a,
            lambda message: message.get("message_type") == "turn.completed",
        )
        action_echo = next(
            message for message in progress if message.get("type") == "action.broadcast"
        )
        narration, _ = receive_until(
            ws_a,
            lambda message: message.get("type") == "narration.push",
        )
        guest_narration, _ = receive_until(
            ws_guest,
            lambda message: message.get("type") == "narration.push",
        )

        # 同一个动作重试可以再次收到技术确认，但不能再次产生叙事广播。
        ws_a.send_json(
            {
                "type": "action.submit",
                "playerId": room_a["playerId"],
                "payload": {
                    "clientActionId": "action-broadcast-122",
                    "utterance": "我看看托马斯",
                },
            }
        )
        retried, _ = receive_until(
            ws_a,
            lambda message: message.get("message_type") == "turn.completed",
        )
        ws_a.send_json(
            {
                "type": "room.join",
                "playerId": room_a["playerId"],
                "payload": {"reconnectToken": room_a["reconnectToken"]},
            }
        )
        next_after_retry, _ = receive_until(
            ws_a,
            lambda message: message.get("type") == "session.bound",
        )
        # room_b 没有收到任何广播——发一条 room.join 触发一次同步交互，确认
        # 收到的仍然是它自己的 session.bound，而不是串过来的 narration。
        ws_b.send_json(
            {
                "type": "room.join",
                "playerId": room_b["playerId"],
                "payload": {"reconnectToken": room_b["reconnectToken"]},
            }
        )
        envelope_b = ws_b.receive_json()

    assert completed["protocol_version"] == "1"
    assert completed["message_type"] == "turn.completed"
    assert completed["correlation_id"] == "action-broadcast-122"
    assert completed["payload"]["player_id"] == room_a["playerId"]
    assert completed["payload"]["actor_id"] == "actor_1"
    assert action_echo["type"] == "action.broadcast"
    assert action_echo["payload"]["utterance"] == "我看看托马斯"
    assert narration["type"] == "narration.push"
    assert narration["payload"]["messageId"] == "action-broadcast-122"
    assert guest_narration == narration
    assert retried["message_type"] == "turn.completed"
    assert next_after_retry["type"] == "session.bound"
    assert envelope_b["type"] == "session.bound"
    for event in progress:
        rendered = str(event)
        assert "call_id" not in rendered
        assert "arguments" not in rendered
        assert "raw_output" not in rendered

    replay = sync_client.get(
        f"{ROOMS_BASE}/{room_a['roomId']}/replay",
        headers={"X-Reconnect-Token": room_a["reconnectToken"]},
    ).json()["data"]
    action_narrations = [
        event
        for event in replay
        if event["eventType"] == "narration.push"
        and event["payload"]["text"] == narration["payload"]["text"]
    ]
    assert len(action_narrations) == 1
    assert action_narrations[0]["payload"]["messageId"] == "action-broadcast-122"


def test_invalid_narration_fails_closed_then_original_request_recovers(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "narration_policy_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    narration_model = _WsInvalidTwiceThenSafeNarration()
    current_application = ws_controller.turn_application
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        build_turn_application(
            current_application.store,
            current_application.engine,
            intent_model=_WsPlainIntentModel(),
            narration_model=narration_model,
        ),
    )
    action = {
        "type": "action.submit",
        "playerId": room["playerId"],
        "payload": {
            "clientActionId": "ws-narration-invalid-167",
            "utterance": "我继续询问托马斯",
        },
    }

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        assert ws.receive_json()["type"] == "view.updated"

        ws.send_json(action)
        failed, first_attempt_events = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
        )

        assert failed["payload"]["code"] == "NARRATION_INVALID"
        assert failed["payload"]["retryable"] is True
        assert all(
            message.get("message_type") != "turn.completed"
            and message.get("type") not in {"view.updated", "narration.push"}
            for message in first_attempt_events
        )
        assert narration_model.leaked_text not in str(first_attempt_events)

        ws.send_json(
            {
                **action,
                "payload": {
                    **action["payload"],
                    "utterance": "我攻击托马斯",
                },
            }
        )
        conflict, conflict_events = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
        )

        assert conflict["payload"]["code"] == "ACTION_ID_CONFLICT"
        assert conflict["payload"]["retryable"] is False
        assert all(
            message.get("message_type") != "turn.completed"
            and message.get("type") not in {"check.request", "check.result", "narration.push"}
            for message in conflict_events
        )
        assert narration_model.calls == 2

        ws.send_json(action)
        completed, retry_events = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert completed["correlation_id"] == "ws-narration-invalid-167"
    assert all(message.get("type") != "turn.failed" for message in retry_events)
    assert narration_model.calls == 3
    assert narration["payload"]["text"] != narration_model.leaked_text

    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    narration_events = [
        event
        for event in replay
        if event["eventType"] == "narration.push"
        and event["payload"]["text"] == narration["payload"]["text"]
    ]
    assert len(narration_events) == 1
    assert narration_events[0]["payload"]["text"] == narration["payload"]["text"]
    assert narration_model.leaked_text not in str(replay)


def test_narration_newlines_are_normalized_before_turn_and_push(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "narration_newline_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    current_application = ws_controller.turn_application
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        build_turn_application(
            current_application.store,
            current_application.engine,
            intent_model=_WsPlainIntentModel(),
            narration_model=_WsEscapedNewlineNarration(),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        assert ws.receive_json()["type"] == "view.updated"
        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "ws-narration-newline-188",
                    "utterance": "我继续询问托马斯",
                },
            }
        )
        completed, _ = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    expected = "第一段\n第二段\n第三段"
    assert completed["payload"]["narration"]["text"] == expected
    assert narration["payload"]["text"] == expected
    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    persisted = [
        event
        for event in replay
        if event["eventType"] == "narration.push" and event["payload"]["text"] == expected
    ]
    assert len(persisted) == 1


def test_skill_check_waits_for_player_selection_and_roll(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "skill_check_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    current_application = ws_controller.turn_application
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        build_turn_application(
            current_application.store,
            current_application.engine,
            intent_model=_WsCandidateIntentModel(),
            narration_model=FakeNarrationModel(),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        assert ws.receive_json()["type"] == "view.updated"
        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "ws-skill-check-146",
                    "utterance": "尝试潜行查找资料",
                },
            }
        )
        request, prepare_events = receive_until(
            ws,
            lambda message: message.get("type") == "check.request",
        )
        ws.send_json(
            {
                "type": "check.roll",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "ws-skill-check-146",
                    "skill": "stealth",
                    "rollValue": 7,
                },
            }
        )
        result, complete_events = receive_until(
            ws,
            lambda message: message.get("type") == "check.result",
        )
        completed, _ = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert request["type"] == "check.request"
    assert request["payload"]["clientActionId"] == "ws-skill-check-146"
    assert [skill["id"] for skill in request["payload"]["skills"]] == [
        "library-use",
        "stealth",
    ]
    assert result["type"] == "check.result"
    assert result["payload"]["skill"] == "stealth"
    assert result["payload"]["rollValue"] == 7
    assert result["payload"]["characterName"] == "陈探员"
    assert completed["message_type"] == "turn.completed"
    assert completed["correlation_id"] == "ws-skill-check-146"
    assert narration["type"] == "narration.push"
    assert [event["type"] for event in prepare_events if "type" in event] == [
        "action.broadcast",
        "turn.started",
        "turn.phase_changed",
        "turn.phase_changed",
        "turn.phase_changed",
        "check.request",
    ]
    assert [event["type"] for event in complete_events if "type" in event] == [
        "turn.phase_changed",
        "check.result",
    ]


def test_invalid_check_narration_clears_pending_turn_and_reuses_completed_action(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "narration_check_retry_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    narration_model = _WsInvalidTwiceThenSafeNarration()
    current_application = ws_controller.turn_application
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        build_turn_application(
            current_application.store,
            current_application.engine,
            intent_model=_WsCandidateIntentModel(),
            narration_model=narration_model,
        ),
    )
    action = {
        "type": "action.submit",
        "playerId": room["playerId"],
        "payload": {
            "clientActionId": "ws-check-narration-invalid-167",
            "utterance": "尝试潜行查找资料",
        },
    }

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        assert ws.receive_json()["type"] == "view.updated"

        ws.send_json(action)
        request, _ = receive_until(
            ws,
            lambda message: message.get("type") == "check.request",
        )
        ws.send_json(
            {
                "type": "check.roll",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": request["payload"]["clientActionId"],
                    "skill": "stealth",
                    "rollValue": 7,
                },
            }
        )
        failed, failed_events = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
        )

        assert failed["payload"]["code"] == "NARRATION_INVALID"
        assert sum(message.get("type") == "check.result" for message in failed_events) == 1

        ws.send_json(action)
        completed, retry_events = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert completed["correlation_id"] == "ws-check-narration-invalid-167"
    assert all(message.get("type") != "check.request" for message in retry_events)
    assert all(message.get("type") != "check.result" for message in retry_events)
    assert narration_model.calls == 3
    assert narration["payload"]["text"] != narration_model.leaked_text

    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    check_results = [
        event
        for event in replay
        if event["eventType"] == "check.result"
        and event["payload"]["clientActionId"] == "ws-check-narration-invalid-167"
    ]
    assert len(check_results) == 1
    assert narration_model.leaked_text not in str(replay)


def test_terminal_attack_check_failure_releases_pending_turn(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "terminal_attack_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    current_application = ws_controller.turn_application
    monkeypatch.setattr(
        ws_controller,
        "turn_application",
        build_turn_application(
            current_application.store,
            current_application.engine,
            intent_model=_WsAttackThenPlainIntentModel(),
            narration_model=FakeNarrationModel(),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        assert ws.receive_json()["type"] == "view.updated"

        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "attack-thomas-153",
                    "utterance": "我想打一顿托马斯",
                },
            }
        )
        request, _ = receive_until(
            ws,
            lambda message: message.get("type") == "check.request",
        )
        assert request["payload"]["clientActionId"] == "attack-thomas-153"

        ws.send_json(
            {
                "type": "check.roll",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "attack-thomas-153",
                    "skill": "fighting-brawl",
                    "rollValue": 1,
                },
            }
        )
        check_result, _ = receive_until(
            ws,
            lambda message: message.get("type") == "check.result",
        )
        assert check_result["payload"]["clientActionId"] == "attack-thomas-153"
        assert check_result["payload"]["characterName"] == "陈探员"
        completed, _ = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        assert completed["correlation_id"] == "attack-thomas-153"
        blocked_narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )
        assert "战斗数据" in blocked_narration["payload"]["text"]
        assert "契约校验" not in blocked_narration["payload"]["text"]

        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "after-attack-153",
                    "utterance": "我继续和托马斯交谈",
                },
            }
        )
        next_turn, _ = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
        )

    assert next_turn["correlation_id"] == "after-attack-153"


def test_action_submit_requires_client_action_id_without_closing_socket(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client, "missing_action_id")
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {"utterance": "缺少幂等键"},
            }
        )
        error = ws.receive_json()
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        rebound = ws.receive_json()

    assert error["type"] == "error"
    assert error["payload"]["code"] == "INVALID_ACTION"
    assert rebound["type"] == "session.bound"


def test_clarification_is_sent_only_to_action_owner(sync_client: TestClient) -> None:
    host_token = register_and_login(sync_client, "clarification_host")
    room = create_room(sync_client, host_token, max_players=2)
    guest = join_as(sync_client, room["roomCode"], "clarification_guest")
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    complete_character(sync_client, room["roomId"], guest["reconnectToken"])
    start_game(sync_client, room, host_token)

    with (
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={host_token}") as host_ws,
        sync_client.websocket_connect(
            f"/ws/{room['roomId']}?token={guest['authToken']}"
        ) as guest_ws,
    ):
        host_ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        host_ws.receive_json()
        host_ws.receive_json()
        guest_ws.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        guest_ws.receive_json()
        guest_ws.receive_json()

        host_ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "clarification-122",
                    "utterance": "我想做点什么",
                },
            }
        )
        completed, _ = receive_until(
            host_ws,
            lambda message: message.get("message_type") == "turn.completed",
        )
        clarification, _ = receive_until(
            host_ws,
            lambda message: message.get("type") == "narration.push",
        )

        guest_ws.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        guest_next, _ = receive_until(
            guest_ws,
            lambda message: message.get("type") == "session.bound",
        )

    assert completed["payload"]["narration"]["kind"] == "clarification"
    assert clarification["type"] == "narration.push"
    assert guest_next["type"] == "session.bound"


def test_action_submit_maps_suspended_room_error(sync_client: TestClient) -> None:
    token = register_and_login(sync_client, "suspended_action")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    suspended = sync_client.post(
        f"{ROOMS_BASE}/{room['roomId']}/suspend",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    assert suspended.status_code == 200

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.receive_json()
        ws.send_json(
            {
                "type": "action.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "suspended-122",
                    "utterance": "我看看旧书店",
                },
            }
        )
        error, _ = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
        )

    assert error["type"] == "turn.failed"
    assert error["payload"] == {
        "code": "ROOM_NOT_ACTIONABLE",
        "correlationId": "suspended-122",
        "publicMessage": "房间当前状态不允许提交动作",
        "retryable": False,
    }


def test_turn_error_reason_keeps_contract_error_message_bounded() -> None:
    reason = ws_controller._turn_error_reason(
        ContractError("checkpoint 不在可信候选中\nwith extra whitespace")
    )

    assert reason == "checkpoint 不在可信候选中 with extra whitespace"
    assert "\n" not in reason
