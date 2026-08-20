"""命令行发布全部内置模组，供 Docker 和本地启动流程复用。"""

import asyncio

from app.core.db import async_session_factory
from app.core.seed import ensure_seed_content
from app.service.builtin_module_loader import BuiltinModuleLoadError, load_builtin_modules


async def main() -> None:
    """先确保目录种子存在，再依次执行每个模组的原子发布。"""

    async with async_session_factory() as db:
        try:
            await ensure_seed_content(db)
            results = await load_builtin_modules(db)
        except BuiltinModuleLoadError as exc:
            raise SystemExit(str(exc)) from exc
    for result in results:
        print("\n".join(result.summary_lines()))


if __name__ == "__main__":
    asyncio.run(main())
