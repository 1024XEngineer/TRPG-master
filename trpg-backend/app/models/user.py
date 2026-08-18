"""账号相关 ORM 模型（issue #77 §1，运行时状态库的一部分）。

`User`/`UserSession` 承接 issue #58 之前用内存字典（`_users`/`_accounts`/
`_tokens`）实现的账号+会话逻辑；`UserCharacterTemplate` 是"我的常用角色卡库"。
Issue #121 起，完成房间 Character 会自动写入该表；卡库列表、加载和手工管理接口
仍留待后续实现。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
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
    （HP/理智/疯狂），复用时天然不会把上一局的状态带进新局。Issue #121 只实现
    完成建卡时的自动保存，卡库 CRUD 端点仍返回 NOT_IMPLEMENTED。
    """

    __tablename__ = "user_character_templates"
    # 同一个玩家在同一规则系统下不能有两张**一模一样**的卡（#337）。判据是内容，
    # 不是名字：两张真不同的卡完全可以同名，字节相同的才算重复。
    #
    # 约束放在数据库层而不是只在 service 里查一遍——那样并发两次保存仍会各自
    # 查空、各插一条。SQLite 虽然默认不强制外键，但**强制 UNIQUE**，所以这条
    # 在本地和测试里都真会触发，不是个测不到的保证。
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "system_id",
            "content_hash",
            name="uq_user_character_templates_content",
        ),
    )

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
    # `name` + `data` 的规范化 SHA-256（见 service 层 `_template_content_hash`）。
    # 服务端算、服务端存；客户端传上来的哈希一律不认。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class UserCharacterTemplatePortrait(Base):
    """角色卡库当前头像；与房间头像分开存储，跨房间复用时复制。"""

    __tablename__ = "user_character_template_portraits"
    __table_args__ = (
        CheckConstraint(
            "size_bytes > 0",
            name="ck_user_character_template_portraits_size_positive",
        ),
    )

    template_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("user_character_templates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
