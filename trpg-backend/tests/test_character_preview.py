"""`POST /api/v1/systems/{systemId}/character/preview` 端点测试（issue #84
S2）：路线乙的接缝——前端建卡过程中调它拿权威计算结果来渲染。
"""

from httpx import AsyncClient

from app.core.seed import BUILTIN_SYSTEM_ID

PREVIEW_URL = f"/api/v1/systems/{BUILTIN_SYSTEM_ID}/character/preview"

ATTRS = {"STR": 50, "CON": 50, "POW": 50, "DEX": 50, "APP": 50, "SIZ": 50, "INT": 50, "EDU": 50}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"account": "preview-user", "password": "secret1", "nickname": "预览用户"},
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_preview_requires_login(client: AsyncClient) -> None:
    response = await client.post(PREVIEW_URL, json={"attributes": ATTRS, "skills": {}})

    assert response.status_code == 401


async def test_preview_unknown_system_returns_404(client: AsyncClient) -> None:
    session = await register(client)

    response = await client.post(
        "/api/v1/systems/00000000-0000-0000-0000-000000009999/character/preview",
        json={"attributes": ATTRS, "skills": {}},
        headers=bearer(session["token"]),
    )

    assert response.status_code == 404


async def test_preview_returns_authoritative_compute_result(client: AsyncClient) -> None:
    session = await register(client)

    response = await client.post(
        PREVIEW_URL,
        json={
            "attributes": ATTRS,
            "occupationId": 1,  # 会计师，skillPointsFormula="EDU*4"，信用区间 [30,70]
            # credit-rating（PR #85 review #4 起是一条真正的技能，见
            # coc7_content.py）按 COC7 官方裁定分账：下限 30 点算职业点负担，
            # 超出下限的 20 点（50-30）算兴趣点负担，所以下面两个断言的
            # spent/remaining 都要把这部分算进去。
            "skills": {"accounting": 55, "law": 55, "credit-rating": 50},
        },
        headers=bearer(session["token"]),
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["derivedStats"]["HP"] == 10
    assert data["derivedStats"]["SAN"] == 50

    assert data["occupationSkillPoints"] == {"budget": 200, "spent": 130, "remaining": 70}
    assert data["interestSkillPoints"] == {"budget": 100, "spent": 20, "remaining": 80}

    accounting_view = next(s for s in data["skillView"] if s["id"] == "accounting")
    assert accounting_view == {
        "id": "accounting",
        "base": 5,
        "allocated": 50,
        "current": 55,
        "cap": 99,
    }

    assert data["validation"] == []


async def test_preview_surfaces_issues_for_invalid_draft(client: AsyncClient) -> None:
    """预览接口即使卡不合法也应该返回 200 + 校验报告，不是抛错——它是渲染用
    的接口，前端要能实时看到"哪里超了"，不是等 complete 才知道。"""
    session = await register(client)

    response = await client.post(
        PREVIEW_URL,
        json={
            "attributes": ATTRS,
            "occupationId": 1,
            "skills": {"spot-hidden": 150},
        },
        headers=bearer(session["token"]),
    )

    assert response.status_code == 200
    codes = [issue["code"] for issue in response.json()["data"]["validation"]]
    assert "SKILL_ABOVE_CAP" in codes
