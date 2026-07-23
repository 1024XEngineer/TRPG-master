from copy import deepcopy

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.seed import ensure_seed_content
from app.module_runtime import ModuleLoader, ModulePackageError
from app.service import room as room_service
from tests.helpers import ROOMS_BASE, create_room, reconnect


def test_paper_chase_is_the_only_loadable_development_module() -> None:
    runtime = ModuleLoader().load_default(allow_uncleared=True)

    assert runtime.package.package_schema_version == "1.1.0"
    assert runtime.package.module.title == "追书人"
    assert runtime.development_only is True
    assert runtime.entry_scene["id"] == runtime.package.module.entry_scene_id
    assert len(runtime.package.content.characters) == 2
    assert len(runtime.package.content.endings) == 6
    assert len(runtime.checksum) == 64


def test_uncleared_paper_chase_is_rejected_by_distribution_gate() -> None:
    with pytest.raises(ModulePackageError, match="rights are not cleared"):
        ModuleLoader().load_default(allow_uncleared=False)


async def test_production_catalog_hides_uncleared_module(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOW_UNCLEARED_MODULES", raising=False)
    get_settings.cache_clear()
    try:
        await ensure_seed_content(db_session)
        assert await room_service.list_modules(db_session) == []
    finally:
        get_settings.cache_clear()


def test_loader_rejects_broken_references_and_unregistered_effects() -> None:
    loader = ModuleLoader()
    runtime = loader.load_default(allow_uncleared=True)
    package = deepcopy(runtime.package_json)
    package["module"]["entry_scene_id"] = "scene.missing"
    package["content"]["checkpoints"][0]["on_success"].append(
        {"type": "keeper_rewrites_state"}
    )

    with pytest.raises(ModulePackageError) as exc_info:
        loader.load_dict(package, allow_uncleared=True)

    errors = "；".join(exc_info.value.errors)
    assert "module.entry_scene_id is missing" in errors
    assert "unregistered effect type keeper_rewrites_state" in errors


async def test_module_api_only_returns_player_safe_projection(client: AsyncClient) -> None:
    response = await client.get("/api/v1/modules")
    modules = response.json()["data"]

    assert response.status_code == 200
    assert len(modules) == 1
    assert modules[0]["title"] == "追书人"
    assert modules[0]["runtimeStatus"] == "ready"
    assert modules[0]["developmentOnly"] is True

    detail_response = await client.get(f"/api/v1/modules/{modules[0]['id']}")
    detail = detail_response.json()["data"]
    serialized = detail_response.text

    assert detail_response.status_code == 200
    assert detail["entryScene"]["playerDescription"]
    assert len(detail["pregens"]) == 2
    assert "keeperBrief" not in serialized
    assert "keeper_brief" not in serialized
    assert "packageJson" not in serialized
    assert '"content":' not in serialized


async def test_selecting_pregen_copies_a_complete_character_snapshot(
    client: AsyncClient,
) -> None:
    room = await create_room(client, max_players=1)
    module = (await client.get("/api/v1/modules")).json()["data"][0]
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module["id"]},
        headers=reconnect(room["reconnectToken"]),
    )
    detail = (
        await client.get(f"/api/v1/modules/{module['id']}")
    ).json()["data"]
    pregen = detail["pregens"][0]

    created = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnPregenId": pregen["id"]},
        headers=reconnect(room["reconnectToken"]),
    )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "complete"
    character_id = created.json()["data"]["characterId"]
    read_back = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        headers=reconnect(room["reconnectToken"]),
    )
    character = read_back.json()["data"]
    assert character["name"] == pregen["name"]
    assert character["occupation"] == pregen["occupation"]
    assert character["attributes"] == pregen["attributes"]
    assert character["skills"] == pregen["skills"]
    preview = await client.get(f"{ROOMS_BASE}/{room['roomCode']}")
    assert preview.json()["data"]["players"][0]["hasCharacter"] is True
