"""Service 层：Example 的数据访问 + 业务操作函数。

这一层只管"怎么查/怎么写数据库"，不关心 HTTP 相关的东西（状态码、异常处理、
请求体校验都不在这里）——controller 层（controller/v1/examples.py）负责编排
调用顺序、决定校验失败时抛什么错误；这一层的函数可以被任何调用方复用（controller、
后台任务、未来的管理脚本等），职责边界很清楚。

对应 Java/Spring 里的 Service（如果以后逻辑变复杂、需要跨表编排，也是在
这一层展开，不会污染 controller）。
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.example import ExampleCreate, ExampleUpdate
from app.models.example import Example


async def list_examples(db: AsyncSession) -> Sequence[Example]:
    """按创建时间正序取出全部记录（骨架阶段数据量小，不做分页）。"""
    result = await db.execute(select(Example).order_by(Example.created_at))
    return result.scalars().all()


async def get_example(db: AsyncSession, example_id: str) -> Example | None:
    """按主键查单条，查不到返回 None（是否转成 404 由调用方/路由层决定）。"""
    return await db.get(Example, example_id)


async def get_example_by_name(db: AsyncSession, name: str) -> Example | None:
    """按名称查单条，用于路由层判断"是否已存在同名记录"（409 冲突检查）。"""
    result = await db.execute(select(Example).where(Example.name == name))
    return result.scalar_one_or_none()


async def create_example(db: AsyncSession, payload: ExampleCreate) -> Example:
    """新建一条记录。

    id 在这里显式生成（而不是依赖 models.Example 里 mapped_column 的 default），
    这样构造出来的 Example 对象在 db.add() 之前就已经有完整的 id，便于调用方
    需要的话可以立即用到这个 id（比如记日志）。
    """
    example = Example(id=str(uuid.uuid4()), name=payload.name, description=payload.description)
    db.add(example)
    await _commit_or_raise(db)
    # commit 之后重新从数据库读一次，拿到 updated_at 等由数据库/ORM 计算的最终值，
    # 保证返回给调用方的对象状态是"提交后的真实状态"。
    await db.refresh(example)
    return example


async def update_example(db: AsyncSession, example: Example, payload: ExampleUpdate) -> Example:
    """全量更新一条已经查出来的记录（调用方负责先用 get_example 查到 example）。"""
    example.name = payload.name
    example.description = payload.description
    await _commit_or_raise(db)
    await db.refresh(example)
    return example


async def delete_example(db: AsyncSession, example: Example) -> None:
    """删除一条已经查出来的记录。"""
    await db.delete(example)
    await db.commit()


async def _commit_or_raise(db: AsyncSession) -> None:
    """commit，失败（比如撞上唯一约束）时回滚，再把 IntegrityError 原样抛给调用方。

    `get_example_by_name` 判重只是"先查后写"，两步之间不是原子的：两个并发请求
    都查到"名字可用"、都往下走到这里 commit 时，只有一个能提交成功，另一个会在
    这里撞上数据库的 UNIQUE 约束——这是并发下唯一真正兜底的地方，前面的查重只是
    为常见的顺序场景提供更快、更友好的报错路径。controller 层负责把这里抛出的
    IntegrityError 翻译成 409（见 controller/v1/examples.py）。
    """
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
