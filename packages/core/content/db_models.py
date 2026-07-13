"""Content 层物理表 —— 对应 master §4.4.1。只读内容库，随模组导入写入。

范围：本次只建 walking skeleton 需要的四张表（worlds/module_packs/
module_scenes/entities）。module_checkpoints/module_san_triggers/
module_pregens/module_assets/module_win_conditions 留到后续迁移按需补，
不在此一次性建满——符合 §4.4.5"只增不破坏"的迁移策略。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class WorldRow(Base):
    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    definition: Mapped[dict] = mapped_column(JSONB, default=dict)
    hooks: Mapped[list] = mapped_column(JSONB, default=list)
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    world_rules: Mapped[list] = mapped_column(JSONB, default=list)


class ModulePackRow(Base):
    __tablename__ = "module_packs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    world_ref: Mapped[str] = mapped_column(ForeignKey("worlds.id"))
    title: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    setting: Mapped[str] = mapped_column(Text)  # master §4.3.1，§4.4.1 表格列举时漏列，按自由文本折叠为 TEXT
    keeper_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    players_min: Mapped[int] = mapped_column(Integer)
    players_max: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[int] = mapped_column(Integer)  # 1..5，见 ModuleMeta.difficulty
    estimated_duration: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)  # 'builtin' | 'imported'
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)


class ModuleSceneRow(Base):
    __tablename__ = "module_scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("module_packs.id"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    map_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    exits: Mapped[list] = mapped_column(JSON, default=list)
    contents: Mapped[list] = mapped_column(JSONB, default=list)


class EntityRow(Base):
    """★ 统一实体表，见 master §4.3.1「为什么合并」——吸收原 clue/npc。"""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("module_packs.id"))
    kind: Mapped[str] = mapped_column(String)  # npc|monster|item|clue|animal|object
    name: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    secrets: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    rules: Mapped[list] = mapped_column(JSONB, default=list)
    is_core: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    intentional_single_path: Mapped[bool] = mapped_column(Boolean, default=False)
