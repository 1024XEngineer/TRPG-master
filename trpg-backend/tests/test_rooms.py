from httpx import AsyncClient

ROOMS_BASE = "/api/v1/rooms"


async def create_room(client: AsyncClient, max_players: int = 4) -> dict:
    response = await client.post(
        ROOMS_BASE,
        json={"roomName": "测试房间", "nickname": "房主", "maxPlayers": max_players},
    )
    assert response.status_code == 200
    return response.json()["data"]


def auth(token: str) -> dict[str, str]:
    return {"X-Reconnect-Token": token}


async def test_join_rejects_full_room(client: AsyncClient) -> None:
    room = await create_room(client, max_players=1)

    response = await client.post(f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "玩家"})

    assert response.status_code == 409
    # 满房间返回更具体的 ROOM_FULL（issue #77 新增的业务错误码），不再是泛化的 CONFLICT。
    assert response.json()["error"]["code"] == "ROOM_FULL"


async def test_join_rejects_room_after_story_starts(client: AsyncClient) -> None:
    room = await create_room(client)
    module_id = (await client.get("/api/v1/modules")).json()["data"][0]["id"]
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=auth(room["reconnectToken"]),
    )
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/start-story",
        json=None,
        headers=auth(room["reconnectToken"]),
    )

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "迟到玩家"}
    )

    assert response.status_code == 409


async def test_host_operations_require_host_token(client: AsyncClient) -> None:
    room = await create_room(client)
    joined = (
        await client.post(f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "玩家"})
    ).json()["data"]
    module_id = (await client.get("/api/v1/modules")).json()["data"][0]["id"]

    missing = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
    )
    non_host = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=auth(joined["reconnectToken"]),
    )

    assert missing.status_code == 401
    assert non_host.status_code == 403


async def test_select_module_validates_room_and_module(client: AsyncClient) -> None:
    room = await create_room(client)

    missing_room = await client.post(
        f"{ROOMS_BASE}/missing/module",
        json={"moduleId": "missing", "attributeGenMethod": "point_buy"},
        headers=auth(room["reconnectToken"]),
    )
    missing_module = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": "missing", "attributeGenMethod": "point_buy"},
        headers=auth(room["reconnectToken"]),
    )

    assert missing_room.status_code == 404
    assert missing_module.status_code == 404


async def test_list_my_rooms_filters_by_token(client: AsyncClient) -> None:
    first = await create_room(client)
    await create_room(client)

    response = await client.get("/api/v1/me/rooms", headers=auth(first["reconnectToken"]))

    assert response.status_code == 200
    rooms = response.json()["data"]
    assert [room["roomId"] for room in rooms] == [first["roomId"]]


async def test_room_text_fields_reject_whitespace(client: AsyncClient) -> None:
    response = await client.post(
        ROOMS_BASE,
        json={"roomName": "   ", "nickname": "房主", "maxPlayers": 4},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_replay_requires_room_member_token(client: AsyncClient) -> None:
    """回放是"只有参与者能看"的内容——没有有效的房间成员凭证不能拉（PR #78 review）。"""
    room = await create_room(client)
    room_id = room["roomId"]

    # 无凭证 → 401
    no_token = await client.get(f"{ROOMS_BASE}/{room_id}/replay")
    assert no_token.status_code == 401

    # 别的房间的成员凭证 → 403（凭证有效但不是这个房间的成员）
    other = await create_room(client)
    wrong_room = await client.get(
        f"{ROOMS_BASE}/{room_id}/replay", headers=auth(other["reconnectToken"])
    )
    assert wrong_room.status_code == 403

    # 本房间成员凭证 → 200
    ok = await client.get(f"{ROOMS_BASE}/{room_id}/replay", headers=auth(room["reconnectToken"]))
    assert ok.status_code == 200
    assert ok.json()["data"] == []
