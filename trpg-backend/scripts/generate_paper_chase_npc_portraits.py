"""调用现有头像 provider 生成并校验《追书人》NPC 头像。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.service.npc_portrait_assets import PAPER_CHASE_NPC_PORTRAITS
from app.service.portrait_generation import build_portrait_generation_service


async def main() -> None:
    """逐个生成头像，经过既有物化器校验后写入前端静态资源目录。"""
    service = build_portrait_generation_service(get_settings())
    root = (
        Path(__file__).resolve().parents[2]
        / "trpg-frontend/public/assets/npc_portraits/paper-chase-zh-coc7"
    )
    root.mkdir(parents=True, exist_ok=True)
    for spec in PAPER_CHASE_NPC_PORTRAITS:
        path = root / spec.filename
        if path.exists():
            continue
        output = await service._image_provider.generate(
            prompt=spec.prompt,
            negative_prompt="多人、文字、水印、边框、照片写实、低分辨率、畸形、怪物",
            size="1024x1024",
            reference_image=service._reference_image,
        )  # noqa: SLF001
        image = await service._image_materializer.materialize(output.image_url)  # noqa: SLF001
        path.write_bytes(image.content)
        print(f"generated {path} {image.content_hash}")


if __name__ == "__main__":
    asyncio.run(main())
