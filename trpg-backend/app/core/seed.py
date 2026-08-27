"""开发/测试环境的最小内容种子数据。

内容库（`games`/`game_systems`/`scenarios`）本期没有真实的模组管理后台，
`GET /modules` 等目录接口至少需要一条可选模组，"注册 → 建房 → 选模组 →
开局"这条主线才能继续跑通（issue"不回归"验收标准）——原来内存 stub 里硬编码
的 `_BUILTIN_MODULES` 现在改用这份种子数据落进真实数据库。COC7 系统还额外
带上 `app/core/coc7_content.py` 的规则数据（属性/技能/职业目录），供
`GET /systems/{systemId}/ruleset` 返回。

issue #141 起，``Scenario`` 只保存目录和展示信息。规则引擎消费的完整内容由
内置模组加载器经过 Validation 后写入不可变的 ``ModuleVersion``；Seed
不再内嵌或发布简化版 ModuleContent。

用固定 UUID + 幂等插入（先查是否已存在）：应用启动时、测试 fixture 里都可以
放心重复调用，不会插入重复数据，也不会改变加载脚本已经发布的版本和 ready 状态。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.models.content import Game, GameSystem, Scenario, World
from app.service.builtin_module_loader import (
    BUILTIN_MODULE_SPECS,
    HAPPY_FROG_VILLAGE_SPEC,
    PAPER_CHASE_SPEC,
    SILVER_LOCK_SPEC,
    read_builtin_presentation,
)

BUILTIN_GAME_ID = "00000000-0000-0000-0000-000000000001"
BUILTIN_SYSTEM_ID = "00000000-0000-0000-0000-000000000002"
BUILTIN_SCENARIO_ID = PAPER_CHASE_SPEC.scenario_id
BUILTIN_WORLD_ID = "00000000-0000-0000-0000-000000000004"
BUILTIN_MODULE_ID = PAPER_CHASE_SPEC.module_id
BUILTIN_MODULE_VERSION = PAPER_CHASE_SPEC.version
BUILTIN_WORLD_REF = PAPER_CHASE_SPEC.world_ref
SILVER_LOCK_SCENARIO_ID = SILVER_LOCK_SPEC.scenario_id
SILVER_LOCK_MODULE_ID = SILVER_LOCK_SPEC.module_id
SILVER_LOCK_MODULE_VERSION = SILVER_LOCK_SPEC.version
HAPPY_FROG_VILLAGE_SCENARIO_ID = HAPPY_FROG_VILLAGE_SPEC.scenario_id
HAPPY_FROG_VILLAGE_MODULE_ID = HAPPY_FROG_VILLAGE_SPEC.module_id
HAPPY_FROG_VILLAGE_MODULE_VERSION = HAPPY_FROG_VILLAGE_SPEC.version


async def ensure_seed_content(db: AsyncSession) -> None:
    """插入 COC7 规则、世界和全部内置模组目录种子。"""
    coc7_ruleset = build_coc7_ruleset().model_dump(mode="json")

    game = await db.get(Game, BUILTIN_GAME_ID)
    if game is None:
        db.add(
            Game(
                id=BUILTIN_GAME_ID,
                name="克苏鲁的呼唤",
                description=(
                    "在熟悉的现实世界表层之下，调查员通过走访、检索与推理接触不可名状的宇宙恐怖；"
                    "重视调查、角色扮演与理智风险，正面战斗通常不是首选。"
                ),
                tags=["1920年代", "调查悬疑", "宇宙恐怖"],
            )
        )
    else:
        game.name = "克苏鲁的呼唤"
        game.description = (
            "在熟悉的现实世界表层之下，调查员通过走访、检索与推理接触不可名状的宇宙恐怖；"
            "重视调查、角色扮演与理智风险，正面战斗通常不是首选。"
        )
        game.tags = ["1920年代", "调查悬疑", "宇宙恐怖"]

    world = await db.get(World, BUILTIN_WORLD_ID)
    if world is None:
        db.add(
            World(
                id=BUILTIN_WORLD_ID,
                game_id=BUILTIN_GAME_ID,
                name="禁酒令时期的阿诺兹堡",
                description=(
                    "1920 年代美国密歇根州的小城。旧书、失踪案与不可名状的恐怖交织，"
                    "调查员需要依靠走访、观察和谨慎判断逐步还原真相。"
                ),
            )
        )

    system = await db.get(GameSystem, BUILTIN_SYSTEM_ID)
    if system is None:
        db.add(
            GameSystem(
                id=BUILTIN_SYSTEM_ID,
                game_id=BUILTIN_GAME_ID,
                world_ref=BUILTIN_WORLD_REF,
                name="COC7",
                version="7th",
                ruleset=coc7_ruleset,
            )
        )
    else:
        # 内置规则与稳定 world_ref 随代码发版，数据库副本每次启动都跟代码对齐。
        system.world_ref = BUILTIN_WORLD_REF
        system.ruleset = coc7_ruleset

    for spec in BUILTIN_MODULE_SPECS:
        presentation = read_builtin_presentation(spec)
        scenario = await db.get(Scenario, spec.scenario_id)
        if scenario is None:
            scenario = Scenario(
                id=spec.scenario_id,
                module_id=spec.module_id,
                world_id=spec.world_id,
                game_system_id=BUILTIN_SYSTEM_ID,
                title=presentation.title,
                version=spec.version,
                authors=list(presentation.authors),
                players_min=presentation.players_min,
                players_max=presentation.players_max,
                difficulty=presentation.difficulty,
                estimated_duration=presentation.estimated_duration,
                synopsis=presentation.synopsis,
                status="wip",
                name_en=presentation.name_en,
                story_label=presentation.story_label,
                subtitle=presentation.subtitle,
                story_pages=[],
            )
            db.add(scenario)
            continue

        # 已发布目录由加载器更新；Seed 不得把 ready 版本降回 wip 或覆盖展示。
        scenario.module_id = spec.module_id
        scenario.world_id = spec.world_id
        scenario.game_system_id = BUILTIN_SYSTEM_ID
        if scenario.status != "ready":
            scenario.title = presentation.title
            scenario.name_en = presentation.name_en
            scenario.version = spec.version
            scenario.players_min = presentation.players_min
            scenario.players_max = presentation.players_max
            scenario.difficulty = presentation.difficulty
            scenario.estimated_duration = presentation.estimated_duration
            scenario.synopsis = presentation.synopsis
            scenario.story_label = presentation.story_label
            scenario.subtitle = presentation.subtitle

    await db.commit()
