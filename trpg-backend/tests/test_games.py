"""游戏大类 / 规则系统目录接口测试（issue #84 S1：ruleset 从三字符串数组
加厚成结构化的属性/技能/职业规格，这里断言种子数据真的能被端点完整返回）。
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import BUILTIN_SYSTEM_ID, ensure_seed_content
from app.models.content import GameSystem


async def test_get_ruleset_returns_full_coc7_data(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/systems/{BUILTIN_SYSTEM_ID}/ruleset")

    assert response.status_code == 200
    data = response.json()["data"]

    # 9 项属性（8 项基础属性 + 幸运），字段完整且带真实的 COC7 生成公式
    assert len(data["attributes"]) == 9
    attrs_by_key = {a["key"]: a for a in data["attributes"]}
    assert attrs_by_key["STR"] == {
        "key": "STR",
        "label": "力量",
        "generation": "3d6*5",
        "pointBuy": True,
    }
    assert attrs_by_key["SIZ"]["generation"] == "(2d6+6)*5"
    # 幸运独立掷 3d6*5（跟 STR 一组生成公式，不是 (2d6+6)*5 那一组），
    # 且 pointBuy=False——COC7 里它只能掷、不能用属性点购买。客户端据此
    # 决定哪些属性渲染成可加点，不用自己维护一份名单（issue #96）。
    assert attrs_by_key["LUCK"] == {
        "key": "LUCK",
        "label": "幸运",
        "generation": "3d6*5",
        "pointBuy": False,
    }
    assert [a["key"] for a in data["attributes"] if a["pointBuy"]] == [
        "STR",
        "CON",
        "POW",
        "DEX",
        "APP",
        "SIZ",
        "INT",
        "EDU",
    ]

    # 点数购买法的约束必须由后端暴露，客户端不该再自己硬编码一份
    # （issue #96：480/[10,90]/默认值此前只存在于前端代码里）。
    assert data["attributePointBuy"] == {
        "budget": 480,
        "minValue": 10,
        "maxValue": 90,
        "defaultValue": 50,
    }

    # 80 项技能（前端 ALL_SKILLS 原有 76 条 + issue #84 S2 补齐的 3 条悬空引用
    # navigate/carpentry/illusion + PR #85 review 补的信用评级 credit-rating），
    # 固定值和公式值都要能原样带过来
    assert len(data["skills"]) == 80
    skills_by_id = {s["id"]: s for s in data["skills"]}
    assert skills_by_id["spot-hidden"]["base"] == 25
    assert skills_by_id["dodge"]["base"] == "DEX/2"
    assert skills_by_id["spot-hidden"]["category"] == "perception"

    # 30 个职业（前端 ALL_OCCUPATIONS 实际条数），信用评级区间和技能点公式要拆解正确
    assert len(data["occupations"]) == 30
    occs_by_id = {o["id"]: o for o in data["occupations"]}
    accountant = occs_by_id[1]
    assert accountant["name"] == "会计师"
    assert accountant["creditMin"] == 30
    assert accountant["creditMax"] == 70
    assert accountant["skillPointsFormula"] == "EDU*4"
    assert "accounting" in accountant["skillIds"]


async def test_get_ruleset_unknown_system_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/systems/00000000-0000-0000-0000-000000009999/ruleset")

    assert response.status_code == 404


async def test_seed_refreshes_stale_builtin_ruleset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """内置系统的 ruleset 每次启动都要跟代码对齐（PR #88 review #3）。

    原来 seed 只在 `not system.ruleset` 时写入，于是改了 `coc7_content.py` 之后
    已存在的库永远拿不到新规则——加幸运时就撞上了：后端要求 9 个属性键，旧库
    的 ruleset 却还是 8 项，`GET /ruleset` 一直返回旧数据。这里模拟"旧库"：把
    ruleset 改成过时的 8 项，再跑一次 seed，断言它被刷新回代码里的 9 项。
    """
    system = await db_session.get(GameSystem, BUILTIN_SYSTEM_ID)
    assert system is not None
    assert system.ruleset is not None
    stale = dict(system.ruleset)
    stale["attributes"] = [a for a in stale["attributes"] if a["key"] != "LUCK"]
    system.ruleset = stale
    await db_session.commit()

    # 旧库状态：接口确实返回过时的 8 项
    response = await client.get(f"/api/v1/systems/{BUILTIN_SYSTEM_ID}/ruleset")
    assert len(response.json()["data"]["attributes"]) == 8

    await ensure_seed_content(db_session)

    # seed 跑完后应该被刷新回代码里的 9 项（含 LUCK）
    response = await client.get(f"/api/v1/systems/{BUILTIN_SYSTEM_ID}/ruleset")
    attributes = response.json()["data"]["attributes"]
    assert len(attributes) == 9
    assert any(a["key"] == "LUCK" for a in attributes)
