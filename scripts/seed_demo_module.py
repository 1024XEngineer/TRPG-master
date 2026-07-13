"""插入这次 /goal 任务要用的模拟 COC 模组——比 walking skeleton 阶段那个单场景
测试数据丰富一些，四个场景可以互相走动、三条线索，供前端 demo 实际跑通"各种交互"。
不做模组导入，纯手写内容，一次性 seed。

用法：uv run python scripts/seed_demo_module.py
"""

from __future__ import annotations

import asyncio

from core.content.db_models import EntityRow, ModulePackRow, ModuleSceneRow, WorldRow
from core.db import get_sessionmaker
import core.state.db_models  # noqa: F401  (触发 users 等表注册进同一个 Base.metadata，module_packs.owner_user_id 的 FK 需要)

WORLD_ID = "coc-7e"
MODULE_ID = "builtin:core:whateley-manor:1.0.0"

SCENE_GATE = "scene-gate"
SCENE_HALLWAY = "scene-hallway"
SCENE_STUDY = "scene-study-2"
SCENE_BASEMENT = "scene-basement"

ENTITY_FOOTPRINTS = "entity-footprints"
ENTITY_BLOODSTAIN = "entity-bloodstain-2"
ENTITY_DIARY = "entity-diary"
ENTITY_LOCKED_DOOR = "entity-locked-door"


async def main() -> None:
    async with get_sessionmaker()() as session:
        existing_world = await session.get(WorldRow, WORLD_ID)
        if existing_world is None:
            session.add(
                WorldRow(id=WORLD_ID, name="克苏鲁的呼唤 7版", definition={}, hooks=[], variables=[], world_rules=[])
            )
            await session.flush()

        session.add(
            ModulePackRow(
                id=MODULE_ID,
                world_ref=WORLD_ID,
                title="惠特利旧宅",
                version="1.0.0",
                setting=(
                    "阿卡姆郊区，惠特利教授三天前突然失踪，只留下虚掩的铁门和满地划痕。"
                    "调查员受托前来查明真相——旧宅里弥漫着潮湿木头与尘土的气息，"
                    "二楼窗户偶尔透出不属于烛光的蓝绿色光芒。"
                ),
                keeper_notes="守秘人提示：三条线索独立可发现，无先后顺序要求；地下室门锁死，本期无法打开（故意设计为死胡同，用于测试'调查未命中预设内容'分支）。",
                authors=["walking-skeleton-demo"],
                players_min=1,
                players_max=4,
                difficulty=1,
                estimated_duration="30-45m",
                source="builtin",
                owner_user_id=None,
            )
        )
        await session.flush()

        session.add_all(
            [
                ModuleSceneRow(
                    id=SCENE_GATE,
                    module_id=MODULE_ID,
                    title="惠特利旧宅 · 正门",
                    description="铁门虚掩着，里面传来一股潮湿的木头和尘土气息。锁孔旁有新鲜的划痕——有人比你们先到了。前院的喷泉早已干涸，藤蔓爬满了石像。",
                    map_ref=None,
                    exits=[SCENE_HALLWAY],
                    contents=[{"kind": "clue_access", "entityId": ENTITY_FOOTPRINTS, "via": "auto"}],
                ),
                ModuleSceneRow(
                    id=SCENE_HALLWAY,
                    module_id=MODULE_ID,
                    title="门厅",
                    description="一楼入口，墙上挂着几幅落满灰尘的肖像画，画中人的眼神让人不太舒服。空气中弥漫着一股若有若无的霉味。",
                    map_ref=None,
                    exits=[SCENE_GATE, SCENE_STUDY, SCENE_BASEMENT],
                    contents=[],
                ),
                ModuleSceneRow(
                    id=SCENE_STUDY,
                    module_id=MODULE_ID,
                    title="书房",
                    description="书桌上散落着信件，壁炉边的地毯上有一小片深色污渍。书架的一角露出一本没有合拢的日记本。",
                    map_ref=None,
                    exits=[SCENE_HALLWAY],
                    contents=[
                        {"kind": "clue_access", "entityId": ENTITY_BLOODSTAIN, "via": "auto"},
                        {"kind": "clue_access", "entityId": ENTITY_DIARY, "via": "auto"},
                    ],
                ),
                ModuleSceneRow(
                    id=SCENE_BASEMENT,
                    module_id=MODULE_ID,
                    title="地下室入口",
                    description="通往地下室的门紧锁着，门缝里透出一丝寒气，锁孔周围有奇怪的刮痕。",
                    map_ref=None,
                    exits=[SCENE_HALLWAY],
                    contents=[{"kind": "entity_present", "entityId": ENTITY_LOCKED_DOOR}],
                ),
            ]
        )

        session.add_all(
            [
                EntityRow(
                    id=ENTITY_FOOTPRINTS,
                    module_id=MODULE_ID,
                    kind="clue",
                    name="花园里的脚印",
                    content="除了你们的脚印，地上还有一双略小的鞋印，从铁门旁绕向了西侧的花园，脚印很新，边缘还没被夜露打湿。",
                    public_persona=None,
                    secrets=None,
                    stats=None,
                    state={"discovered": False},
                    rules=[],
                    is_core=True,
                    intentional_single_path=False,
                ),
                EntityRow(
                    id=ENTITY_BLOODSTAIN,
                    module_id=MODULE_ID,
                    kind="clue",
                    name="地毯上的污渍",
                    content="凑近查看，能确认是干涸的血迹，形状暗示曾有人在此处倒下并被拖拽，拖痕的方向指向壁炉。",
                    public_persona=None,
                    secrets=None,
                    stats=None,
                    state={"discovered": False},
                    rules=[],
                    is_core=True,
                    intentional_single_path=False,
                ),
                EntityRow(
                    id=ENTITY_DIARY,
                    module_id=MODULE_ID,
                    kind="clue",
                    name="惠特利教授的日记",
                    content="最后几页字迹潦草，反复提到'门后的低语'和一个从未标注在任何地图上的日期。最后一页只写着：'它已经知道我在听了。'",
                    public_persona=None,
                    secrets=None,
                    stats=None,
                    state={"discovered": False},
                    rules=[],
                    is_core=True,
                    intentional_single_path=False,
                ),
                EntityRow(
                    id=ENTITY_LOCKED_DOOR,
                    module_id=MODULE_ID,
                    kind="object",
                    name="地下室的锁门",
                    content="一扇厚重的橡木门，锁孔样式很旧，普通钥匙插不进去。本期模组没有为它设计开启路径。",
                    public_persona=None,
                    secrets=None,
                    stats=None,
                    state={},
                    rules=[],
                    is_core=False,
                    intentional_single_path=False,
                ),
            ]
        )

        await session.commit()

    print("seed 完成：module_id =", MODULE_ID, "起始场景 =", SCENE_GATE)


if __name__ == "__main__":
    asyncio.run(main())
