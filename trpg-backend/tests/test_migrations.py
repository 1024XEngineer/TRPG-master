"""Issue #89 Alembic 升降级与历史数据保护测试。"""

import json
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "1a02058345ee"
ENGINE_IDENTITY_PREVIOUS_REVISION = "9c4e7a2b1d6f"
# PR2 NPC 对话迁移（d1e2f3a4b5c6）接在 PR1 输入路由 head 后面；#398 的检定唯一
# 约束放宽（b8c9d0e1f2a3）再接在它之后，最后是模组快照的死字段剥离。
# 记忆投影与时间点回填各自形成分支后，由空迁移重新汇合为单一 head。
HEAD_REVISION = "b3d6f9a2c4e7"


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


def _index_names(database: Path, table: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA index_list('{table}')")}


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
        "host_action_queue",
        "event_audiences",
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
    assert ("room_id", "client_action_id") in _unique_column_sets(database, "host_action_queue")
    assert {
        "recipient_kind",
        "recipient_entity_id",
        "recipient_explicit",
        "attempt_count",
        "next_attempt_at",
        "lease_owner",
        "lease_expires_at",
        "result_event_ids",
    }.issubset(_column_names(database, "host_action_queue"))
    assert "entity_id" in _column_names(database, "module_assets")
    assert {"channel", "actor_id"}.issubset(_column_names(database, "chat_messages"))
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
    assert "audience_player_ids" in _column_names(database, "memory_entries")

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
    # #398：「一个动作至多一次检定」放宽为「至多一次**未结算**的检定」，
    # 规则要能在动作的效果链中间再要求一次被动检定。
    indexes = _index_names(database, "pending_check_decisions")
    assert "uq_pending_check_decisions_room_action" not in indexes
    assert "uq_pending_check_decisions_room_action_open" in indexes


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


def test_message_channel_and_recipient_migration_backfills_old_rows(tmp_path: Path) -> None:
    """PR1 迁移必须让既有讨论消息和主持队列继续保持原来的语义。"""

    database = tmp_path / "message-recipient-backfill.db"
    _upgrade_or_fail(database, "b9c0d1e2f3a4")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (
                id, room_id, player_id, client_message_id, text, created_at
            ) VALUES (
                '80000000-0000-0000-0000-000000000001',
                'room-1', 'player-1', 'old-chat', '旧讨论消息', '2026-08-23 00:00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO host_action_queue (
                room_id, item_id, client_action_id, player_id, actor_id,
                utterance, position, status, created_at, updated_at
            ) VALUES (
                'room-1', 'old-item', 'old-action', 'player-1', 'actor-1',
                '旧主持行动', 1, 'queued',
                '2026-08-23 00:00:00', '2026-08-23 00:00:00'
            )
            """
        )

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        chat = connection.execute(
            "SELECT channel, actor_id FROM chat_messages WHERE client_message_id = 'old-chat'"
        ).fetchone()
        recipient = connection.execute(
            """
            SELECT recipient_kind, recipient_entity_id, recipient_explicit
            FROM host_action_queue WHERE client_action_id = 'old-action'
            """
        ).fetchone()

    assert chat == ("discussion", None)
    assert recipient == ("keeper", None, 1)


def test_npc_dialogue_migration_backfills_started_queue(tmp_path: Path) -> None:
    """PR2 把旧 started 收敛为不可重复执行的 completed，并初始化恢复字段。"""

    database = tmp_path / "npc-dialogue-backfill.db"
    _upgrade_or_fail(database, "c0d1e2f3a4b5")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO host_action_queue (
                room_id, item_id, client_action_id, player_id, actor_id,
                utterance, recipient_kind, recipient_entity_id,
                recipient_explicit, position, status, created_at, updated_at
            ) VALUES (
                'room-1', 'old-started', 'old-started-action', 'player-1', 'actor-1',
                '已经由旧服务接管', 'keeper', NULL, 1, 1, 'started',
                '2026-08-23 00:00:00', '2026-08-23 00:00:00'
            )
            """
        )

    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT status, attempt_count, result_event_ids
            FROM host_action_queue WHERE item_id = 'old-started'
            """
        ).fetchone()

    assert row == ("completed", 0, "[]")


def test_npc_dialogue_downgrade_keeps_scene_events_private(tmp_path: Path) -> None:
    """旧版本不支持冻结受众时，降级只能收窄到发起玩家，不能扩大为公开事件。"""

    database = tmp_path / "npc-dialogue-downgrade.db"
    _upgrade_or_fail(database, "head")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, room_id, player_id, event_type, payload, visibility, created_at
            ) VALUES (
                '90000000-0000-0000-0000-000000000001',
                'room-1', 'player-1', 'dialogue.player', '{}', 'scene_scoped',
                '2026-08-24 00:00:00'
            )
            """
        )

    result = _run_alembic(database, "downgrade", "c0d1e2f3a4b5")
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(database) as connection:
        visibility = connection.execute(
            "SELECT visibility FROM events WHERE event_type = 'dialogue.player'",
        ).fetchone()
    assert visibility == ("player_scoped",)


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


