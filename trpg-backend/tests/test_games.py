"""游戏大类 / 规则系统目录接口测试（issue #84 S1：ruleset 从三字符串数组
加厚成结构化的属性/技能/职业规格，这里断言种子数据真的能被端点完整返回）。
"""

from httpx import AsyncClient

from app.core.seed import BUILTIN_SYSTEM_ID


async def test_get_ruleset_returns_full_coc7_data(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/systems/{BUILTIN_SYSTEM_ID}/ruleset")

    assert response.status_code == 200
    data = response.json()["data"]

    # 8 项基础属性，字段完整且带真实的 COC7 生成公式
    assert len(data["attributes"]) == 8
    attrs_by_key = {a["key"]: a for a in data["attributes"]}
    assert attrs_by_key["STR"] == {"key": "STR", "label": "力量", "generation": "3d6*5"}
    assert attrs_by_key["SIZ"]["generation"] == "(2d6+6)*5"

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
