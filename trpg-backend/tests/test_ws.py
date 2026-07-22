import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

ROOMS_BASE = "/api/v1/rooms"


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


def create_room(client: TestClient, token: str) -> dict:
    """建房（issue #106 起要求登录，房间会关联到这个账号）。"""
    response = client.post(
        ROOMS_BASE,
        json={"roomName": "WS测试房间", "nickname": "房主", "maxPlayers": 4},
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
    return response.json()["data"]


def complete_character(client: TestClient, room_id: str, reconnect_token: str) -> None:
    headers = {"X-Reconnect-Token": reconnect_token}
    draft = client.post(f"{ROOMS_BASE}/{room_id}/characters", headers=headers)
    character_id = draft.json()["data"]["characterId"]
    client.patch(
        f"{ROOMS_BASE}/{room_id}/characters/{character_id}",
        json={
            "name": "陈探员",
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
    module_id = client.get("/api/v1/modules").json()["data"][0]["id"]
    client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room['roomId']}/start-story", headers=headers)


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
        envelope = ws.receive_json()

    assert envelope["type"] == "narration.push"
    assert envelope["payload"]["text"]

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "InGame"


def test_game_start_rejects_non_host(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)
    # 访客必须在 Lobby 阶段加入（join_room 只在这个阶段放行），所以先加入
    # 再推进到 Building，两人都建完卡后再让访客尝试 game.start。
    guest = join_as(sync_client, room["roomCode"], "guest_non_host")
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    complete_character(sync_client, room["roomId"], guest["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
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
    room_a = create_room(sync_client, token_a)
    room_b = create_room(sync_client, token_b)

    with (
        sync_client.websocket_connect(f"/ws/{room_a['roomId']}?token={token_a}") as ws_a,
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
                "playerId": room_a["playerId"],
                "payload": {"utterance": "检查门锁"},
            }
        )
        narration = ws_a.receive_json()

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

    assert narration["type"] == "narration.push"
    assert "检查门锁" in narration["payload"]["text"]
    assert envelope_b["type"] == "session.bound"
