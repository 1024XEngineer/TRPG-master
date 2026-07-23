"""玩家讨论区消息 ORM 模型（issue #107 地基）。

`ChatMessage` 是玩家之间闲聊/讨论用的消息，跟 `events`（`app/models/event.py`）
性质完全不同，这正是单开一张表、不复用 `events` 的原因：

- **AI 完全不读这张表**：讨论区的设计前提是"AI 主持人听不见玩家私下讨论"
  （issue #107 决策），讨论内容不会拼进任何 LLM 上下文。`events` 则相反，
  是给编排层/复盘消费的裁决记录。
- **退房即清空、不进复盘**：`POST /rooms/{roomId}/end` 会把这张表里属于该
  房间的行整表删除，是名副其实的"临时工作记忆"；`events` 是只增不改的
  永久流水，`GET /rooms/{roomId}/replay` 直接顺序读它。
- **需要按 `(player_id, client_message_id)` 去重**：客户端断线重连后可能
  重发同一条消息，`events` 没有这个去重需求，`chat_messages` 有——这也是
  不复用 `events` 的关键决策依据之一，单独建表才能挂上这个唯一约束。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatMessage(Base):
    """房间内玩家讨论区的一条消息。"""

    __tablename__ = "chat_messages"

    # 去重键靠 (player_id, client_message_id) 的唯一约束保证，而不是
    # service 层"先查是否存在再插"——同样是 check-then-act 在并发/重试下
    # 不可靠（PR #110 review 里 players 表唯一约束的教训同样适用这里）。
    __table_args__ = (
        UniqueConstraint("player_id", "client_message_id", name="uq_chat_messages_player_client"),
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False, index=True
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=False
    )
    # 客户端生成的去重键（比如一个本地自增序号或 UUID），重连重发同一条消息时
    # 靠 (player_id, client_message_id) 的唯一约束挡掉重复插入。
    client_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
