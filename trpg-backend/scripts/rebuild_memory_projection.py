"""按房间重建长期记忆投影，便于修复摘要/记忆游标或导入历史数据。"""

from __future__ import annotations

import argparse
import asyncio

from app.adapters.sqlalchemy_memory import SqlAlchemyMemoryStore
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.service.conversation_summary import build_conversation_summary_service


async def _main(room_id: str, *, replace: bool, summary: bool) -> None:
    """默认增量补投影；可选复用摘要服务重建指定房间摘要。"""
    store = SqlAlchemyMemoryStore(async_session_factory)
    result = (
        await store.rebuild_room_events(room_id)
        if replace
        else await store.project_room_events(room_id)
    )
    print(
        f"room_id={room_id} mode={'replace' if replace else 'incremental'} "
        f"scanned_events={result.scanned_events} "
        f"scanned_game_events={result.scanned_game_events} "
        f"inserted={result.inserted} skipped={result.skipped} "
        f"event_created_at={result.event_created_at} event_id={result.event_id} "
        f"game_sequence={result.game_sequence}"
    )
    if summary:
        summary_service = build_conversation_summary_service(get_settings(), async_session_factory)
        player_count, generated = await summary_service.rebuild_room(room_id, replace=replace)
        print(
            f"room_id={room_id} summary_mode={'replace' if replace else 'incremental'} "
            f"players={player_count} generated={generated}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建指定房间的长期记忆投影")
    parser.add_argument("room_id")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="删除并重新生成指定房间的 MemoryEntry；仅配合 --summary 时重建摘要",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="同时按正常摘要服务增量处理该房间；配合 --replace 才会重建摘要",
    )
    args = parser.parse_args()
    asyncio.run(_main(args.room_id, replace=args.replace, summary=args.summary))
