import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.service import auth as auth_service
from app.service import room as room_service

ROOMS_BASE = "/api/v1/rooms"


@pytest.fixture(autouse=True)
def clear_stubs() -> None:
    room_service._rooms.clear()
    room_service._players.clear()
    room_service._characters.clear()
    auth_service._users.clear()
    auth_service._accounts.clear()
    auth_service._tokens.clear()


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


def create_room(client: TestClient) -> dict:
    response = client.post(
        ROOMS_BASE, json={"roomName": "WS测试房间", "nickname": "房主", "maxPlayers": 4}
    )
    assert response.status_code == 200
    return response.json()["data"]


def complete_character(client: TestClient, room_id: str, reconnect_token: str) -> None:
    headers = {"X-Reconnect-Token": reconnect_token}
    draft = client.post(f"{ROOMS_BASE}/{room_id}/characters", headers=headers)
    character_id = draft.json()["data"]["characterId"]
    client.patch(
        f"{ROOMS_BASE}/{room_id}/characters/{character_id}",
        json={
            "name": "陈探员",
            "attributes": {"STR": 50},
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
    module_id = client.get("/api/v1/modules").json()["data"][0]["id"]
    client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room['roomId']}/start-story", headers=headers)


def test_connect_without_token_is_rejected(sync_client: TestClient) -> None:
    room = create_room(sync_client)

    with pytest.raises(WebSocketDisconnect), sync_client.websocket_connect(f"/ws/{room['roomId']}"):
        pass


def test_room_join_binds_session(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"roomCode": room["roomCode"], "nickname": "房主"},
            }
        )
        envelope = ws.receive_json()

    assert envelope == {
        "type": "session.bound",
        "payload": {"roomId": room["roomId"], "playerId": room["playerId"]},
    }


def test_room_join_with_unknown_player_closes_connection(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client)

    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws,
    ):
        ws.send_json({"type": "room.join", "playerId": "not-a-real-player", "payload": {}})
        ws.receive_json()


def test_player_ready_updates_room_state(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json({"type": "room.join", "playerId": room["playerId"], "payload": {}})
        ws.receive_json()  # session.bound
        ws.send_json(
            {"type": "player.ready", "playerId": room["playerId"], "payload": {"ready": True}}
        )

        # 让服务端处理完 player.ready 再去查——最简单的办法是紧接着发一条
        # room.join 强制走一次同步的事件处理再返回。
        ws.send_json({"type": "room.join", "playerId": room["playerId"], "payload": {}})
        ws.receive_json()

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["players"][0]["ready"] is True


def test_game_start_pushes_opening_narration_and_advances_phase(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json({"type": "room.join", "playerId": room["playerId"], "payload": {}})
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        envelope = ws.receive_json()

    assert envelope["type"] == "narration.push"
    assert envelope["payload"]["text"]

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "InGame"


def test_game_start_rejects_non_host(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client)
    # 访客必须在 Lobby 阶段加入（join_room 只在这个阶段放行），所以先加入
    # 再推进到 Building，两人都建完卡后再让访客尝试 game.start。
    guest = sync_client.post(
        f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "访客"}
    ).json()["data"]
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    complete_character(sync_client, room["roomId"], guest["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json({"type": "room.join", "playerId": guest["playerId"], "payload": {}})
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": guest["playerId"], "payload": {}})

        # 非房主发起 game.start 会被静默拒绝，不会有 narration.push；房间
        # 阶段应该维持 Building 不变。
        ws.send_json({"type": "room.join", "playerId": guest["playerId"], "payload": {}})
        envelope = ws.receive_json()

    assert envelope["type"] == "session.bound"
    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "Building"


def test_action_submit_broadcasts_narration_to_room_only(sync_client: TestClient) -> None:
    token_a = register_and_login(sync_client, "host_a")
    token_b = register_and_login(sync_client, "host_b")
    room_a = create_room(sync_client)
    room_b = create_room(sync_client)

    with (
        sync_client.websocket_connect(f"/ws/{room_a['roomId']}?token={token_a}") as ws_a,
        sync_client.websocket_connect(f"/ws/{room_b['roomId']}?token={token_b}") as ws_b,
    ):
        ws_a.send_json({"type": "room.join", "playerId": room_a["playerId"], "payload": {}})
        ws_a.receive_json()  # session.bound
        ws_b.send_json({"type": "room.join", "playerId": room_b["playerId"], "payload": {}})
        ws_b.receive_json()  # session.bound

        ws_a.send_json(
            {
                "type": "action.submit",
                "playerId": room_a["playerId"],
                "payload": {"utterance": "检查门锁"},
            }
        )
        narration = ws_a.receive_json()

        # room_b 没有收到任何广播——发一条 room.join 触发一次同步交互，确认
        # 收到的仍然是它自己的 session.bound，而不是串过来的 narration。
        ws_b.send_json({"type": "room.join", "playerId": room_b["playerId"], "payload": {}})
        envelope_b = ws_b.receive_json()

    assert narration["type"] == "narration.push"
    assert "检查门锁" in narration["payload"]["text"]
    assert envelope_b["type"] == "session.bound"
