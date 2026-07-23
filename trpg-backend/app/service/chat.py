"""玩家讨论区的 service 层（issue #107）。

讨论区跟「对 AI 主持人说话」是两条独立通道（两个界面）：这里的消息只在
玩家之间流转，**永远不进任何 LLM 上下文**——这条约定要靠代码结构保证：
AI 相关代码（narrator / 未来的编排层）没有任何 import 指向本模块或
`ChatMessage` 模型，一旦有人"顺手把聊天也塞进 prompt"，成本和玩法两个
立项理由同时失效（issue #107 与 AI 编排的对齐约定第 1 条）。
"""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.chat import ChatMessageRead
from app.models.chat import ChatMessage
from app.models.room import Player


async def save_chat_message(
    db: AsyncSession, room_id: str, player_id: str, text: str, client_message_id: str
) -> ChatMessage:
    """落一条讨论区消息；重发（相同 `(player_id, client_message_id)`）幂等地
    返回已存在的那条，不产生重复记录。

    幂等靠 `chat_messages` 的唯一约束兜底，而不是"先查有没有再插"——
    check-then-act 在并发/重试下不可靠。🔴 撞约束必须用 SAVEPOINT
    （`begin_nested`）包住插入：直接 commit 失败后 rollback 会把事务连同
    连接一起废掉，异步驱动下重查时炸 `MissingGreenlet`（PR #110 的教训，
    同 `join_room` 的处理方式）。
    """
    message = ChatMessage(
        room_id=room_id, player_id=player_id, text=text, client_message_id=client_message_id
    )
    try:
        async with db.begin_nested():
            db.add(message)
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.player_id == player_id,
                ChatMessage.client_message_id == client_message_id,
            )
        )
        if existing is None:
            raise
        return existing

    await db.commit()
    return message


async def list_chat_messages(
    db: AsyncSession, room_id: str, before: str | None, limit: int
) -> list[ChatMessageRead]:
    """讨论区历史消息，倒序（最新在前）分页。

    游标用 `(created_at, id)` 复合序而不是单独 created_at：SQLite 的时间戳
    精度下同一毫秒内可能落多条消息，只按时间比较会在翻页边界漏掉/重复同刻
    的消息，补上主键作次序钉死全序。`before` 传上一页最后一条的 message_id。
    """
    query = select(ChatMessage, Player.nickname).join(Player, ChatMessage.player_id == Player.id)
    query = query.where(ChatMessage.room_id == room_id)

    if before is not None:
        anchor = await db.get(ChatMessage, before)
        # 无效游标当空页处理（而不是报错或悄悄回第一页）：报错会让"消息恰好
        # 被清理掉后刷新"变成用户可见的失败，回第一页会让翻页悄悄跳针。
        if anchor is None or anchor.room_id != room_id:
            return []
        query = query.where(
            (ChatMessage.created_at < anchor.created_at)
            | ((ChatMessage.created_at == anchor.created_at) & (ChatMessage.id < anchor.id))
        )

    query = query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
    rows = (await db.execute(query)).all()
    return [
        ChatMessageRead(
            message_id=message.id,
            player_id=message.player_id,
            nickname=nickname,
            text=message.text,
            sent_at=message.created_at,
            client_message_id=message.client_message_id,
        )
        for message, nickname in rows
    ]


async def clear_room_chat(db: AsyncSession, room_id: str) -> None:
    """删掉一个房间的全部讨论区消息。

    挂在房间结束（`POST /rooms/{roomId}/end`）时调用：聊天是"临时工作记忆"
    ——不进复盘、退房即清，这也是它单开一张表而不复用只追加的 `events`
    裁决记录的原因之一（issue #107 关键决策）。调用方负责 commit。
    """
    await db.execute(delete(ChatMessage).where(ChatMessage.room_id == room_id))
