import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.example import Example
from app.schemas.example import ExampleCreate, ExampleUpdate


async def list_examples(db: AsyncSession) -> Sequence[Example]:
    result = await db.execute(select(Example).order_by(Example.created_at))
    return result.scalars().all()


async def get_example(db: AsyncSession, example_id: str) -> Example | None:
    return await db.get(Example, example_id)


async def get_example_by_name(db: AsyncSession, name: str) -> Example | None:
    result = await db.execute(select(Example).where(Example.name == name))
    return result.scalar_one_or_none()


async def create_example(db: AsyncSession, payload: ExampleCreate) -> Example:
    example = Example(id=str(uuid.uuid4()), name=payload.name, description=payload.description)
    db.add(example)
    await db.commit()
    await db.refresh(example)
    return example


async def update_example(db: AsyncSession, example: Example, payload: ExampleUpdate) -> Example:
    example.name = payload.name
    example.description = payload.description
    await db.commit()
    await db.refresh(example)
    return example


async def delete_example(db: AsyncSession, example: Example) -> None:
    await db.delete(example)
    await db.commit()
