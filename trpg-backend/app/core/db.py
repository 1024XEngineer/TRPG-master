"""数据库连接层：SQLAlchemy 异步引擎 + Session 工厂 + ORM 基类。

用 SQLAlchemy（异步）而不是原生 asyncpg/aiosqlite 手写 SQL，是因为数据模型
还在演进期，ORM 能省掉大量手写 SQL 和字段映射的维护成本；同一套 `Base` 子类
（见 models/room.py）不用改代码就能同时对接本地 SQLite 和线上 PostgreSQL，
差异全部封装在 `DATABASE_URL` 这一个环境变量里。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# echo=False：不把每条 SQL 打到日志里（调试连接问题时可以临时改 True）。
# 这里创建的是"连接池"，不是单个连接——每次请求进来会从池里借一个连接，用完还回去。
# pool_pre_ping=True：从池里借连接前先探活一下（轻量的 "SELECT 1"）。云数据库
# 经常会主动断开长时间空闲的连接，没有这个选项的话，池子里借出的第一个失效连接
# 会让请求直接报错；本地 SQLite 用不上，但换成线上 PostgreSQL 之后这个坑很常见，
# 干脆一开始就打开，不用等真的踩到了再加。
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

# expire_on_commit=False：commit 之后，Python 对象里已经查出来的属性值不会被清空。
# 如果不设这个，commit 之后再访问 room.room_name 之类的属性会触发一次隐式的重新查询，
# 在异步代码里这种"意外的隐式 IO"很容易踩坑（比如在没有 await 的地方悄悄发起数据库请求）。
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类（见 models/room.py 里的 `Room(Base)`）。

    SQLAlchemy 靠这个基类的 `metadata` 属性收集所有已定义的表结构，
    下面的 `init_db()` 就是靠 `Base.metadata.create_all` 把这些表建到数据库里。
    """

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用的数据库会话获取函数。

    用法：在路由函数参数里写 `db: AsyncSession = Depends(get_db)`，FastAPI
    会在处理请求前调用这个生成器拿到 `session`，请求处理完（不管成功还是抛异常）
    自动执行 `async with` 的退出逻辑把连接还回连接池——不需要每个路由自己写
    try/finally 来关闭连接。

    测试代码（tests/conftest.py）会用 `app.dependency_overrides[get_db] = ...`
    把这个函数整体替换成指向内存 SQLite 的版本，这样测试不会碰到本地/生产的真实数据库。
    """
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """建表：把 Base.metadata 里登记的所有模型对应的表结构同步到数据库。

    issue #77 决策 9：本期引入 Alembic 之后，这个函数已经从 main.py 的 FastAPI
    lifespan 里撤下，退为仅测试用——`create_all` 只有"没表就建、有表就跳过"
    这一种语义，不处理字段增删改这类真正的迁移场景，继续在应用启动时调用
    会让开发者拿到一个"代码以为字段存在、数据库其实没有"的坏状态。真实的
    本地/生产建表交给 `alembic upgrade head`（见 README）。测试套件目前是
    直接对着独立的内存 SQLite 引擎调 `Base.metadata.create_all`
    （tests/conftest.py），没有反过来调用这个函数，但语义完全等价——每次
    测试都从空库重新建表，不需要迁移历史。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
