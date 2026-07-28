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
    assert result.version == BUILTIN_MODULE_VERSION
    assert result.world_ref == "coc-7e"
    assert result.scene_count == 11
    assert result.entity_count == 16
    assert result.checkpoint_count == 20
    assert result.rule_count >= 9
    assert result.win_condition_count == 4
    assert "result: unchanged" in result.summary_lines()

    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    assert scenario is not None
    assert scenario.title == "追书人"
    assert scenario.story_pages[0]["title"] == "托马斯的会客室"
    assert "失窃藏书" in scenario.story_pages[0]["content"]
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
    payload["checkpoints"][0]["skills"] = ["not-a-coc7-skill"]
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
