"""pytest 共享 fixture：让测试完全脱离本地/生产的真实数据库，跑在一个
每次测试都从零开始的内存 SQLite 上。

核心手法是 FastAPI 的依赖覆盖（`app.dependency_overrides`）：main.py 里的
路由都是通过 `Depends(get_db)` 拿数据库会话的，这里把 `get_db` 整体替换成
指向内存数据库的版本，路由代码本身完全不用感知"现在跑的是测试"。
"""

import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.controller import ws as ws_controller
from app.core.db import Base, get_db
from app.core.seed import ensure_seed_content
from app.main import app

# 用临时文件 SQLite，不用 ":memory:"+StaticPool。关键原因是并发模型：异步 HTTP
# 测试跑在 pytest-asyncio 的事件循环里，而同步 TestClient 的 WebSocket 跑在它
# 自己 portal 线程的另一个事件循环里。aiosqlite 的每个连接都绑定在「创建它的
# 那个事件循环」上，StaticPool 只有一个共享连接——两个循环去用同一个连接会
# 直接死锁。文件型 SQLite 让每个循环各开各的连接、指向同一个文件，就不存在这个
# 问题；测试间隔离仍由下面 _prepare_database 的 create_all/drop_all 保证。
# （另外 WS 路由已改成每条消息一个短 session，不再长期持有连接、锁窗口很短，
# 见 app/controller/ws.py。）文件放临时目录，进程退出随之清理。
_TEST_DB_PATH = Path(tempfile.mkdtemp(prefix="trpg-test-")) / "test.db"
# NullPool：每次用完立刻关闭连接，不在池里留着复用。同步 TestClient 的 WS 跑在
# 它自己 portal 线程的事件循环里，如果连接被池缓存下来、下一个用例（在别的
# 循环里）又拿到这个绑定在旧循环上的连接，就会挂死。NullPool 让每次都开一个
# 干净的新连接，避免跨事件循环复用。
test_engine = create_async_engine(f"sqlite+aiosqlite:///{_TEST_DB_PATH}", poolclass=NullPool)
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

# WS 路由（app/controller/ws.py）是原生 websocket handler，拿不到 FastAPI 的
# Depends(get_db)，而是直接 `async with async_session_factory() as db`——也就是
# 上面的依赖覆盖对它无效，它会绕过测试库去连真实库。这里把 ws 模块引用的那个
# 工厂也重绑到测试库，否则 WS 测试里 HTTP 请求写进的是内存测试库、WS 路由却
# 去空的真实库里查 player，必然查不到而关连接。
ws_controller.async_session_factory = TestSessionLocal  # type: ignore[assignment]


@pytest.fixture(autouse=True)
async def _prepare_database() -> AsyncGenerator[None, None]:
    """每个测试函数跑之前建表、跑完之后清表，保证测试之间互不影响
    （不用手动在每个测试里管理数据库状态）。autouse=True 表示不需要在测试
    函数参数里显式声明这个 fixture，pytest 会自动应用到每个测试上。"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 灌内置模组种子数据：生产环境靠 main.py lifespan 的 ensure_seed_content，
    # 但 ASGITransport 测试客户端不触发 lifespan，所以这里手动灌一次——否则
    # 依赖内置模组的用例（建房选模组、GET /modules 等）会因为库里没有模组而失败。
    async with TestSessionLocal() as session:
        await ensure_seed_content(session)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """给需要绕过 HTTP、直接读写数据库的用例用（多数用例走 `client` 就够了）。

    注意别在测试模块里 `from tests.conftest import TestSessionLocal`——那会把
    conftest 当成另一个模块再导入一次、连带新建一个引擎，表建在旧引擎上，
    结果是 `no such table`。要拿 session 就用这个 fixture。
    """
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
def sql_counter() -> Generator[list[str], None, None]:
    """记录这段测试期间真实执行的 SQL 语句，用来断言"查询数不随数据量增长"。

    给 N+1 查询这类问题用：光看接口返回值是对的看不出它发了多少条查询，而 N+1
    的症状要到数据量长起来才显现——那时候再发现就晚了。断言用"总数有上限"而不是
    "等于某个具体值"，免得以后加一条无关查询就误报。
    """
    from sqlalchemy import event

    executed: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        executed.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    try:
        yield executed
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record)


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
