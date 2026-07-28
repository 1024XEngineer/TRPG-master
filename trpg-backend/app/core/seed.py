"""开发/测试环境的最小内容种子数据。

内容库（`games`/`game_systems`/`scenarios`）本期没有真实的模组管理后台，
`GET /modules` 等目录接口至少需要一条可选模组，"注册 → 建房 → 选模组 →
开局"这条主线才能继续跑通（issue"不回归"验收标准）——原来内存 stub 里硬编码
的 `_BUILTIN_MODULES` 现在改用这份种子数据落进真实数据库。COC7 系统还额外
带上 `app/core/coc7_content.py` 的规则数据（属性/技能/职业目录），供
`GET /systems/{systemId}/ruleset` 返回。

issue #141 起，``Scenario`` 只保存目录和展示信息。规则引擎消费的完整内容由
本地追书人加载脚本经过 Validation 后写入不可变的 ``ModuleVersion``；Seed
不再内嵌或发布简化版 ModuleContent。

用固定 UUID + 幂等插入（先查是否已存在）：应用启动时、测试 fixture 里都可以
放心重复调用，不会插入重复数据，也不会改变加载脚本已经发布的版本和 ready 状态。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.models.content import Game, GameSystem, Scenario, World

BUILTIN_GAME_ID = "00000000-0000-0000-0000-000000000001"
BUILTIN_SYSTEM_ID = "00000000-0000-0000-0000-000000000002"
BUILTIN_SCENARIO_ID = "00000000-0000-0000-0000-000000000003"
BUILTIN_WORLD_ID = "00000000-0000-0000-0000-000000000004"
BUILTIN_MODULE_ID = "paper-chase-zh-coc7"
BUILTIN_MODULE_VERSION = "1.0.0"
BUILTIN_WORLD_REF = "coc-7e"

BUILTIN_STORY_PAGES = [
    {
        "title": "托马斯的委托",
        "content": (
            "1920 年代的密歇根州阿诺兹堡，托马斯·金博尔请你寻找从叔叔旧居"
            "失窃的五本旧书，并查明叔叔道格拉斯一年前的失踪案。"
        ),
    }
]


async def ensure_seed_content(db: AsyncSession) -> None:
    """插入内置的"克苏鲁的呼唤 / COC7 / 追书人"种子数据（如果还不存在）。"""
    coc7_ruleset = build_coc7_ruleset().model_dump(mode="json")

    game = await db.get(Game, BUILTIN_GAME_ID)
    if game is None:
        game = Game(id=BUILTIN_GAME_ID, name="克苏鲁的呼唤")
        db.add(game)
    game.name = "克苏鲁的呼唤"
    game.description = "以调查、线索和理智为核心的现代恐怖角色扮演游戏；本目录采用第七版规则。"

    world = await db.get(World, BUILTIN_WORLD_ID)
    if world is None:
        db.add(
            World(
                id=BUILTIN_WORLD_ID,
                game_id=BUILTIN_GAME_ID,
                name="禁酒令时期的阿诺兹堡",
                description=(
                    "1920 年代美国密歇根州的小城。旧书、墓园与失踪案交织在一起，"
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

    scenario = await db.get(Scenario, BUILTIN_SCENARIO_ID)
    if scenario is None:
        scenario = Scenario(
            id=BUILTIN_SCENARIO_ID,
            module_id=BUILTIN_MODULE_ID,
            world_id=BUILTIN_WORLD_ID,
            game_system_id=BUILTIN_SYSTEM_ID,
            title="追书人",
            version=BUILTIN_MODULE_VERSION,
            authors=["TRPG-master"],
            players_min=2,
            players_max=5,
            difficulty=2,
            estimated_duration="3-4 小时",
            synopsis="调查员受托寻找五本失窃旧书，并查明道格拉斯一年前的失踪案；线索将带你走访旧宅、图书馆与公共墓地。",
            status="wip",
            name_en="The Book Seeker",
            story_label="CASE-001",
            subtitle="失踪藏书留下的最后线索",
            story_pages=BUILTIN_STORY_PAGES,
        )
        db.add(scenario)
    else:
        # 目录展示信息可以随应用更新；加载器写入的推荐版本和 ready 状态必须保留。
        scenario.module_id = BUILTIN_MODULE_ID
        scenario.world_id = BUILTIN_WORLD_ID
        scenario.title = "追书人"
        scenario.players_min = 2
        scenario.players_max = 5
        scenario.difficulty = 2
        scenario.estimated_duration = "3-4 小时"
        scenario.synopsis = (
            "调查员受托寻找五本失窃旧书，并查明道格拉斯一年前的失踪案；"
            "线索将带你走访旧宅、图书馆与公共墓地。"
        )
        scenario.name_en = "The Book Seeker"
        scenario.story_label = "CASE-001"
        scenario.subtitle = "失踪藏书留下的最后线索"
        scenario.story_pages = BUILTIN_STORY_PAGES

    await db.commit()
