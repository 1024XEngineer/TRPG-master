"""Issue #89 Alembic 升降级与历史数据保护测试。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "1a02058345ee"
ENGINE_IDENTITY_PREVIOUS_REVISION = "9c4e7a2b1d6f"
# 记忆与 main 分支的模组迁移通过 merge migration 汇合为当前 head。
HEAD_REVISION = "a7b8c9d0e1f2"


def _run_alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _upgrade_or_fail(database: Path, revision: str) -> None:
    result = _run_alembic(database, "upgrade", revision)
    assert result.returncode == 0, result.stdout + result.stderr


def _table_names(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def _column_names(database: Path, table: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info('{table}')")}


def _unique_column_sets(database: Path, table: str) -> set[tuple[str, ...]]:
    with sqlite3.connect(database) as connection:
        unique_indexes = [
            row[1] for row in connection.execute(f"PRAGMA index_list('{table}')") if row[2]
        ]
        return {
            tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{index_name}')"))
            for index_name in unique_indexes
        }


def _foreign_keys(database: Path, table: str) -> set[tuple[str, str, str]]:
    with sqlite3.connect(database) as connection:
        return {
            (row[3], row[2], row[4])
            for row in connection.execute(f"PRAGMA foreign_key_list('{table}')")
        }


def test_migration_upgrades_empty_sqlite_and_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "round-trip.db"

    _upgrade_or_fail(database, "head")
    tables = _table_names(database)
    assert {
        "module_versions",
        "game_sessions",
        "game_events",
        "action_executions",
        "pending_check_decisions",
        "check_runs",
        "adjudication_command_executions",
        "action_plan_runs",
        "room_action_reservations",
        "inventory_import_drafts",
        "inventory_command_executions",
        "ending_drafts",
        "ending_command_executions",
        "character_portraits",
        "user_character_template_portraits",
        "portrait_generation_tasks",
        "time_advance_proposals",
        "memory_entries",
        "conversation_summaries",
        "memory_projection_cursors",
        "turn_run_cutover",
        "scene_transition_proposals",
    }.issubset(tables)
    assert "decision_schema_version" in _column_names(
        database,
        "pending_check_decisions",
    )
    assert "check_schema_version" in _column_names(database, "check_runs")
    assert {"request_schema_version", "result_schema_version"}.issubset(
        _column_names(database, "adjudication_command_executions")
    )
    assert "action_request_id" in _column_names(
        database,
        "adjudication_command_executions",
    )
    assert "request_json" in _column_names(database, "inventory_import_drafts")
    assert "agenda_state_version" in _column_names(database, "game_sessions")
    assert {"run_version", "run_json", "lease_owner", "lease_expires_at"}.issubset(
        _column_names(database, "action_plan_runs")
    )
    assert ("room_id",) in _unique_column_sets(database, "room_action_reservations")
    assert "room_sessions" not in tables
    assert {"status", "name_en", "story_label", "subtitle", "story_pages"}.issubset(
        _column_names(database, "scenarios")
    )
    assert "module_id" in _column_names(database, "scenarios")
    assert "world_ref" in _column_names(database, "game_systems")
    assert "tags" in _column_names(database, "games")
    assert ("module_id",) in _unique_column_sets(database, "scenarios")
    assert ("world_ref",) in _unique_column_sets(database, "game_systems")
    assert ("module_id", "scenarios", "module_id") in _foreign_keys(database, "module_versions")
    assert {
        ("module_id", "module_versions", "module_id"),
        ("module_version", "module_versions", "version"),
    }.issubset(_foreign_keys(database, "game_sessions"))
    assert "module_version" in _column_names(database, "rooms")
    assert "host_speech_voice_type" in _column_names(database, "rooms")
    assert "version" in _column_names(database, "characters")
    assert "occupation_choice_skill_ids" in _column_names(database, "characters")
    assert {
        "character_id",
        "content",
        "content_type",
        "size_bytes",
        "content_hash",
        "created_at",
        "updated_at",
    } == _column_names(database, "character_portraits")
    assert (
        "character_id",
        "characters",
        "id",
    ) in _foreign_keys(database, "character_portraits")
    assert {
        "template_id",
        "content",
        "content_type",
        "size_bytes",
        "content_hash",
        "created_at",
        "updated_at",
    } == _column_names(database, "user_character_template_portraits")
    assert (
        "template_id",
        "user_character_templates",
        "id",
    ) in _foreign_keys(database, "user_character_template_portraits")
    assert {
        "generation_id",
        "character_id",
        "status",
        "cancel_requested",
        "portrait_version",
    }.issubset(_column_names(database, "portrait_generation_tasks"))
    assert ("character_id",) in _unique_column_sets(database, "portrait_generation_tasks")
    assert "correlation_id" in _column_names(database, "events")
    assert {
        "visibility",
        "actor_id",
        "scene_id",
        "view_revision",
    }.issubset(_column_names(database, "events"))
    assert ("room_id", "event_type", "correlation_id") in _unique_column_sets(database, "events")
    assert "source_created_at" in _column_names(database, "memory_entries")

    downgrade = _run_alembic(database, "downgrade", PREVIOUS_REVISION)
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    assert "room_sessions" in _table_names(database)
    assert "module_versions" not in _table_names(database)
    assert "version" not in _column_names(database, "characters")
    assert "occupation_choice_skill_ids" not in _column_names(database, "characters")
    assert "character_portraits" not in _table_names(database)
    assert "user_character_template_portraits" not in _table_names(database)
    assert "correlation_id" not in _column_names(database, "events")

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == (HEAD_REVISION,)


def test_recent_history_migration_backfills_visibility_conservatively(
    tmp_path: Path,
) -> None:
    database = tmp_path / "recent-history-backfill.db"
    _upgrade_or_fail(database, "2e4d6c7a8b90")
    rows = [
        ("70000000-0000-0000-0000-000000000001", "action.broadcast", "a", "player-1"),
        ("70000000-0000-0000-0000-000000000002", "check.result", "b", "player-1"),
        ("70000000-0000-0000-0000-000000000003", "narration.push", None, None),
        ("70000000-0000-0000-0000-000000000004", "narration.push", "c", "player-1"),
        ("70000000-0000-0000-0000-000000000005", "unknown", "d", "player-1"),
        ("70000000-0000-0000-0000-000000000006", "unknown", "e", None),
    ]
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO events (
                id, room_id, player_id, event_type, correlation_id, payload, created_at
            ) VALUES (?, 'room-1', ?, ?, ?, '{}', '2026-07-29 00:00:00')
            """,
            [
                (event_id, player_id, event_type, correlation_id)
                for event_id, event_type, correlation_id, player_id in rows
            ],
        )

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        visibility = dict(
            connection.execute("SELECT id, visibility FROM events ORDER BY id").fetchall()
        )
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('events')")}
        try:
            connection.execute(
                """
                INSERT INTO events (
                    id, room_id, player_id, event_type, correlation_id,
                    visibility, payload, created_at
                ) VALUES (
                    '70000000-0000-0000-0000-000000000007',
                    'room-1', NULL, 'check.result', 'f',
                    'player_scoped', '{}', '2026-07-29 00:00:00'
                )
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("player_scoped event without player_id must fail")

    assert list(visibility.values()) == [
        "public",
        "player_scoped",
        "public",
        "player_scoped",
        "player_scoped",
        "public",
    ]
    assert {
        "ix_events_room_created",
        "ix_events_room_visibility_player_created",
    }.issubset(indexes)


def test_migration_rejects_duplicate_characters_before_ddl(tmp_path: Path) -> None:
    database = tmp_path / "duplicate-characters.db"
    _upgrade_or_fail(database, PREVIOUS_REVISION)

    with sqlite3.connect(database) as connection:
        rows = [
            (
                f"20000000-0000-0000-0000-00000000000{index}",
                "room-1",
                "player-1",
                "draft",
                "pointbuy",
                "",
                "",
                "2026-07-23 00:00:00",
                "2026-07-23 00:00:00",
            )
            for index in (1, 2)
        ]
        connection.executemany(
            """
            INSERT INTO characters (
                id, room_id, player_id, status, generation_method,
                background, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    result = _run_alembic(database, "upgrade", "head")

    assert result.returncode != 0
    assert "characters 存在重复" in result.stdout + result.stderr
    assert "version" not in _column_names(database, "characters")
    assert "module_versions" not in _table_names(database)


def test_migration_rejects_nonempty_room_sessions_before_ddl(tmp_path: Path) -> None:
    database = tmp_path / "room-sessions.db"
    _upgrade_or_fail(database, PREVIOUS_REVISION)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO room_sessions (
                id, room_id, status, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                "30000000-0000-0000-0000-000000000001",
                "room-1",
                "active",
                "2026-07-23 00:00:00",
            ),
        )

    result = _run_alembic(database, "upgrade", "head")

    assert result.returncode != 0
    assert "room_sessions 存在历史数据" in result.stdout + result.stderr
    assert "room_sessions" in _table_names(database)
    assert "status" not in _column_names(database, "scenarios")


def test_module_identity_migration_rejects_existing_catalog_data(tmp_path: Path) -> None:
    database = tmp_path / "existing-catalog.db"
    _upgrade_or_fail(database, ENGINE_IDENTITY_PREVIOUS_REVISION)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO games (id, name, created_at)
            VALUES (?, ?, ?)
            """,
            (
                "40000000-0000-0000-0000-000000000001",
                "历史游戏",
                "2026-07-25 00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO game_systems (id, game_id, name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "40000000-0000-0000-0000-000000000002",
                "40000000-0000-0000-0000-000000000001",
                "历史规则系统",
                "2026-07-25 00:00:00",
            ),
        )

    result = _run_alembic(database, "upgrade", "head")

    assert result.returncode != 0
    assert "game_systems 存在历史数据" in result.stdout + result.stderr
    assert "world_ref" not in _column_names(database, "game_systems")
    assert "module_id" not in _column_names(database, "scenarios")


def test_memory_source_time_reconciliation_repairs_stamped_database(tmp_path: Path) -> None:
    """数据库已标记旧 head 但缺列时，新迁移仍能补列、回填数据并创建索引。"""
    database = tmp_path / "memory-source-time-drift.db"
    _upgrade_or_fail(database, "f6a7b8c9d0e1")

    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX ix_memory_entries_room_source_created")
        connection.execute("ALTER TABLE memory_entries DROP COLUMN source_created_at")
        connection.execute(
            """
            INSERT INTO memory_entries (
                id, room_id, subject_id, kind, content, epistemic_status,
                visibility, participants, listener_ids, source_event_id,
                source_sequence, created_at
            ) VALUES (
                '10000000000000000000000000000001',
                '10000000000000000000000000000002',
                'actor_1', 'action', '历史行动', 'asserted', 'public',
                '[]', '[]', 'event-1', 0, '2026-08-20 12:34:56'
            )
            """
        )

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        source_created_at = connection.execute(
            "SELECT source_created_at FROM memory_entries WHERE source_event_id = 'event-1'"
        ).fetchone()
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('memory_entries')")}
    assert source_created_at == ("2026-08-20 12:34:56",)
    assert "ix_memory_entries_room_source_created" in indexes
