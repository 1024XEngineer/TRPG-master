"""`ChatMessage`（`app/models/chat.py`，issue #107 地基）唯一约束测试。

跟 `tests/test_rooms.py::test_unique_constraint_blocks_duplicate_player_rows`
同一个理由：`(player_id, client_message_id)` 的去重必须由**数据库**保证——
重连重发同一条消息时，service 层任何"先查有没有"的判断都可能是
check-then-act，只有约束能真的挡住重复插入。这里直接往库里插两行相同键的
`ChatMessage`，证明约束真的会咬人，而不是只测 service 层的行为。
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from tests.helpers import create_room


async def test_unique_constraint_blocks_duplicate_client_message_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    room = await create_room(client)

    db_session.add(
        ChatMessage(
            room_id=room["roomId"],
            player_id=room["playerId"],
            client_message_id="local-msg-1",
            text="大家好",
        )
    )
    await db_session.commit()

    db_session.add(
        ChatMessage(
            room_id=room["roomId"],
            player_id=room["playerId"],
            client_message_id="local-msg-1",
            text="重发的同一条消息",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_same_player_can_send_messages_with_different_client_message_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """约束只锁 `(player_id, client_message_id)` 这一对组合，不同 id 的正常
    消息不受影响——避免把约束改严了误伤合法场景。"""
    room = await create_room(client)

    db_session.add_all(
        [
            ChatMessage(
                room_id=room["roomId"],
                player_id=room["playerId"],
                client_message_id="local-msg-1",
                text="第一条",
            ),
            ChatMessage(
                room_id=room["roomId"],
                player_id=room["playerId"],
                client_message_id="local-msg-2",
                text="第二条",
            ),
        ]
    )
    await db_session.commit()
