from httpx import AsyncClient

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
    # 私家侦探（occupation id=16）的两项职业技能，用真实技能 id 键控、分配在
    # 职业技能点预算内（EDU*2+STR*2=80*2+50*2=260）——issue #84 S2 起
    # complete 会用 coc7_rules 权威校验，键必须是技能表里的 id 不是技能名。
    # credit-rating（信用评级，PR #85 review #4 新增为一条真正的技能）落在
    # 私家侦探信用区间 [9,40] 内，否则 complete 会被 CREDIT_OUT_OF_RANGE 拒。
    "skills": {"law": 55, "spot-hidden": 75, "credit-rating": 25},
    "equipment": [{"name": "左轮手枪"}, {"name": "手电筒"}],
    "occupation": "私家侦探",
    "background": "曾是警察",
    "notes": "",
}


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


async def test_complete_character_rejects_invalid_card(client: AsyncClient) -> None:
    """issue #84 S2：complete 前用 coc7_rules 权威校验，非法卡（这里让职业
    技能点花费远超预算）直接被拒，返回结构化校验报告，而不是被静默放行。"""
    room = await create_room(client)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]

    invalid_character = {
        **BUILT_CHARACTER,
        # 私家侦探的全部 8 项职业技能都拉满到上限 99，总花费（>600）远超
        # 职业预算 260 + 兴趣预算 140 = 400 的总预算，应该触发
        # OCCUPATION_POINTS_EXCEEDED。
        "skills": {
            "disguise": 99,
            "drive-auto": 99,
            "fighting-brawl": 99,
            "fast-talk": 99,
            "law": 99,
            "listen": 99,
            "persuade": 99,
            "spot-hidden": 99,
        },
    }
    saved = await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=invalid_character,
        headers=auth(room["reconnectToken"]),
    )
    assert saved.status_code == 200

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
        headers=auth(room["reconnectToken"]),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CHARACTER_INVALID"
    codes = [issue["code"] for issue in body["error"]["details"]]
    assert "OCCUPATION_POINTS_EXCEEDED" in codes
