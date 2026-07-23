"""开发/测试环境的最小内容种子数据。

内容库（`games`/`game_systems`/`scenarios`）本期没有真实的模组管理后台，
`GET /modules` 等目录接口至少需要一条可选模组，"注册 → 建房 → 选模组 →
开局"这条主线才能继续跑通（issue"不回归"验收标准）——原来内存 stub 里硬编码
的 `_BUILTIN_MODULES` 现在改用这份种子数据落进真实数据库。COC7 系统还额外
带上 `app/core/coc7_content.py` 的规则数据（属性/技能/职业目录），供
`GET /systems/{systemId}/ruleset` 返回。

issue #89 起，``Scenario`` 只保存目录和展示信息；规则引擎消费的完整内容保存为
不可变的 ``ModuleVersion``。内置版本在写入前通过当前 ``ModuleContent`` 契约
校验，并且至少包含一个可开局 Scene。

用固定 UUID + 幂等插入（先查是否已存在）：应用启动时、测试 fixture 里都可以
放心重复调用，不会插入重复数据，也不会原地覆盖已经发布的版本内容。
"""

from collaboration_framework.contracts import ModuleContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.models.content import Game, GameSystem, Scenario
from app.models.engine import ModuleVersion

BUILTIN_GAME_ID = "00000000-0000-0000-0000-000000000001"
BUILTIN_SYSTEM_ID = "00000000-0000-0000-0000-000000000002"
BUILTIN_SCENARIO_ID = "00000000-0000-0000-0000-000000000003"
BUILTIN_MODULE_VERSION = "1.0.0"
BUILTIN_WORLD_REF = "coc7-modern"

# 从 dict 入口做校验，确保这份最终写入 JSON 列的发布内容与真实导入/发布边界一致。
# to_json_dict() 同时将 tuple、别名等 Pydantic 表示转换为数据库可序列化的 JSON。
BUILTIN_MODULE_CONTENT = ModuleContent.model_validate(
    {
        "module_id": BUILTIN_SCENARIO_ID,
        "version": BUILTIN_MODULE_VERSION,
        "world_ref": BUILTIN_WORLD_REF,
        "scenes": [
            {
                "id": "scene-old-bookshop",
                "name": "旧书店",
                "content": "调查员来到一间即将打烊的旧书店，寻找失踪藏书留下的线索。",
                "entity_ids": ["location-old-bookshop"],
                "checkpoint_ids": ["checkpoint-search-ledger"],
            }
        ],
        "entities": [
            {
                "id": "location-old-bookshop",
                "kind": "location",
                "name": "旧书店",
                "aliases": ["书店"],
                "content": "狭窄的书架后是一张堆满账本的木桌。",
                "secrets": "最新的借阅记录夹在账本封底。",
                "state": {"ledger_found": False},
                "direct_responses": {"observe": "木桌上的账本有一页明显被反复翻动过。"},
            }
        ],
        "checkpoints": [
            {
                "id": "checkpoint-search-ledger",
                "scene_id": "scene-old-bookshop",
                "action": "search",
                "target_id": "location-old-bookshop",
                "skills": ["spot-hidden"],
                "difficulty": "regular",
                "mvp_check_result": "success",
                "outcomes": {
                    "success": {
                        "facts": ["调查员找到了失踪藏书的借阅记录。"],
                        "player_visible_information": ["账本封底夹着一张近期借阅单。"],
                        "narration_constraints": ["说明借阅单仍然清晰可读。"],
                        "ops": [
                            {
                                "op": "modify",
                                "path": "entities.location-old-bookshop.ledger_found",
                                "set": True,
                            }
                        ],
                    },
                    "failure": {
                        "facts": ["调查员暂时没有发现账本里的暗格。"],
                        "player_visible_information": ["成叠账本让搜索变得十分困难。"],
                        "narration_constraints": ["不要透露借阅单的位置。"],
                    },
                },
            }
        ],
        "win_conditions": [
            {
                "id": "ending-ledger-found",
                "when": {
                    "path": "entities.location-old-bookshop.ledger_found",
                    "equals": True,
                },
                "fact": "调查员取得了追查失踪藏书所需的关键记录。",
                "player_visible_information": "借阅单为下一步调查指明了方向。",
            }
        ],
    }
).to_json_dict()

BUILTIN_STORY_PAGES = [
    {
        "title": "失踪的藏书",
        "content": "一本从未公开编目的旧书离奇失踪，最后的线索指向城南的一间旧书店。",
    }
]


async def ensure_seed_content(db: AsyncSession) -> None:
    """插入内置的"克苏鲁的呼唤 / COC7 / 追书人"种子数据（如果还不存在）。"""
    coc7_ruleset = build_coc7_ruleset().model_dump(mode="json")

    game = await db.get(Game, BUILTIN_GAME_ID)
    if game is None:
        db.add(
            Game(
                id=BUILTIN_GAME_ID,
                name="克苏鲁的呼唤",
                description="COC 内置游戏大类（种子数据）",
            )
        )

    system = await db.get(GameSystem, BUILTIN_SYSTEM_ID)
    if system is None:
        db.add(
            GameSystem(
                id=BUILTIN_SYSTEM_ID,
                game_id=BUILTIN_GAME_ID,
                name="COC7",
                version="7th",
                ruleset=coc7_ruleset,
            )
        )
    elif system.ruleset != coc7_ruleset:
        # 内置规则随代码发版，数据库副本每次启动都跟代码对齐。
        system.ruleset = coc7_ruleset

    scenario = await db.get(Scenario, BUILTIN_SCENARIO_ID)
    if scenario is None:
        scenario = Scenario(
            id=BUILTIN_SCENARIO_ID,
            game_system_id=BUILTIN_SYSTEM_ID,
            title="追书人（内置）",
            version=BUILTIN_MODULE_VERSION,
            authors=["TRPG-master"],
            players_min=1,
            players_max=6,
            difficulty=1,
            estimated_duration="2-3 小时",
            synopsis="内置模拟模组，供 MS1 骨架联调使用。",
            status="ready",
            name_en="The Book Seeker",
            story_label="CASE-001",
            subtitle="失踪藏书留下的最后线索",
            story_pages=BUILTIN_STORY_PAGES,
        )
        db.add(scenario)
    else:
        # 目录展示信息可以随应用更新；已发布的 ModuleVersion 内容不能原地修改。
        scenario.version = BUILTIN_MODULE_VERSION
        scenario.status = "ready"
        scenario.name_en = "The Book Seeker"
        scenario.story_label = "CASE-001"
        scenario.subtitle = "失踪藏书留下的最后线索"
        scenario.story_pages = BUILTIN_STORY_PAGES

    module_version = await db.get(
        ModuleVersion,
        (BUILTIN_SCENARIO_ID, BUILTIN_MODULE_VERSION),
    )
    if module_version is None:
        db.add(
            ModuleVersion(
                module_id=BUILTIN_SCENARIO_ID,
                version=BUILTIN_MODULE_VERSION,
                world_ref=BUILTIN_WORLD_REF,
                content_schema_version=1,
                content_json=BUILTIN_MODULE_CONTENT,
            )
        )

    await db.commit()
