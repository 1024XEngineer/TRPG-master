"""内容库 / 规则库 ORM 模型（issue #77 §1，11 张表）。

这一组表是"只读、跨局复用"的内容数据——大类（游戏）→ 规则系统 → 世界观 →
模组（场景）→ 场景内的具体分幕/实体/检定点/胜利条件/预设角色/素材，本期只
铺表结构，不接入真实的模组导入管线（真实 LLM 解析归 #57），`rooms`/
`characters` 等运行时表通过外键引用这里的行。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Game(Base):
    """游戏大类，比如"克苏鲁的呼唤"。"""

    __tablename__ = "games"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class GameSystem(Base):
    """大类下的具体规则系统，比如 COC7。

    `ruleset` 存放建卡所需的属性/技能/职业目录（供 `GET /systems/{systemId}/ruleset`
    读取），本期只是一份可以为空的 JSON 快照，不做规则校验。
    """

    __tablename__ = "game_systems"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    game_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("games.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ruleset: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class World(Base):
    """世界观/设定，一个游戏大类下可以有多套世界观。"""

    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    game_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("games.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Scenario(Base):
    """模组（对应前端/DTO 里的"模组" ModuleRead），房间选定的就是这里的一行。"""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    world_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("worlds.id"), nullable=True
    )
    game_system_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_systems.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    authors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    players_min: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    players_max: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    estimated_duration: Mapped[str | None] = mapped_column(String(50), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ScenarioScene(Base):
    """模组内的分幕/场景，`rooms.discovered_scene_ids` 里存的就是这里的行 id。"""

    __tablename__ = "scenario_scenes"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Entity(Base):
    """模组内的实体（NPC / 物品 / 地点等），字段形状随类型变化，用 JSON 兜底。"""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModuleCheckpoint(Base):
    """模组内的检定关卡点（规则引擎驱动 check.request 时会读这里，本期不接规则引擎）。"""

    __tablename__ = "module_checkpoints"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenario_scenes.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    skill: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModuleSanTrigger(Base):
    """模组内的理智检定触发点。"""

    __tablename__ = "module_san_triggers"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenario_scenes.id"), nullable=True
    )
    trigger_name: Mapped[str] = mapped_column(String(200), nullable=False)
    san_loss_success: Mapped[str | None] = mapped_column(String(50), nullable=True)
    san_loss_failure: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModuleWinCondition(Base):
    """模组内的胜利/结局条件。"""

    __tablename__ = "module_win_conditions"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModulePregen(Base):
    """模组作者预设的角色（老玩家复用卡的两条既有路径之一，见 issue 决策 5）。"""

    __tablename__ = "module_pregens"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModuleAsset(Base):
    """模组素材（地图/立绘等静态资源的引用）。"""

    __tablename__ = "module_assets"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scenario_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
