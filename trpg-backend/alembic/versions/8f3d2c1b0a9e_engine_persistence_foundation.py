"""engine persistence foundation

Revision ID: 8f3d2c1b0a9e
Revises: 1a02058345ee
Create Date: 2026-07-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3d2c1b0a9e"
down_revision: str | Sequence[str] | None = "1a02058345ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _guard_existing_data() -> None:
    """在任何 DDL 前拒绝会被唯一约束或删表破坏的历史数据。"""
    connection = op.get_bind()

    duplicate_character = (
        connection.execute(
            sa.text(
                """
            SELECT room_id, player_id, COUNT(*) AS character_count
            FROM characters
            GROUP BY room_id, player_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
            )
        )
        .mappings()
        .first()
    )
    if duplicate_character is not None:
        raise RuntimeError(
            "迁移已中止：characters 存在重复的 (room_id, player_id)，"
            "请先人工合并角色卡；不会静默删除或覆盖数据。"
        )

    room_session = (
        connection.execute(sa.text("SELECT id, room_id FROM room_sessions LIMIT 1"))
        .mappings()
        .first()
    )
    if room_session is not None:
        raise RuntimeError(
            "迁移已中止：room_sessions 存在历史数据，请先人工制定迁移方案；"
            "不会静默删除历史游戏记录。"
        )


def upgrade() -> None:
    """增加规则引擎基础表，并安全调整现有目录与运行时表。"""
    _guard_existing_data()

    op.add_column(
        "scenarios",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'wip'"),
        ),
    )
    op.add_column("scenarios", sa.Column("name_en", sa.String(length=200), nullable=True))
    op.add_column("scenarios", sa.Column("story_label", sa.String(length=100), nullable=True))
    op.add_column("scenarios", sa.Column("subtitle", sa.String(length=200), nullable=True))
    op.add_column(
        "scenarios",
        sa.Column(
            "story_pages",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.create_check_constraint(
            "ck_scenarios_status",
            "status IN ('wip', 'ready', 'hidden')",
        )

    op.add_column("rooms", sa.Column("module_version", sa.String(length=50), nullable=True))

    op.add_column(
        "characters",
        sa.Column(
            "version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    # SQLite 不支持直接 ADD CONSTRAINT，batch 模式会安全地重建表；PostgreSQL
    # 上保持等价 ALTER 语义。脏数据已经在 DDL 前由 _guard_existing_data 拒绝。
    with op.batch_alter_table("characters") as batch_op:
        batch_op.create_unique_constraint(
            "uq_characters_room_player",
            ["room_id", "player_id"],
        )
        batch_op.create_check_constraint(
            "ck_characters_version_positive",
            "version >= 1",
        )

    op.drop_table("room_sessions")

    op.create_table(
        "module_versions",
        sa.Column("module_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("world_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "content_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_schema_version >= 1",
            name="ck_module_versions_content_schema_version",
        ),
        sa.ForeignKeyConstraint(["module_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("module_id", "version", name="pk_module_versions"),
    )
    op.create_table(
        "game_sessions",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("module_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("module_version", sa.String(length=50), nullable=False),
        sa.Column(
            "state_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column(
            "state_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state_schema_version >= 1",
            name="ck_game_sessions_state_schema_version",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_game_sessions_state_version",
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "module_version"],
            ["module_versions.module_id", "module_versions.version"],
            name="fk_game_sessions_module_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("room_id"),
    )
    op.create_table(
        "game_events",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("client_action_id", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column(
            "event_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_game_events_sequence"),
        sa.CheckConstraint(
            "event_schema_version >= 1",
            name="ck_game_events_event_schema_version",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'private', 'hidden')",
            name="ck_game_events_visibility",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "sequence", name="pk_game_events"),
        sa.UniqueConstraint("room_id", "event_id", name="uq_game_events_room_event"),
    )
    op.create_index(
        "ix_game_events_room_client_action",
        "game_events",
        ["room_id", "client_action_id"],
        unique=False,
    )
    op.create_table(
        "action_executions",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column(
            "request_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column(
            "result_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("committed_state_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_schema_version >= 1",
            name="ck_action_executions_request_schema_version",
        ),
        sa.CheckConstraint(
            "result_schema_version >= 1",
            name="ck_action_executions_result_schema_version",
        ),
        sa.CheckConstraint(
            "committed_state_version >= 0",
            name="ck_action_executions_committed_state_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "request_id", name="pk_action_executions"),
    )


def downgrade() -> None:
    """移除规则引擎基础结构，并恢复空的旧 room_sessions 表。"""
    op.drop_table("action_executions")
    op.drop_index("ix_game_events_room_client_action", table_name="game_events")
    op.drop_table("game_events")
    op.drop_table("game_sessions")
    op.drop_table("module_versions")

    op.create_table(
        "room_sessions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_constraint("ck_characters_version_positive", type_="check")
        batch_op.drop_constraint("uq_characters_room_player", type_="unique")
        batch_op.drop_column("version")

    op.drop_column("rooms", "module_version")

    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_constraint("ck_scenarios_status", type_="check")
        batch_op.drop_column("story_pages")
        batch_op.drop_column("subtitle")
        batch_op.drop_column("story_label")
        batch_op.drop_column("name_en")
        batch_op.drop_column("status")
