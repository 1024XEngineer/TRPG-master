"""GameState 层物理表 —— 对应 master §4.4.2/§4.4.3。仅引擎可写，跨房间隔离
唯一入口（通信铁律二）。`users` 严格说是账号层不是 GameState 层，暂放此处
是因为项目还没有专门的账号模块，两处 FK（rooms.host_user_id/players.user_id）
需要它先存在；后续如果长出独立的账号模块，再迁移不迟。

范围：本次只建 walking skeleton 需要的表，`notes` 留到后续迁移按需补。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    nickname: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class UserSessionRow(Base):
    """★ 2026-07-13 新增，对应 master §4.4.9 user_sessions（真实服务端登录会话，
    非无状态 JWT，见 auth.py `logout` 的注释）。"""

    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)


class RoomRow(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    room_code: Mapped[str] = mapped_column(String, unique=True)
    host_player_id: Mapped[str] = mapped_column(String)
    host_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    module_pack_id: Mapped[str] = mapped_column(ForeignKey("module_packs.id"))
    phase: Mapped[str] = mapped_column(String)
    entity_states: Mapped[dict] = mapped_column(JSONB, default=dict)
    rolling_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class PlayerRow(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"))
    nickname: Mapped[str] = mapped_column(String)
    # 与 characters.player_id 互相指向对方，是 master §4.4.0 记录在案的轻度冗余，
    # 用 use_alter 处理循环 FK（迁移时先建两张表，再补这条约束）。
    character_id: Mapped[str | None] = mapped_column(
        ForeignKey("characters.id", use_alter=True, name="fk_players_character_id"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    unknown_streak: Mapped[int] = mapped_column(Integer, default=0)
    connected: Mapped[bool] = mapped_column(Boolean, default=True)
    last_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    joined_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    left_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    reconnect_token: Mapped[str | None] = mapped_column(String, nullable=True)


class CharacterRow(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"))
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    based_on_pregen_id: Mapped[str | None] = mapped_column(String, nullable=True)  # module_pregens 未建表前不加 FK
    name: Mapped[str] = mapped_column(String)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    derived_stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    skills: Mapped[dict] = mapped_column(JSONB, default=dict)
    equipment: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(String)  # 软引用 → module_scenes.id
    conditions: Mapped[list] = mapped_column(JSONB, default=list)
    ledger: Mapped[dict] = mapped_column(JSONB, default=dict)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="draft")  # ★ 2026-07-13 新增：draft|complete，见 characters.py 建卡两段式


class EventRow(Base):
    """★ 事件溯源，不折叠——需要 (room_id, id) 范围查询，见 master §4.4.3。"""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID，天然有序
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB)
    visibility: Mapped[str] = mapped_column(String)  # public|scene|private
    ts: Mapped[int] = mapped_column(BigInteger)  # epoch millis，与 Event.ts（Pydantic，int）直接对应
