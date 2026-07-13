"""插入 walking skeleton 用的最小测试数据：一个模组、一个场景、一个线索实体、
一个房间、一个玩家、一个角色。跑一次即可，用于验证真实 Postgres 持久化链路。

用法：uv run python scripts/seed_walking_skeleton.py
"""

from __future__ import annotations

import asyncio

from core.content.db_models import EntityRow, ModulePackRow, ModuleSceneRow, WorldRow
from core.db import get_sessionmaker
from core.state.db_models import CharacterRow, PlayerRow, RoomRow, UserRow

WORLD_ID = "coc-7e"
MODULE_ID = "builtin:core:test-scenario:1.0.0"
SCENE_ID = "scene-study"
ENTITY_ID = "entity-bloodstain"
USER_ID = "user-kp-test"
ROOM_ID = "room-test-001"
PLAYER_ID = "player-test-001"
CHARACTER_ID = "character-test-001"


async def main() -> None:
    # 分阶段 flush——纯 FK 列（没建 relationship()）不会让 SQLAlchemy 自动排序，
    # 必须按依赖顺序显式插入；players↔characters 互相引用，用「先插 player
    # （character_id 留空）→ 插 character → 回填 player.character_id」三步破环。
    async with get_sessionmaker()() as session:
        session.add(
            WorldRow(
                id=WORLD_ID,
                name="克苏鲁的呼唤 7版",
                definition={},
                hooks=[],
                variables=[],
                world_rules=[],
            )
        )
        await session.flush()

        session.add(
            ModulePackRow(
                id=MODULE_ID,
                world_ref=WORLD_ID,
                title="测试场景：书房",
                version="1.0.0",
                setting="一栋维多利亚风格老宅的书房，主人昨夜离奇死亡。",
                keeper_notes=None,
                authors=["walking-skeleton"],
                players_min=1,
                players_max=4,
                difficulty=1,
                estimated_duration="30m",
                source="builtin",
                owner_user_id=None,
            )
        )
        session.add(
            UserRow(
                id=USER_ID,
                account="kp_test",
                password_hash="not-a-real-hash",
                nickname="测试守秘人",
            )
        )
        await session.flush()

        session.add(
            ModuleSceneRow(
                id=SCENE_ID,
                module_id=MODULE_ID,
                title="书房",
                description="书桌上散落着信件，壁炉边的地毯上有一小片深色污渍。",
                map_ref=None,
                exits=[],
                contents=[{"kind": "entity_present", "entityId": ENTITY_ID}],
            )
        )
        session.add(
            EntityRow(
                id=ENTITY_ID,
                module_id=MODULE_ID,
                kind="clue",
                name="地毯上的污渍",
                content="凑近查看，能确认是干涸的血迹，形状暗示曾有人在此处倒下并被拖拽。",
                public_persona=None,
                secrets=None,
                stats=None,
                state={"discovered": False},
                rules=[],
                is_core=True,
                intentional_single_path=False,
            )
        )
        await session.flush()

        session.add(
            RoomRow(
                id=ROOM_ID,
                room_code="TEST01",
                host_player_id=PLAYER_ID,
                host_user_id=USER_ID,
                module_pack_id=MODULE_ID,
                phase="InGame",
                entity_states={ENTITY_ID: {"discovered": False}},
                rolling_summary=None,
            )
        )
        await session.flush()

        session.add(
            PlayerRow(
                id=PLAYER_ID,
                room_id=ROOM_ID,
                nickname="测试玩家",
                character_id=None,  # 先留空，等 character 插入后回填
                user_id=USER_ID,
                ready=True,
                connected=True,
            )
        )
        await session.flush()

        session.add(
            CharacterRow(
                id=CHARACTER_ID,
                room_id=ROOM_ID,
                player_id=PLAYER_ID,
                based_on_pregen_id=None,
                name="测试调查员",
                attributes={"STR": 50, "CON": 60, "SIZ": 55, "DEX": 65, "APP": 50, "INT": 70, "POW": 60, "EDU": 75},
                derived_stats={"HP": 11, "SAN": 60, "MP": 12, "LUCK": 55},
                skills={"侦查": {"value": 60, "occPoints": 40, "intPoints": 0}},
                equipment=[{"name": "手电筒", "qty": 1}],
                location=SCENE_ID,
                conditions=[],
                ledger={},
                flags=[],
            )
        )
        await session.flush()

        player = await session.get(PlayerRow, PLAYER_ID)
        assert player is not None
        player.character_id = CHARACTER_ID

        await session.commit()
    print("seed 完成：room_id =", ROOM_ID, "module_id =", MODULE_ID)


if __name__ == "__main__":
    asyncio.run(main())
