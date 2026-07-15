from httpx import AsyncClient


async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "ok"}, "error": None}
