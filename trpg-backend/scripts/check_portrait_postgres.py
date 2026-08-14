"""CI 中核对 PostgreSQL 生图任务迁移及部分唯一索引。"""

import asyncio
import os

import asyncpg


async def main() -> None:
    """连接 CI PostgreSQL，确认活动任务唯一约束按预期生成。"""
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url)
    try:
        definition = await connection.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = $1",
            "uq_portrait_generation_tasks_active_character",
        )
        assert definition and "UNIQUE INDEX" in definition
        assert "WHERE" in definition and "cancelling" in definition
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
