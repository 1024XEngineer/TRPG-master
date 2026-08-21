"""按房间重建长期记忆投影，便于修复摘要/记忆游标或导入历史数据。"""

from __future__ import annotations

import argparse
import asyncio

from app.adapters.sqlalchemy_memory import SqlAlchemyMemoryStore
from app.core.db import async_session_factory


async def _main(room_id: str, *, replace: bool) -> None:
    """默认增量补投影；只有显式 replace 才替换指定房间的投影。"""
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建指定房间的长期记忆投影")
    parser.add_argument("room_id")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="删除并重新生成指定房间的 MemoryEntry；不会删除摘要或原始事件",
    )
    args = parser.parse_args()
    asyncio.run(_main(args.room_id, replace=args.replace))
