"""账号相关 ORM 模型（issue #77 §1，运行时状态库的一部分）。

`User`/`UserSession` 承接 issue #58 之前用内存字典（`_users`/`_accounts`/
`_tokens`）实现的账号+会话逻辑；`UserCharacterTemplate` 是本期新增的"我的
常用角色卡库"（issue 决策 5），本期只铺表与接口，不实现真实读写（详见
service/character.py）。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    """账号。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class UserSession(Base):
    """登录会话：`Authorization: Bearer <token>` 里的 token 就是这里的 `token` 列。

    本期不做过期/续期（跟原来的内存 stub 行为一致），`token` 直接唯一索引，
    退出登录时整行删除。
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class UserCharacterTemplate(Base):
    """玩家的"我的常用角色卡"库（issue 决策 5）。

    `system_id` 约束死了这张卡只能用于同一个规则系统（COC7 的卡不能拿去玩
    DND5e）；只存建卡态字段（放在 `data` 里），不带任何单局才有的状态
    （HP/理智/疯狂），复用时天然不会把上一局的状态带进新局。本期只铺表与
    接口，不实现真实读写（service 层直接返回 NOT_IMPLEMENTED）。
    """

    __tablename__ = "user_character_templates"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    system_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_systems.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
