"""按房间重建长期记忆投影，便于修复摘要/记忆游标或导入历史数据。"""

from __future__ import annotations

import argparse
import asyncio

from app.adapters.sqlalchemy_memory import SqlAlchemyMemoryStore
from app.core.db import async_session_factory


async def _main(room_id: str) -> None:
    """执行一次幂等补投影。"""
    count = await SqlAlchemyMemoryStore(async_session_factory).project_room_events(room_id)
    print(f"projected={count} room_id={room_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建指定房间的长期记忆投影")
    parser.add_argument("room_id")
    args = parser.parse_args()
    asyncio.run(_main(args.room_id))