def test_time_point_backfill_makes_old_snapshots_reload_unchanged(
    tmp_path: Path,
) -> None:
    """旧格式模组快照跑完迁移后，加载器必须判定 unchanged（#415）。

    #415 给 TimePointSpec 加了 time_segment / label，给 ModuleTimePolicySpec
    加了 terminal_point。三个都可选，所以旧快照解析没问题——但内置模组加载器
    比的是**整份归一化 JSON**，新代码会把这三个字段写成 null，比对不等就抛
    BuiltinModuleLoadError，后端 lifespan 起不来。

    这条测试守的正是那条升级路径：pytest 平时在临时空库上 create_all，
    migration job 在全新容器上跑，两者都只覆盖「全新建库」，撞不到这个 bug。
    """

    from collaboration_framework.contracts import ModuleContentV3

    database = tmp_path / "time-point-backfill.db"
    _upgrade_or_fail(database, "f7b9c2d4e6a8")

    fixture = (
        Path(__file__).resolve().parents[2]
        / "agent-collaboration-framework"
        / "docs"
        / "module-parser"
        / "examples"
        / "module-content-validation"
        / "银之锁"
        / "module-content-v3.json"
    )
    fresh = ModuleContentV3.model_validate_json(fixture.read_text(encoding="utf-8"))
    normalized = fresh.to_json_dict()

    # 造出「扩字段之前」序列化出来的形状：把三个新键摘掉。
    legacy = deepcopy(normalized)
    for point in legacy["time_policy"]["default_points"]:
        del point["time_segment"]
        del point["label"]
    del legacy["time_policy"]["terminal_point"]
    assert legacy != normalized

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO scenarios (
                id, module_id, game_system_id, title, version, authors,
                players_min, players_max, difficulty, status, created_at, updated_at
            ) VALUES (
                '90000000-0000-0000-0000-000000000001', 'legacy-time-module',
                '90000000-0000-0000-0000-000000000002', '旧快照', '1.0.0', '[]',
                1, 4, 1, 'ready', '2026-08-25 00:00:00', '2026-08-25 00:00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO module_versions (
                module_id, version, world_ref, content_schema_version,
                content_json, created_at
            ) VALUES (
                'legacy-time-module', '1.0.0', 'coc-7e', 3, ?,
                '2026-08-25 00:00:00'
            )
            """,
            (json.dumps(legacy, ensure_ascii=False),),
        )

    _upgrade_or_fail(database, "head")

    with sqlite3.connect(database) as connection:
        stored = json.loads(
            connection.execute(
                "SELECT content_json FROM module_versions WHERE module_id = 'legacy-time-module'"
            ).fetchone()[0]
        )

    # 这就是加载器那一步比较：迁移后必须完全相等，否则 lifespan 抛
    # BuiltinModuleLoadError。
    assert stored == normalized
