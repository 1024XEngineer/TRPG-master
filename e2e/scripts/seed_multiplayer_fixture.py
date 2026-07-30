"""Publish an E2E-only two-player module into the disposable test database."""

import asyncio

from app.core.db import async_session_factory, engine
from content_fixtures import publish_multiplayer_module


async def _run() -> None:
    async with async_session_factory() as db:
        await publish_multiplayer_module(db)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
