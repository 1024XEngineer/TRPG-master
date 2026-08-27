"""验证三个内置模组的发布、目录和选模组行为。"""

from __future__ import annotations

from copy import deepcopy

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import (
    HAPPY_FROG_VILLAGE_MODULE_ID,
    HAPPY_FROG_VILLAGE_SCENARIO_ID,
    SILVER_LOCK_MODULE_ID,
    SILVER_LOCK_SCENARIO_ID,
)
from app.models.content import ModuleAsset, Scenario
from app.models.engine import ModuleVersion
from app.models.room import Room
from app.service.builtin_module_loader import (
    HAPPY_FROG_VILLAGE_SPEC,
    PAPER_CHASE_SPEC,
    SILVER_LOCK_SPEC,
    BuiltinModuleLoadError,
    load_builtin_module,
    load_builtin_modules,
)
from tests.helpers import ROOMS_BASE, create_room, reconnect


async def test_all_builtin_modules_load_idempotently(db_session: AsyncSession) -> None:
    """测试 fixture 已发布一次，再次全量加载必须全部 unchanged。"""

    results = await load_builtin_modules(db_session)
    assert [(result.module_id, result.outcome) for result in results] == [
        ("paper-chase-zh-coc7", "unchanged"),
        (SILVER_LOCK_MODULE_ID, "unchanged"),
        (HAPPY_FROG_VILLAGE_MODULE_ID, "unchanged"),
    ]

    scenario = await db_session.get(Scenario, SILVER_LOCK_SCENARIO_ID)
    version = await db_session.get(
        ModuleVersion,
        (SILVER_LOCK_MODULE_ID, SILVER_LOCK_SPEC.version),
    )
    assert scenario is not None
    assert scenario.status == "ready"
    assert scenario.world_id is None
    assert scenario.players_min == scenario.players_max == 1
    assert version is not None
    assert version.content_schema_version == 3


async def test_paper_chase_npc_portraits_are_seeded_idempotently(
    db_session: AsyncSession,
) -> None:
    """《追书人》发布会写入五个 NPC 头像，重复发布不增加记录。"""

    before = list(
        await db_session.scalars(
            select(ModuleAsset).where(
                ModuleAsset.scenario_id == PAPER_CHASE_SPEC.scenario_id,
                ModuleAsset.asset_type == "npc_portrait",
            )
        )
    )
    await db_session.commit()
    await load_builtin_modules(db_session)
    after = list(
        await db_session.scalars(
            select(ModuleAsset).where(
                ModuleAsset.scenario_id == PAPER_CHASE_SPEC.scenario_id,
                ModuleAsset.asset_type == "npc_portrait",
            )
        )
    )
    assert len(before) == len(after) == 5
    assert {asset.entity_id for asset in after} == {
        "thomas",
        "cemetery_figure",
        "lyla",
        "melodias",
        "hilda",
    }


async def test_happy_frog_village_npc_portraits_are_seeded_idempotently(
    db_session: AsyncSession,
) -> None:
    """《幸福蛙蛙村》发布会写入全部七个 NPC 实体的头像。"""

    query = select(ModuleAsset).where(
        ModuleAsset.scenario_id == HAPPY_FROG_VILLAGE_SCENARIO_ID,
        ModuleAsset.asset_type == "npc_portrait",
    )
    before = list(await db_session.scalars(query))
    await db_session.commit()
    await load_builtin_modules(db_session)
    after = list(await db_session.scalars(query))

    assert len(before) == len(after) == 7
    assert {asset.entity_id: asset.url for asset in after} == {
        "villager_accounts": ("/assets/npc_portraits/happy-frog-village/villager_accounts.webp"),
        "ezra": "/assets/npc_portraits/happy-frog-village/ezra.webp",
        "messenger": "/assets/npc_portraits/happy-frog-village/messenger.webp",
        "emily": "/assets/npc_portraits/happy-frog-village/emily.webp",
        "james": "/assets/npc_portraits/happy-frog-village/james.webp",
        "frog_head_guest": ("/assets/npc_portraits/happy-frog-village/frog_head_guest.webp"),
        "dream_frogs": "/assets/npc_portraits/happy-frog-village/dream_frogs.webp",
    }


async def test_silver_lock_rejects_changed_immutable_version(
    db_session: AsyncSession,
) -> None:
    """相同版本被篡改后必须拒绝覆盖，保留数据库中的原内容。"""

    version = await db_session.get(
        ModuleVersion,
        (SILVER_LOCK_MODULE_ID, SILVER_LOCK_SPEC.version),
    )
    assert version is not None
    changed = deepcopy(version.content_json)
    changed["background"] = "同版本的另一份银之锁内容"
    version.content_json = changed
    await db_session.commit()

    with pytest.raises(BuiltinModuleLoadError, match="不会静默覆盖"):
        await load_builtin_module(db_session, SILVER_LOCK_SPEC)

    db_session.expire_all()
    preserved = await db_session.get(
        ModuleVersion,
        (SILVER_LOCK_MODULE_ID, SILVER_LOCK_SPEC.version),
    )
    assert preserved is not None
    assert preserved.content_json == changed


