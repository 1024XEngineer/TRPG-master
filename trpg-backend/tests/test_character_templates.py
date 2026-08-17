"""我的角色卡库（#337）。

卡库卡是玩家自己的第一等资产，房间角色卡是它的一份拷贝。这个方向决定了这里
每一条断言：卡库能独立于房间存在、删卡不会被历史房间卡拖住、拷贝之后两边互不
影响。
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import BUILTIN_GAME_ID, BUILTIN_SYSTEM_ID
from app.models.content import GameSystem
from app.models.room import Character
from app.models.user import UserCharacterTemplate
from tests.helpers import ROOMS_BASE, bearer, create_room, register

TEMPLATES_BASE = "/api/v1/me/character-templates"
# 另一个真实存在的规则系统。`user_character_templates.system_id` 是指向
# `game_systems` 的外键——SQLite 关着外键约束，随便编个 UUID 也能落库，但
# PostgreSQL 上那是 commit 时的 IntegrityError。用例要建真行，不能编 id。
OTHER_SYSTEM_ID = "00000000-0000-0000-0000-0000000000fd"


async def _ensure_other_system(db_session: AsyncSession) -> str:
    if await db_session.get(GameSystem, OTHER_SYSTEM_ID) is None:
        db_session.add(
            GameSystem(
                id=OTHER_SYSTEM_ID,
                game_id=BUILTIN_GAME_ID,
                world_ref="test-other-system",
                name="另一个规则系统",
                ruleset=None,
            )
        )
        await db_session.commit()
    return OTHER_SYSTEM_ID


TEMPLATE_ATTRIBUTES: dict[str, int] = {
    "STR": 50,
    "CON": 60,
    "POW": 55,
    "DEX": 45,
    "APP": 50,
    "SIZ": 60,
    "INT": 70,
    "EDU": 80,
    "LUCK": 50,
}

TEMPLATE_DATA = {
    "generation_method": "pointbuy",
    "name": "陈探员",
    "age": 32,
    "gender": "男",
    "residence": "阿卡姆",
    "birthplace": "波士顿",
    "attributes": TEMPLATE_ATTRIBUTES,
    "skills": {"law": 55, "spot-hidden": 75, "credit-rating": 25},
    "occupation_choice_skill_ids": None,
    "equipment": ["左轮手枪"],
    "occupation": "私家侦探",
    "background": "曾是警察",
    "notes": "",
}


async def _create_template(
    client: AsyncClient, token: str, *, name: str = "陈探员", system_id: str = BUILTIN_SYSTEM_ID
) -> dict:
    response = await client.post(
        TEMPLATES_BASE,
        json={"name": name, "systemId": system_id, "data": TEMPLATE_DATA},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_card_library_round_trip_without_any_room(client: AsyncClient) -> None:
    """建卡库卡、列出、改名、删除，全程不碰任何房间。

    这正是「卡库是第一等实体」的意思：#337 之前这四个端点全是 501 桩，卡库只能
    作为完成建卡的副产品出现。
    """
    token = await register(client)

    created = await _create_template(client, token)
    assert created["name"] == "陈探员"
    assert created["data"]["occupation"] == "私家侦探"

    listed = await client.get(TEMPLATES_BASE, headers=bearer(token))
    assert listed.status_code == 200
    assert [item["templateId"] for item in listed.json()["data"]] == [created["templateId"]]

    renamed = await client.patch(
        f"{TEMPLATES_BASE}/{created['templateId']}",
        json={"name": "陈探员（二版）"},
        headers=bearer(token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "陈探员（二版）"
    # 只传 name 时 data 必须原样留着，不能被当成"没传即清空"。
    assert renamed.json()["data"]["data"]["attributes"] == TEMPLATE_ATTRIBUTES

    deleted = await client.delete(
        f"{TEMPLATES_BASE}/{created['templateId']}", headers=bearer(token)
    )
    assert deleted.status_code == 200
    assert (await client.get(TEMPLATES_BASE, headers=bearer(token))).json()["data"] == []


async def test_updating_data_replaces_it_instead_of_merging(client: AsyncClient) -> None:
    """`data` 是整体覆盖：合并语义下前端删掉一项技能就永远删不掉。"""
    token = await register(client)
    created = await _create_template(client, token)

    trimmed = {**TEMPLATE_DATA, "skills": {"law": 55}}
    updated = await client.patch(
        f"{TEMPLATES_BASE}/{created['templateId']}",
        json={"data": trimmed},
        headers=bearer(token),
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["data"]["skills"] == {"law": 55}


async def test_another_players_template_is_indistinguishable_from_a_missing_one(
    client: AsyncClient,
) -> None:
    """别人的卡和不存在的卡返回同一个 404，否则试一遍就能问出「这张卡存在」。"""
    owner_token = await register(client)
    other_token = await register(client)
    created = await _create_template(client, owner_token)

    for method in ("get", "delete"):
        response = await getattr(client, method)(
            f"{TEMPLATES_BASE}/{created['templateId']}", headers=bearer(other_token)
        )
        assert response.status_code == 404, response.text
    patched = await client.patch(
        f"{TEMPLATES_BASE}/{created['templateId']}",
        json={"name": "抢过来"},
        headers=bearer(other_token),
    )
    assert patched.status_code == 404

    missing = await client.get(
        f"{TEMPLATES_BASE}/00000000-0000-0000-0000-0000000000ff",
        headers=bearer(other_token),
    )
    assert missing.status_code == 404
    # 别人的卡没有被动过。
    still_there = await client.get(
        f"{TEMPLATES_BASE}/{created['templateId']}", headers=bearer(owner_token)
    )
    assert still_there.status_code == 200
    assert still_there.json()["data"]["name"] == "陈探员"


async def test_list_can_be_filtered_by_system(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await register(client)
    other_system_id = await _ensure_other_system(db_session)
    coc = await _create_template(client, token, name="COC 卡")
    other = await _create_template(client, token, name="别的系统的卡", system_id=other_system_id)

    filtered = await client.get(
        TEMPLATES_BASE, params={"systemId": BUILTIN_SYSTEM_ID}, headers=bearer(token)
    )

    assert [item["templateId"] for item in filtered.json()["data"]] == [coc["templateId"]]
    unfiltered = await client.get(TEMPLATES_BASE, headers=bearer(token))
    assert {item["templateId"] for item in unfiltered.json()["data"]} == {
        coc["templateId"],
        other["templateId"],
    }


async def test_seeding_a_room_draft_copies_the_card_and_then_stands_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """从卡库播种房间草稿，之后两边互不影响。"""
    token = await register(client)
    template = await _create_template(client, token)
    room = await create_room(client, token=token)

    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template["templateId"]},
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    assert draft.status_code == 201, draft.text
    character_id = draft.json()["data"]["characterId"]

    read = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    body = read.json()["data"]
    assert body["name"] == "陈探员"
    assert body["attributes"] == TEMPLATE_ATTRIBUTES
    assert body["skills"] == TEMPLATE_DATA["skills"]
    assert body["occupation"] == "私家侦探"
    # 局内状态不跟着卡库走：衍生值等 complete 时服务端按属性权威重算。
    assert body["derivedStats"] == {}

    # 改卡库卡不会回头影响已经播种出去的房间卡。
    await client.patch(
        f"{TEMPLATES_BASE}/{template['templateId']}",
        json={"data": {**TEMPLATE_DATA, "name": "改过的名字"}},
        headers=bearer(token),
    )
    db_session.expire_all()
    stored = await db_session.get(Character, character_id)
    assert stored is not None
    assert stored.name == "陈探员"
    assert stored.based_on_template_id == template["templateId"]


async def test_deleting_a_referenced_card_clears_provenance_instead_of_failing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """删掉被房间卡引用过的卡库卡：房间卡留着，只是出处被置空。

    置空是 service 层显式做的，不是靠数据库的 `ON DELETE SET NULL`——本地和测试
    跑的 SQLite `PRAGMA foreign_keys = 0`，外键根本不生效；线上 PostgreSQL 上这个
    FK 又是 `NO ACTION`。交给数据库的话，这条保证在测试里永远不会被执行到。
    """
    token = await register(client)
    template = await _create_template(client, token)
    room = await create_room(client, token=token)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template["templateId"]},
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    character_id = draft.json()["data"]["characterId"]

    deleted = await client.delete(
        f"{TEMPLATES_BASE}/{template['templateId']}", headers=bearer(token)
    )

    assert deleted.status_code == 200
    db_session.expire_all()
    assert await db_session.scalar(select(func.count()).select_from(UserCharacterTemplate)) == 0
    stored = await db_session.get(Character, character_id)
    assert stored is not None
    assert stored.based_on_template_id is None
    # 房间卡自己的数据一点没少。
    assert stored.name == "陈探员"
    assert stored.attributes == TEMPLATE_ATTRIBUTES


async def test_seeding_refuses_a_card_from_another_rule_system(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await register(client)
    other_system_id = await _ensure_other_system(db_session)
    template = await _create_template(client, token, system_id=other_system_id)
    room = await create_room(client, token=token)

    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template["templateId"]},
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )

    assert draft.status_code == 409, draft.text


async def test_seeding_refuses_someone_elses_card(client: AsyncClient) -> None:
    owner_token = await register(client)
    template = await _create_template(client, owner_token)
    thief_token = await register(client)
    room = await create_room(client, token=thief_token)

    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template["templateId"]},
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )

    assert draft.status_code == 404, draft.text


async def test_room_scoped_building_still_works_without_a_template(client: AsyncClient) -> None:
    """不带 basedOnTemplateId 的从零建卡完全不受影响。"""
    room = await create_room(client)

    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )

    assert draft.status_code == 201
    assert draft.json()["data"]["status"] == "draft"


async def test_rolling_and_generating_need_no_room(client: AsyncClient) -> None:
    """无房间建卡链路：掷属性和一键生成都挂在卡库卡下面，服务端直接写进那张卡。"""
    token = await register(client)
    template = await _create_template(client, token)
    template_id = template["templateId"]

    rolled = await client.post(
        f"{TEMPLATES_BASE}/{template_id}/roll-attributes", headers=bearer(token)
    )
    assert rolled.status_code == 200, rolled.text
    attributes = rolled.json()["data"]["attributes"]
    assert set(attributes) == {"STR", "CON", "DEX", "APP", "POW", "SIZ", "INT", "EDU", "LUCK"}
    assert all(15 <= value <= 90 for value in attributes.values())

    stored = await client.get(f"{TEMPLATES_BASE}/{template_id}", headers=bearer(token))
    assert stored.json()["data"]["data"]["attributes"] == attributes
    assert stored.json()["data"]["data"]["generation_method"] == "roll"

    generated = await client.post(
        f"{TEMPLATES_BASE}/{template_id}/quick-generate",
        json={"name": "叶探员"},
        headers=bearer(token),
    )
    assert generated.status_code == 200, generated.text
    data = generated.json()["data"]["data"]
    assert data["name"] == "叶探员"
    assert data["attributes"] and data["occupation"]
    reread = await client.get(f"{TEMPLATES_BASE}/{template_id}", headers=bearer(token))
    assert reread.json()["data"]["data"]["name"] == "叶探员"


async def test_a_client_cannot_claim_its_attributes_were_rolled(client: AsyncClient) -> None:
    """自查抓到的洞：`generation_method` 是跳过点数预算校验的开关，不能由客户端声明。

    改之前 `data` 是客户端全权写入的，只要写上 `roll` 再播种进房间，8 项全 90 的卡
    也能 complete 成功——因为 roll 本来就允许超 480 总预算（掷骰经常超）。
    """
    token = await register(client)
    maxed = {
        **TEMPLATE_DATA,
        "generation_method": "roll",
        "attributes": dict.fromkeys(TEMPLATE_ATTRIBUTES, 90),
    }

    created = await client.post(
        TEMPLATES_BASE,
        json={"name": "满属性", "systemId": BUILTIN_SYSTEM_ID, "data": maxed},
        headers=bearer(token),
    )
    assert created.status_code == 201
    assert created.json()["data"]["data"]["generation_method"] == "pointbuy"
    template_id = created.json()["data"]["templateId"]

    patched = await client.patch(
        f"{TEMPLATES_BASE}/{template_id}",
        json={"data": maxed},
        headers=bearer(token),
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["data"]["generation_method"] == "pointbuy"

    room = await create_room(client, token=token)
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template_id},
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    completed = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{draft.json()['data']['characterId']}/complete",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    )
    assert completed.status_code == 422, completed.text


async def test_server_rolled_attributes_survive_edits_that_leave_them_alone(
    client: AsyncClient,
) -> None:
    """服务端掷出来的 roll 背书，在「只改姓名/技能」的保存里必须留住。

    否则玩家在卡库里捏完一张掷骰卡，改一下名字就被降级成点数购买法，进房间
    complete 会因为掷骰总点数超 480 而失败。
    """
    token = await register(client)
    template = await _create_template(client, token)
    template_id = template["templateId"]
    await client.post(f"{TEMPLATES_BASE}/{template_id}/roll-attributes", headers=bearer(token))
    rolled = (await client.get(f"{TEMPLATES_BASE}/{template_id}", headers=bearer(token))).json()[
        "data"
    ]["data"]

    kept = await client.patch(
        f"{TEMPLATES_BASE}/{template_id}",
        json={"data": {**rolled, "name": "改个名字"}},
        headers=bearer(token),
    )
    assert kept.json()["data"]["data"]["generation_method"] == "roll"

    tampered = await client.patch(
        f"{TEMPLATES_BASE}/{template_id}",
        json={"data": {**rolled, "attributes": dict.fromkeys(TEMPLATE_ATTRIBUTES, 90)}},
        headers=bearer(token),
    )
    assert tampered.json()["data"]["data"]["generation_method"] == "pointbuy"


async def test_oversized_template_data_is_refused(client: AsyncClient) -> None:
    token = await register(client)

    response = await client.post(
        TEMPLATES_BASE,
        json={"name": "巨无霸", "systemId": BUILTIN_SYSTEM_ID, "data": {"junk": "x" * 200_000}},
        headers=bearer(token),
    )

    assert response.status_code == 422, response.text


async def test_seeding_onto_an_existing_draft_is_a_conflict(client: AsyncClient) -> None:
    """已有草稿时带模板必须报错，不能返回 201 加一张原封不动的空卡。

    前端多半在进页面时就建好了草稿，所以「从卡库选卡」几乎必然撞上这条路径；
    静默忽略的话它看起来成功了、实际什么都没发生。
    """
    token = await register(client)
    template = await _create_template(client, token)
    room = await create_room(client, token=token)
    headers = {"X-Reconnect-Token": room["reconnectToken"]}

    first = await client.post(f"{ROOMS_BASE}/{room['roomId']}/characters", headers=headers)
    assert first.status_code == 201

    second = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template["templateId"]},
        headers=headers,
    )

    assert second.status_code == 409, second.text


async def test_card_library_endpoints_require_login(client: AsyncClient) -> None:
    token = await register(client)
    template = await _create_template(client, token)
    template_id = template["templateId"]

    for path in ("roll-attributes", "quick-generate"):
        response = await client.post(f"{TEMPLATES_BASE}/{template_id}/{path}")
        assert response.status_code == 401, response.text
    assert (await client.get(TEMPLATES_BASE)).status_code == 401


async def test_saving_a_card_for_a_missing_rule_system_is_refused(client: AsyncClient) -> None:
    """`system_id` 是外键。SQLite 关着约束随便编都能存，PostgreSQL 上是 500。"""
    token = await register(client)

    response = await client.post(
        TEMPLATES_BASE,
        json={
            "name": "野系统卡",
            "systemId": "00000000-0000-0000-0000-0000000000aa",
            "data": TEMPLATE_DATA,
        },
        headers=bearer(token),
    )

    assert response.status_code == 404, response.text


async def test_fields_that_would_overflow_character_columns_are_refused(
    client: AsyncClient,
) -> None:
    """卡库能存、房间存不下的卡不该存在。

    `characters.name` 是 VARCHAR(100)，而卡库的 `data` 只校验总大小。一条 200 字
    的 name 在 SQLite 上一路畅通，到 PostgreSQL 就是「合法保存的卡永远播种不了」。
    """
    token = await register(client)

    too_long = await client.post(
        TEMPLATES_BASE,
        json={
            "name": "超长名字",
            "systemId": BUILTIN_SYSTEM_ID,
            "data": {**TEMPLATE_DATA, "name": "陈" * 101},
        },
        headers=bearer(token),
    )
    assert too_long.status_code == 422, too_long.text

    created = await _create_template(client, token)
    patched = await client.patch(
        f"{TEMPLATES_BASE}/{created['templateId']}",
        json={"data": {**TEMPLATE_DATA, "gender": "男" * 21}},
        headers=bearer(token),
    )
    assert patched.status_code == 422, patched.text


async def test_quick_generate_syncs_the_display_name(client: AsyncClient) -> None:
    """卡库列表展示的是顶层 name，一键生成要把它一起更新。"""
    token = await register(client)
    template = await _create_template(client, token, name="占位名")

    await client.post(
        f"{TEMPLATES_BASE}/{template['templateId']}/quick-generate",
        json={"name": "叶探员"},
        headers=bearer(token),
    )

    listed = await client.get(TEMPLATES_BASE, headers=bearer(token))
    entry = next(
        item for item in listed.json()["data"] if item["templateId"] == template["templateId"]
    )
    assert entry["name"] == "叶探员"
