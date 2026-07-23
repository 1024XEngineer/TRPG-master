"""Issue #89 Alembic 升降级与历史数据保护测试。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "1a02058345ee"
HEAD_REVISION = "9c4e7a2b1d6f"


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


def test_migration_upgrades_empty_sqlite_and_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "round-trip.db"

    _upgrade_or_fail(database, "head")
    tables = _table_names(database)
    assert {
        "module_versions",
        "game_sessions",
        "game_events",
        "action_executions",
    }.issubset(tables)
    assert "room_sessions" not in tables
    assert {"status", "name_en", "story_label", "subtitle", "story_pages"}.issubset(
        _column_names(database, "scenarios")
    )
    assert "module_version" in _column_names(database, "rooms")
    assert "version" in _column_names(database, "characters")
    assert "correlation_id" in _column_names(database, "events")
    assert ("room_id", "event_type", "correlation_id") in _unique_column_sets(database, "events")

    downgrade = _run_alembic(database, "downgrade", PREVIOUS_REVISION)
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    assert "room_sessions" in _table_names(database)
    assert "module_versions" not in _table_names(database)
    assert "version" not in _column_names(database, "characters")
    assert "correlation_id" not in _column_names(database, "events")

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == (HEAD_REVISION,)


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