async def test_silver_lock_publish_rolls_back_version_and_ready_together(
    db_session: AsyncSession,
) -> None:
    """注入提交前失败，不能留下不可变版本或半发布目录。"""

    await db_session.execute(
        delete(ModuleVersion).where(
            ModuleVersion.module_id == SILVER_LOCK_MODULE_ID,
            ModuleVersion.version == SILVER_LOCK_SPEC.version,
        )
    )
    scenario = await db_session.get(Scenario, SILVER_LOCK_SCENARIO_ID)
    assert scenario is not None
    scenario.status = "wip"
    await db_session.commit()

    def fail_before_commit() -> None:
        raise RuntimeError("injected silver lock failure")

    with pytest.raises(RuntimeError, match="injected silver lock failure"):
        await load_builtin_module(
            db_session,
            SILVER_LOCK_SPEC,
            _before_commit=fail_before_commit,
        )

    db_session.expire_all()
    rolled_back = await db_session.get(Scenario, SILVER_LOCK_SCENARIO_ID)
    assert rolled_back is not None
    assert rolled_back.status == "wip"
    assert (
        await db_session.get(
            ModuleVersion,
            (SILVER_LOCK_MODULE_ID, SILVER_LOCK_SPEC.version),
        )
        is None
    )


async def test_catalog_and_selection_use_silver_lock_publication(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """目录由 API 返回双模组，单人房间选择后钉住银之锁版本。"""

    catalog = (await client.get("/api/v1/modules")).json()["data"]
    assert {
        "paper-chase-zh-coc7",
        SILVER_LOCK_MODULE_ID,
    } <= {module["id"] for module in catalog}
    silver = next(module for module in catalog if module["id"] == SILVER_LOCK_MODULE_ID)
    assert silver["title"] == "银之锁"
    assert silver["authors"] == ["夕影"]
    assert silver["playersMin"] == silver["playersMax"] == 1

    detail = (await client.get(f"/api/v1/modules/{SILVER_LOCK_MODULE_ID}")).json()["data"]
    assert detail["storyPages"][0]["title"] == "内容提示"
    assert "动物死亡" in detail["storyPages"][0]["content"]

    oversized = await create_room(client, max_players=2)
    rejected = await client.post(
        f"{ROOMS_BASE}/{oversized['roomId']}/module",
        json={"moduleId": SILVER_LOCK_MODULE_ID, "attributeGenMethod": "point_buy"},
        headers=reconnect(oversized["reconnectToken"]),
    )
    assert rejected.status_code == 409

    room_data = await create_room(client, max_players=1)
    accepted = await client.post(
        f"{ROOMS_BASE}/{room_data['roomId']}/module",
        json={"moduleId": SILVER_LOCK_MODULE_ID, "attributeGenMethod": "point_buy"},
        headers=reconnect(room_data["reconnectToken"]),
    )
    assert accepted.status_code == 200
    room = await db_session.get(Room, room_data["roomId"])
    assert room is not None
    assert room.scenario_id == SILVER_LOCK_SCENARIO_ID
    assert room.module_version == SILVER_LOCK_SPEC.version


async def test_catalog_and_selection_use_happy_frog_village_publication(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """第三个预设在目录中展示，且 1-4 人房间可钉住其不可变版本。"""

    catalog = (await client.get("/api/v1/modules")).json()["data"]
    frog = next(module for module in catalog if module["id"] == HAPPY_FROG_VILLAGE_MODULE_ID)
    assert frog["title"] == "幸福蛙蛙村"
    assert frog["authors"] == ["一只小小信"]
    assert frog["playersMin"] == 1
    assert frog["playersMax"] == 4

    detail = (await client.get(f"/api/v1/modules/{HAPPY_FROG_VILLAGE_MODULE_ID}")).json()["data"]
    assert detail["storyPages"][0]["title"] == "内容提示"
    assert "身体异变" in detail["storyPages"][0]["content"]

    room_data = await create_room(client, max_players=4)
    accepted = await client.post(
        f"{ROOMS_BASE}/{room_data['roomId']}/module",
        json={
            "moduleId": HAPPY_FROG_VILLAGE_MODULE_ID,
            "attributeGenMethod": "point_buy",
        },
        headers=reconnect(room_data["reconnectToken"]),
    )
    assert accepted.status_code == 200
    room = await db_session.get(Room, room_data["roomId"])
    assert room is not None
    assert room.scenario_id == HAPPY_FROG_VILLAGE_SCENARIO_ID
    assert room.module_version == HAPPY_FROG_VILLAGE_SPEC.version
