"""房间相关 ORM 模型（issue #77 §1，运行时状态库的一部分）。

- Room：房间主表
- Player：房间内玩家成员表（issue #77 之前叫 `room_players`，本期改名对齐设计，
  补齐 `user_id`/`is_ai`/`joined_at`/`left_at`/`connected`）
- Character：房间内的角色卡（原来挂在 service/room.py 的内存字典里）
- Note：房间内玩家的速记本（本期只铺表，没有对应的读写接口——`note.save`
  WS 事件本期不铺，见 issue"本期不做"）
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_code: Mapped[str] = mapped_column(String(6), unique=True, index=True, nullable=False)
    room_name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="Lobby")

    # 房主身份：host_player_id 是房间内身份（Player.id，房间创建后回写），
    # host_user_id 是账号身份（User.id）——两者是独立的身份体系（同一账号
    # 理论上可以用不同 nickname 在不同房间里当房主），本期 REST 创建/加入
    # 房间接口不强制要求登录（trpg-frontend 现在也没有在这两个请求上带
    # Authorization 头，属于零改动约束下的已知缺口），所以 host_user_id
    # 允许为空，只在调用方确实带了有效登录态时才回填。
    host_player_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), nullable=True, default=None
    )
    host_user_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=True, default=None
    )

    game_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("games.id"), nullable=True, default=None
    )
    system_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_systems.id"), nullable=True, default=None
    )
    scenario_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=True, default=None
    )
    attribute_gen_method: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )
    # 已探索场景 id 列表（对应 scenario_scenes.id），JSON 数组存起来，本期
    # 没有任何写入路径（推进场景发现属于规则引擎/编排器范畴），只铺字段。
    discovered_scene_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    # 生命周期时间戳：created_at 是"建房时刻"，下面两个分别对应正式开局
    # （phase 变成 InGame）和结束游戏（phase 变成 Completed）的时刻。
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    players: Mapped[list["Player"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class Player(Base):
    """房间内玩家成员表（原 `room_players`，本期改名为 `players`）。"""

    __tablename__ = "players"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    # 关联账号：可空，理由同 Room.host_user_id 的注释——本期 REST 创建/加入
    # 房间不强制登录，只在调用方带了有效 Authorization 时才回填。
    user_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=True, default=None
    )
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_character: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reconnect_token: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), default=lambda: str(uuid.uuid4()), nullable=False
    )
    # WS 连接是否处于活跃状态：room.join 时置 True，WS 断开时置 False——
    # 断线重连（room.rejoin，issue 决策 6）读这个字段判断"这个玩家掉线了吗"，
    # 本期只维护状态，不接断线重连的真实逻辑。
    connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["Room"] = relationship(back_populates="players")


class Character(Base):
    """房间内的角色卡（原本挂在 service/room.py 的 `_characters` 内存字典里）。"""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # 建卡三条路径的来源（都可空，互斥但不做数据库层面强制）：
    # ① based_on_pregen_id：套用模组作者预设角色；
    # ② based_on_template_id：复用玩家自己的常用卡（issue 决策 5，本期不实现）；
    # ③ 都不填：从零选职业建卡，occupation 字段直接记职业名。
    based_on_pregen_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("module_pregens.id"), nullable=True
    )
    based_on_template_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("user_character_templates.id"), nullable=True
    )

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    derived_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    skills: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    equipment: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Note(Base):
    """房间内玩家的速记本。本期只铺表，没有对应的读写接口。"""

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
