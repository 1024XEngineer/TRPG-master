import json
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import (
    BUILTIN_MODULE_ID,
    BUILTIN_MODULE_VERSION,
    BUILTIN_SCENARIO_ID,
    BUILTIN_SYSTEM_ID,
)
from app.models.content import GameSystem, Scenario
from app.models.engine import ModuleVersion
from app.service import paper_chase_loader as loader


async def test_loader_is_idempotent_and_reports_real_content(
    db_session: AsyncSession,
) -> None:
    result = await loader.load_paper_chase(db_session)

    assert result.outcome == "unchanged"
    assert result.module_id == BUILTIN_MODULE_ID
    assert result.version == "3.0.6"
    assert result.world_ref == "coc-7e"
    assert result.location_count == 12
    assert result.entity_count == 15
    assert result.information_count == 9
    assert result.rule_count == 27
    assert result.ending_anchor_count == 4
    assert "result: unchanged" in result.summary_lines()

    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert scenario is not None
    assert scenario.title == "追书人"
    assert scenario.story_pages[0]["title"] == "调查委托"
    assert "被盗的五本珍藏旧书" in scenario.story_pages[0]["content"]


async def test_paper_chase_models_caretaker_bottle_as_discoverable_state() -> None:
    """看守兜里的酒瓶不能是"看一眼就知道"的公开描述。

    初始投影不能泄露酒瓶；observe_caretaker 成功后一方面翻开
    `state.bottle_noticed`，另一方面发布玩家可见线索，使 Narrator 有安全正文
    可以明确叙述检定收获。
    """

    payload = json.loads(loader.PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == "3.0.6"
    entities = {entity["id"]: entity for entity in payload["entities"]}
    information = {item["id"]: item for item in payload["information"]}
    rules = {rule["id"]: rule for rule in payload["rules"]}

    assert "caretaker_bottle" not in entities
    melodias = entities["melodias"]
    assert melodias["state"]["bottle_noticed"] is False
    assert "玻璃瓶" not in melodias["description"]
    assert "瓶" not in melodias["description"]

    observe = rules["observe_caretaker"]
    assert observe["trigger"]["scope"]["target_ids"] == ["melodias"]
    assert "bottle_noticed" in json.dumps(observe["execution"], ensure_ascii=False)
    assert "melodias_pocket_bottle" in json.dumps(observe["execution"], ensure_ascii=False)
    bottle_clue = information["melodias_pocket_bottle"]
    assert "小酒瓶" in bottle_clue["player_content"]
    assert "小酒瓶" in bottle_clue["keeper_content"]


def test_paper_chase_keeps_previous_v2_snapshots() -> None:
    """切到 v3 不删旧快照——已经开局的房间可能还钉在某个 v2 版本上。"""

    current = json.loads(loader.PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8"))
    assert current["version"] == "3.0.6"
    assert current["content_schema_version"] == 3

    for name, version in (
        ("module-content-draft.json", "1.0.5"),
        ("module-content-1.0.4.json", "1.0.4"),
        ("module-content-1.0.1.json", "1.0.1"),
    ):
        snapshot_path = loader.PAPER_CHASE_SOURCE_PATH.with_name(name)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["version"] == version
        assert snapshot["module_id"] == current["module_id"]


async def test_loader_projects_player_safe_presentation_to_catalog(
    db_session: AsyncSession,
) -> None:
    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert scenario is not None
    assert scenario.status == "ready"
    assert scenario.title == "追书人"
    assert scenario.name_en == "Paper Chase"
    assert scenario.players_min == 1
    assert scenario.players_max == 1
    assert scenario.story_pages
    text = " ".join(page["content"] for page in scenario.story_pages)
    assert "食尸鬼" not in text
    assert "地穴" not in text


async def test_loader_rejects_other_identity_without_database_changes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = json.loads(loader.PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8"))
    payload["module_id"] = "some-other-module"
    source = tmp_path / "other-module.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(loader, "PAPER_CHASE_SOURCE_PATH", source)

    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    module_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert scenario is not None
    assert module_version is not None
    assert module_version.content_schema_version == 3
    original_content = module_version.content_json
    await db_session.commit()

    with pytest.raises(loader.PaperChaseLoadError, match="身份不匹配"):
        await loader.load_paper_chase(db_session)

    db_session.expire_all()
    unchanged_scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    unchanged_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert unchanged_scenario is not None
    assert unchanged_scenario.status == "ready"
    assert unchanged_version is not None
    assert unchanged_version.content_json == original_content


async def test_loader_rejects_validation_failure_before_writing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = json.loads(loader.PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8"))
    payload["rules"][0]["trigger"]["scope"]["location_ids"] = ["no-such-location"]
    source = tmp_path / "invalid-paper-chase.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(loader, "PAPER_CHASE_SOURCE_PATH", source)

    with pytest.raises(loader.PaperChaseLoadError, match="Validation 未通过"):
        await loader.load_paper_chase(db_session)

    assert (
        await db_session.get(
            ModuleVersion,
            (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
        )
        is not None
    )


async def test_loader_does_not_overwrite_different_immutable_version(
    db_session: AsyncSession,
) -> None:
    module_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert module_version is not None
    changed_content = dict(module_version.content_json)
    changed_content["background"] = "同版本的另一份内容"
    module_version.content_json = changed_content
    await db_session.commit()

    with pytest.raises(loader.PaperChaseLoadError, match="不会静默覆盖"):
        await loader.load_paper_chase(db_session)

    db_session.expire_all()
    unchanged = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert unchanged is not None
    assert unchanged.content_json == changed_content


async def test_loader_preserves_rooms_pinned_legacy_version(
    db_session: AsyncSession,
) -> None:
    current = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert current is not None
    legacy_path = loader.PAPER_CHASE_SOURCE_PATH.with_name("module-content-1.0.1.json")
    legacy_content = json.loads(legacy_path.read_text(encoding="utf-8"))
    db_session.add(
        ModuleVersion(
            module_id=BUILTIN_MODULE_ID,
            version="1.0.1",
            world_ref=current.world_ref,
            content_schema_version=1,
            content_json=legacy_content,
        )
    )
    await db_session.commit()

    result = await loader.load_paper_chase(db_session)

    assert result.version == "3.0.6"
    legacy = await db_session.get(ModuleVersion, (BUILTIN_MODULE_ID, "1.0.1"))
    assert legacy is not None
    assert legacy.content_json == legacy_content


async def test_loader_rolls_back_module_and_ready_status_together(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        delete(ModuleVersion).where(
            ModuleVersion.module_id == BUILTIN_MODULE_ID,
            ModuleVersion.version == BUILTIN_MODULE_VERSION,
        )
    )
    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert scenario is not None
    scenario.status = "wip"
    await db_session.commit()

    def fail_before_commit() -> None:
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        await loader.load_paper_chase(db_session, _before_commit=fail_before_commit)

    db_session.expire_all()
    rolled_back_scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert rolled_back_scenario is not None
    assert rolled_back_scenario.status == "wip"
    assert (
        await db_session.get(
            ModuleVersion,
            (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
        )
        is None
    )


async def test_loader_requires_database_ruleset_without_partial_write(
    db_session: AsyncSession,
) -> None:
    system = await db_session.get(GameSystem, BUILTIN_SYSTEM_ID)
    assert system is not None
    system.ruleset = None
    await db_session.commit()

    with pytest.raises(loader.PaperChaseLoadError, match="Ruleset 为空"):
        await loader.load_paper_chase(db_session)

    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert scenario is not None
    assert scenario.status == "ready"
