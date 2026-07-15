from httpx import AsyncClient

BASE = "/api/v1/examples"


async def test_list_examples_starts_empty(client: AsyncClient) -> None:
    response = await client.get(BASE)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["error"] is None


async def test_create_get_update_delete_flow(client: AsyncClient) -> None:
    create_res = await client.post(BASE, json={"name": "线索A", "description": "第一条线索"})
    assert create_res.status_code == 201
    created = create_res.json()["data"]
    assert created["name"] == "线索A"
    assert created["description"] == "第一条线索"
    assert created["id"]
    assert created["created_at"]
    assert created["updated_at"]
    example_id = created["id"]

    list_res = await client.get(BASE)
    assert list_res.status_code == 200
    assert len(list_res.json()["data"]) == 1

    get_res = await client.get(f"{BASE}/{example_id}")
    assert get_res.status_code == 200
    assert get_res.json()["data"]["id"] == example_id

    update_res = await client.put(
        f"{BASE}/{example_id}", json={"name": "线索A-已更新", "description": None}
    )
    assert update_res.status_code == 200
    updated = update_res.json()["data"]
    assert updated["name"] == "线索A-已更新"
    assert updated["description"] is None

    delete_res = await client.delete(f"{BASE}/{example_id}")
    assert delete_res.status_code == 200
    assert delete_res.json() == {"success": True, "data": None, "error": None}

    get_after_delete = await client.get(f"{BASE}/{example_id}")
    assert get_after_delete.status_code == 404
    assert get_after_delete.json()["error"]["code"] == "NOT_FOUND"


async def test_get_missing_example_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"] == {"code": "NOT_FOUND", "message": "示例不存在"}


async def test_create_duplicate_name_returns_409(client: AsyncClient) -> None:
    payload = {"name": "重复名称", "description": None}
    first = await client.post(BASE, json=payload)
    assert first.status_code == 201

    second = await client.post(BASE, json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_create_with_invalid_payload_returns_422(client: AsyncClient) -> None:
    response = await client.post(BASE, json={"name": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


async def test_update_missing_example_returns_404(client: AsyncClient) -> None:
    response = await client.put(
        f"{BASE}/does-not-exist", json={"name": "任意名称", "description": None}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
