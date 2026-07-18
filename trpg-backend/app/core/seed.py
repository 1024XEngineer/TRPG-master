"""开发/测试环境的最小内容种子数据（issue #77，issue #84 S1 补充 ruleset）。

内容库（`games`/`game_systems`/`scenarios`）本期没有真实的模组管理后台，
`GET /modules` 等目录接口至少需要一条可选模组，"注册 → 建房 → 选模组 →
开局"这条主线才能继续跑通（issue"不回归"验收标准）——原来内存 stub 里硬编码
的 `_BUILTIN_MODULES` 现在改用这份种子数据落进真实数据库。COC7 系统还额外
带上 `app/core/coc7_content.py` 的规则数据（属性/技能/职业目录），供
`GET /systems/{systemId}/ruleset` 返回。

用固定 UUID + 幂等插入（先查是否已存在）：应用启动时、测试 fixture 里都可以
放心重复调用，不会插入重复数据。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.models.content import Game, GameSystem, Scenario

BUILTIN_GAME_ID = "00000000-0000-0000-0000-000000000001"
BUILTIN_SYSTEM_ID = "00000000-0000-0000-0000-000000000002"
BUILTIN_SCENARIO_ID = "00000000-0000-0000-0000-000000000003"


async def ensure_seed_content(db: AsyncSession) -> None:
    """插入内置的"克苏鲁的呼唤 / COC7 / 追书人"种子数据（如果还不存在）。"""
    existing = await db.get(Scenario, BUILTIN_SCENARIO_ID)
    coc7_ruleset = build_coc7_ruleset().model_dump(mode="json")

    if existing is not None:
        # 种子数据本身已经跑过，但 `ruleset` 是 issue #84 S1 才补上的字段——
        # 旧库里已存在的 GameSystem 行可能还没有，这里顺带补全，不破坏幂等性。
        system = await db.get(GameSystem, BUILTIN_SYSTEM_ID)
        if system is not None and not system.ruleset:
            system.ruleset = coc7_ruleset
            await db.commit()
        return

    db.add(
        Game(id=BUILTIN_GAME_ID, name="克苏鲁的呼唤", description="COC 内置游戏大类（种子数据）")
    )
    db.add(
        GameSystem(
            id=BUILTIN_SYSTEM_ID,
            game_id=BUILTIN_GAME_ID,
            name="COC7",
            version="7th",
            ruleset=coc7_ruleset,
        )
    )
    db.add(
        Scenario(
            id=BUILTIN_SCENARIO_ID,
            game_system_id=BUILTIN_SYSTEM_ID,
            title="追书人（内置）",
            version="1.0.0",
            authors=["TRPG-master"],
            players_min=1,
            players_max=6,
            difficulty=1,
            estimated_duration="2-3 小时",
            synopsis="内置模拟模组，供 MS1 骨架联调使用。",
        )
    )
    await db.commit()
