"""pytest 共享 fixture：让测试完全脱离本地/生产的真实数据库，跑在一个
每次测试都从零开始的内存 SQLite 上。

核心手法是 FastAPI 的依赖覆盖（`app.dependency_overrides`）：main.py 里的
路由都是通过 `Depends(get_db)` 拿数据库会话的，这里把 `get_db` 整体替换成
指向内存数据库的版本，路由代码本身完全不用感知"现在跑的是测试"。
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import app

# sqlite的 ":memory:" 数据库默认"每个新连接都是一个全新的空数据库"——
# 如果用默认的连接池，一个测试里发出的多次请求可能各自拿到不同的连接，
# 看到的会是互不相干的空数据库。StaticPool 强制整个引擎只维护一个连接、
# 所有请求复用它，这样同一个测试内的多次数据库操作才能看到彼此的写入。
# check_same_thread=False 是搭配 StaticPool 常见的必要选项（sqlite 默认
# 同一连接只能在创建它的线程里使用，这里放开这个限制）。
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """跟 app/core/db.py 里的 get_db 签名一致，只是内部用的是测试专用的引擎/会话工厂。"""
    async with TestSessionLocal() as session:
        yield session


# 关键一行：把 FastAPI 依赖图里所有用到 `Depends(get_db)` 的地方，替换成上面
# 这个指向内存数据库的版本。这行代码在模块导入时就执行（而不是放在某个 fixture
# 里），所以只要 pytest 收集了这个 conftest.py，整个测试会话期间 app 用的都是
# 测试数据库，不会有测试请求不小心打到本地开发用的 SQLite 文件或线上数据库。
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def _prepare_database() -> AsyncGenerator[None, None]:
    """每个测试函数跑之前建表、跑完之后清表，保证测试之间互不影响
    （不用手动在每个测试里管理数据库状态）。autouse=True 表示不需要在测试
    函数参数里显式声明这个 fixture，pytest 会自动应用到每个测试上。"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """给测试用例注入一个能直接调用 FastAPI app 的异步 HTTP 客户端。

    `ASGITransport(app=app)` 让 httpx 直接在内存里调用 ASGI 应用，不需要真的
    起一个监听端口的服务器进程——测试跑得更快，也不用操心端口占用。注意这种
    方式不会触发 main.py 里的 lifespan（也就是 init_db 不会被调用），但这里
    不需要它：数据库表是靠上面的 `_prepare_database` fixture 直接建的。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
