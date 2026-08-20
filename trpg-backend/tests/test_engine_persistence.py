"""Issue #89 的 ORM、约束与内置 ModuleVersion 测试。"""

from collaboration_framework.contracts import ModuleContentV3
from sqlalchemy import CheckConstraint, PrimaryKeyConstraint, String, UniqueConstraint, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.core.seed import (
    BUILTIN_MODULE_ID,
    BUILTIN_MODULE_VERSION,
    BUILTIN_SCENARIO_ID,
    BUILTIN_SYSTEM_ID,
    BUILTIN_WORLD_REF,
    ensure_seed_content,
)
from app.models.content import GameSystem, Scenario
from app.models.engine import ActionExecution, GameEvent, GameSession, ModuleVersion
from app.models.event import Event
from app.models.room import Character, Player, Room
from app.service.paper_chase_loader import load_paper_chase


def _constraint_names(table_name: str, constraint_type: type) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name is not None
    }


def test_engine_tables_and_constraints_are_registered() -> None:
    """create_all/Alembic autogenerate 能发现全部新模型及关键数据库不变式。"""
    assert {
        "module_versions",
        "game_sessions",
        "game_events",
        "action_executions",
        "pending_check_decisions",
        "check_runs",
        "adjudication_command_executions",
        "time_advance_proposals",
    }.issubset(Base.metadata.tables)
    assert "room_sessions" not in Base.metadata.tables

    module_versions = Base.metadata.tables["module_versions"]
    module_pk = next(
        constraint
        for constraint in module_versions.constraints
        if isinstance(constraint, PrimaryKeyConstraint)
    )
    assert [column.name for column in module_pk.columns] == ["module_id", "version"]
    assert isinstance(module_versions.c.module_id.type, String)
    assert {
        (foreign_key.parent.name, foreign_key.target_fullname)
        for foreign_key in module_versions.foreign_keys
    } == {("module_id", "scenarios.module_id")}

    scenarios = Base.metadata.tables["scenarios"]
    game_systems = Base.metadata.tables["game_systems"]
    assert scenarios.c.module_id.nullable is False
    assert game_systems.c.world_ref.nullable is False
    assert ("module_id",) in {
        tuple(constraint.columns.keys())
        for constraint in scenarios.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("world_ref",) in {
        tuple(constraint.columns.keys())
        for constraint in game_systems.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    game_sessions = Base.metadata.tables["game_sessions"]
    assert [column.name for column in game_sessions.primary_key.columns] == ["room_id"]
    assert {
        tuple(column.name for column in constraint.columns)
        for constraint in game_sessions.foreign_key_constraints
    } == {("room_id",), ("module_id", "module_version")}

    assert "uq_game_events_room_event" in _constraint_names("game_events", UniqueConstraint)
    assert "ck_game_events_visibility" in _constraint_names("game_events", CheckConstraint)
    assert {
        tuple(index.columns.keys()) for index in Base.metadata.tables["game_events"].indexes
    } == {("room_id", "client_action_id")}

    assert "uq_characters_room_player" in _constraint_names("characters", UniqueConstraint)
    assert "ck_characters_version_positive" in _constraint_names("characters", CheckConstraint)
    assert "ck_scenarios_status" in _constraint_names("scenarios", CheckConstraint)
    assert "uq_events_room_type_correlation" in _constraint_names("events", UniqueConstraint)
    assert Base.metadata.tables["events"].c.correlation_id.nullable


async def test_seed_only_creates_wip_catalog_and_ruleset(db_session: AsyncSession) -> None:
    await db_session.execute(delete(ModuleVersion))
    await db_session.execute(delete(Scenario))
    await db_session.commit()

    await ensure_seed_content(db_session)

    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    module_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    system = await db_session.get(GameSystem, BUILTIN_SYSTEM_ID)

    assert scenario is not None
    assert scenario.module_id == BUILTIN_MODULE_ID
    assert scenario.status == "wip"
    assert scenario.version == BUILTIN_MODULE_VERSION
    assert scenario.story_pages == []
    assert system is not None
    assert system.world_ref == BUILTIN_WORLD_REF
    assert module_version is None


async def test_loader_persists_valid_playable_module_version(db_session: AsyncSession) -> None:
    scenario = await db_session.get(Scenario, BUILTIN_SCENARIO_ID)
    module_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert scenario is not None
    assert scenario.status == "ready"
    assert module_version is not None
    publication = ModuleContentV3.model_validate(module_version.content_json)
    assert publication.module_id == BUILTIN_MODULE_ID
    assert publication.module_id == module_version.module_id
    assert publication.version == module_version.version
    assert publication.world_ref == module_version.world_ref
    assert publication.world_ref == BUILTIN_WORLD_REF
    assert len(publication.locations) == 12
    assert len(publication.entities) == 15
    assert publication.background
    assert publication.presentation is not None
    assert publication.presentation.players_min == 1
    assert publication.presentation.players_max == 1

    await db_session.commit()
    repeated = await load_paper_chase(db_session)
    assert repeated.outcome == "unchanged"


async def test_seed_does_not_overwrite_published_module_content(
    db_session: AsyncSession,
) -> None:
    """重复 seed 可更新目录数据，但不能原地修改已发布版本。"""
    module_version = await db_session.get(
        ModuleVersion,
        (BUILTIN_MODULE_ID, BUILTIN_MODULE_VERSION),
    )
    assert module_version is not None
    existing_publication = dict(module_version.content_json)
    locations = list(existing_publication["locations"])
    locations[0] = {
        **locations[0],
        "player_visible_description": "已经发布、不得被 seed 覆盖的内容。",
    }
    existing_publication["locations"] = locations
    ModuleContentV3.model_validate(existing_publication)
    module_version.content_json = existing_publication
    await db_session.commit()

    await ensure_seed_content(db_session)
    await db_session.refresh(module_version)

    assert module_version.content_json == existing_publication


async def test_character_room_player_and_version_constraints(
    db_session: AsyncSession,
) -> None:
    room_id = "10000000-0000-0000-0000-000000000001"
    room = Room(
        id=room_id,
        room_code="DB0089",
        room_name="数据库约束测试",
        max_players=4,
    )
    player = Player(
        id="10000000-0000-0000-0000-000000000002",
        room_id=room_id,
        nickname="调查员",
    )
    db_session.add_all(
        [
            room,
            player,
            Character(
                id="10000000-0000-0000-0000-000000000003",
                room_id=room_id,
                player_id=player.id,
            ),
        ]
    )
    await db_session.commit()

    db_session.add(
        Character(
            id="10000000-0000-0000-0000-000000000004",
            room_id=room_id,
            player_id=player.id,
        )
    )
    try:
        await db_session.commit()
        raise AssertionError("数据库必须拒绝同一 Room/Player 的第二张 Character")
    except IntegrityError:
        await db_session.rollback()

    other_player = Player(
        id="10000000-0000-0000-0000-000000000005",
        room_id=room_id,
        nickname="第二位调查员",
    )
    db_session.add_all(
        [
            other_player,
            Character(
                id="10000000-0000-0000-0000-000000000006",
                room_id=room_id,
                player_id=other_player.id,
                version=0,
            ),
        ]
    )
    try:
        await db_session.commit()
        raise AssertionError("数据库必须拒绝小于 1 的 Character.version")
    except IntegrityError:
        await db_session.rollback()


async def test_event_correlation_deduplicates_action_narration_only(
    db_session: AsyncSession,
) -> None:
    """同一动作叙事至多落一条；无关联键的历史/普通事件仍可重复。"""
    room_id = "40000000-0000-0000-0000-000000000001"
    db_session.add(
        Room(
            id=room_id,
            room_code="EV0089",
            room_name="事件去重测试",
            max_players=4,
        )
    )
    db_session.add(
        Event(
            id="40000000-0000-0000-0000-000000000002",
            room_id=room_id,
            event_type="narration.push",
            correlation_id="client-action-89",
            visibility="public",
            payload={"content": "首次叙事"},
        )
    )
    await db_session.commit()

    db_session.add(
        Event(
            id="40000000-0000-0000-0000-000000000003",
            room_id=room_id,
            event_type="narration.push",
            correlation_id="client-action-89",
            visibility="public",
            payload={"content": "不得重复的叙事"},
        )
    )
    try:
        await db_session.commit()
        raise AssertionError("数据库必须拒绝同一动作产生的重复 narration.push")
    except IntegrityError:
        await db_session.rollback()

    db_session.add_all(
        [
            Event(
                id="40000000-0000-0000-0000-000000000004",
                room_id=room_id,
                event_type="narration.push",
                correlation_id=None,
                visibility="public",
                payload={"content": "普通叙事一"},
            ),
            Event(
                id="40000000-0000-0000-0000-000000000005",
                room_id=room_id,
                event_type="narration.push",
                correlation_id=None,
                visibility="public",
                payload={"content": "普通叙事二"},
            ),
        ]
    )
    await db_session.commit()


def test_engine_models_are_publicly_exported() -> None:
    """集中导出保持可发现，并且不再导出 RoomSession。"""
    import app.models as models

    assert models.ModuleVersion is ModuleVersion
    assert models.GameSession is GameSession
    assert models.GameEvent is GameEvent
    assert models.ActionExecution is ActionExecution
    assert not hasattr(models, "RoomSession")
