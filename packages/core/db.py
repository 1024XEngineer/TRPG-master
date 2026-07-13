"""共享数据库基础设施 —— engine/session 工厂，供 core/content 与 core/state 的
真实 SQLAlchemy 实现共用。不是领域接口，纯技术底座，因此不放进任何一个
现有模块（避免制造 core/content 与 core/state 之间不存在的依赖关系）。
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    url = os.environ["DATABASE_URL"]
    return create_async_engine(url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
