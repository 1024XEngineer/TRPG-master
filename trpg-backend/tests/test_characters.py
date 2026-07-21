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
        "LUCK": 50,
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


# ── 角色卡读回：后端是唯一事实来源（issue #96）─────────────────────────


async def test_get_character_reads_back_saved_card(client: AsyncClient) -> None:
    """保存后能从后端把角色卡读回来。

    补这个端点是为了让客户端不必再把角色卡存进 localStorage 当权威源——
    那份本地副本的结构会随后端 schema 演进而过期（PR #88 加幸运后，本地存的
    8 键旧卡就再也编辑不了了）。
    """
    room = await create_room(client)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]
    await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=BUILT_CHARACTER,
        headers=auth(room["reconnectToken"]),
    )

    response = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=auth(room["reconnectToken"]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == character_id
    assert data["name"] == BUILT_CHARACTER["name"]
    assert data["attributes"] == BUILT_CHARACTER["attributes"]
    assert data["occupation"] == BUILT_CHARACTER["occupation"]
    # 默认是点数购买法——迁移前建的卡和前端建卡向导走的都是这条路径
    assert data["generationMethod"] == "pointbuy"


async def test_roll_attributes_marks_card_as_rolled(client: AsyncClient) -> None:
    """服务端权威掷骰后，这张卡要被标记成 roll。

    complete 时据此跳过点数购买法的总预算校验——掷骰结果 8 项总和均值约 457、
    范围 195–720，拿 480 的预算去卡它会把合法的卡判成非法。
    """
    room = await create_room(client)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]

    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/roll-attributes",
        headers=auth(room["reconnectToken"]),
    )

    read_back = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=auth(room["reconnectToken"]),
    )
    assert read_back.json()["data"]["generationMethod"] == "roll"


async def test_replacing_rolled_attributes_falls_back_to_point_buy(client: AsyncClient) -> None:
    """🔴 掷完骰再自己重填属性，来源标记必须退回点数购买法（PR #97 review [1]）。

    `roll` 这个标记的意义是「这组属性是服务端掷出来的」，据此跳过 480 点预算
    校验。但 PATCH 接受客户端任意属性——标记原样留着的话，先掷一次、再把 8 项
    全顶到单项上限 90（8 项共 720 点、远超 480）提交，complete 就会走 roll
    分支放行。用 90 而不是 99 是为了精确命中预算这条校验——99 会先被单项
    区间 [10, 90] 拦下，测出来的就不是预算有没有生效了。
    """
    room = await create_room(client)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/roll-attributes",
        headers=auth(room["reconnectToken"]),
    )

    maxed = {
        **BUILT_CHARACTER,
        # 幸运不参与点数购买，保持原值；其余 8 项顶到单项上限。
        "attributes": {key: (50 if key == "LUCK" else 90) for key in BUILT_CHARACTER["attributes"]},
    }
    await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=maxed,
        headers=auth(room["reconnectToken"]),
    )

    read_back = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=auth(room["reconnectToken"]),
    )
    assert read_back.json()["data"]["generationMethod"] == "pointbuy"

    completed = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
        headers=auth(room["reconnectToken"]),
    )
    assert completed.status_code == 422
    codes = [issue["code"] for issue in completed.json()["error"]["details"]]
    assert "ATTRIBUTE_POINTS_EXCEEDED" in codes


async def test_saving_a_rolled_card_unchanged_keeps_roll_method(client: AsyncClient) -> None:
    """上一条的对照：属性原样存回去时，`roll` 必须保住。

    建卡向导的 PATCH 是整卡保存，掷骰法那条路径也要走它把姓名/技能存下来。
    若一见到 PATCH 就退回 pointbuy，掷出来总和超 480 的合法卡会被判非法——
    等于废掉 roll-attributes。只测上一条会漏掉这个方向。
    """
    room = await create_room(client)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]
    rolled = (
        await client.post(
            f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/roll-attributes",
            headers=auth(room["reconnectToken"]),
        )
    ).json()["data"]["attributes"]

    await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json={**BUILT_CHARACTER, "attributes": rolled},
        headers=auth(room["reconnectToken"]),
    )

    read_back = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=auth(room["reconnectToken"]),
    )
    assert read_back.json()["data"]["generationMethod"] == "roll"


async def test_cannot_read_another_players_character(client: AsyncClient) -> None:
    """角色卡里有背景故事/装备这类属于该玩家的信息，别人不能直接拉。"""
    room = await create_room(client)
    joined = (
        await client.post(f"{ROOMS_BASE}/{room['roomCode']}/join", json={"nickname": "玩家"})
    ).json()["data"]
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters", headers=auth(room["reconnectToken"])
    )
    character_id = draft.json()["data"]["characterId"]

    response = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=auth(joined["reconnectToken"]),
    )

    assert response.status_code == 403
