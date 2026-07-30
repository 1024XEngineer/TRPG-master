"""本地加载固定的追书人 ModuleContent。

用法：

    uv run python scripts/load_paper_chase.py
"""

import asyncio
import sys

from app.core.db import async_session_factory, engine
from app.core.seed import ensure_seed_content
from app.service.paper_chase_loader import PaperChaseLoadError, load_paper_chase


async def _run() -> int:
    try:
        async with async_session_factory() as db:
            await ensure_seed_content(db)
            result = await load_paper_chase(db)
    except PaperChaseLoadError as exc:
        print(f"追书人 ModuleContent 加载失败: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print("追书人 ModuleContent 加载完成")
    print("\n".join(result.summary_lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
