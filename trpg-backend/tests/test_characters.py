import pytest
from httpx import AsyncClient

from app.service import room as room_service

ROOMS_BASE = "/api/v1/rooms"

BUILT_CHARACTER = {
    "name": "陈探员",
    "attributes": {
        "STR": 50,
        "CON": 60,
        "POW": 55,
        "DEX": 45,
        "APP": 50,
        "SIZ": 60,
        "INT": 70,
        "EDU": 80,
    },
    "derivedStats": {"HP": 12, "SAN": 55, "MP": 11},
    "skills": {"图书馆使用": 70, "侦查": 60},
    "equipment": [{"name": "左轮手枪"}, {"name": "手电筒"}],
    "occupation": "私家侦探",
    "background": "曾是警察",
    "notes": "",
}


@pytest.fixture(autouse=True)
def clear_room_stub() -> None:
    room_service._rooms.clear()
    room_service._players.clear()
    room_service._characters.clear()


async def create_room(client: AsyncClient) -> dict:
    response = await client.post(
        ROOMS_BASE, json={"roomName": "测试房间", "nickname": "房主", "maxPlayers": 4}
    )
    assert response.status_code == 200
    return response.json()["data"]


def auth(token: str) -> dict[str, str]:
    return {"X-Reconnect-Token": token}


async def test_full_character_build_flow_marks_player_ready(client: AsyncClient) -> None:
    room = await create_room(client)

    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    assert draft.status_code == 201
    character_id = draft.json()["data"]["characterId"]
    assert draft.json()["data"]["status"] == "draft"

    saved = await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=BUILT_CHARACTER,
        headers=auth(room["reconnectToken"]),
    )
    assert saved.status_code == 200

    completed = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
        headers=auth(room["reconnectToken"]),
    )
    assert completed.status_code == 200

    preview = await client.get(f"{ROOMS_BASE}/{room['roomCode']}")
    host = next(p for p in preview.json()["data"]["players"] if p["isHost"])
    assert host["hasCharacter"] is True


async def test_create_character_requires_token(client: AsyncClient) -> None:
    room = await create_room(client)

    response = await client.post(f"{ROOMS_BASE}/{room['roomId']}/characters")

    assert response.status_code == 401


async def test_cannot_edit_another_players_character(client: AsyncClient) -> None:
    room = await create_room(client)
    joined = (
        await client.post(f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "玩家"})
    ).json()["data"]
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]

    response = await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=BUILT_CHARACTER,
        headers=auth(joined["reconnectToken"]),
    )

    assert response.status_code == 403


async def test_character_not_found_returns_404(client: AsyncClient) -> None:
    room = await create_room(client)

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/missing/complete",
        headers=auth(room["reconnectToken"]),
    )

    assert response.status_code == 404
