"""《追书人》NPC 头像资产清单和幂等导入逻辑。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ModuleAsset


@dataclass(frozen=True, slots=True)
class NpcPortraitSpec:
    """NPC 头像的稳定实体身份和生成提示词。"""

    entity_id: str
    name: str
    filename: str
    prompt: str


PAPER_CHASE_NPC_PORTRAITS = (
    NpcPortraitSpec(
        "thomas",
        "托马斯·金博尔",
        "thomas.png",
        "1920年代美国小镇年轻男性调查者，书房背景，克制而焦虑，时代西装，方形半身漫画角色立绘，清晰线稿，轻厚涂，柔和暖色光影",
    ),
    NpcPortraitSpec(
        "cemetery_figure",
        "道格拉斯·金博尔",
        "cemetery_figure.png",
        "1920年代美国墓地中的瘦削中年男性，怀抱旧书，神秘警觉，夜色墓地背景，方形半身漫画角色立绘，清晰线稿，轻厚涂，冷暖光影",
    ),
    NpcPortraitSpec(
        "lyla",
        "莱拉·奥戴尔",
        "lyla.png",
        "1920年代美国小镇成年女性邻居，谨慎观察，朴素时代服装，住宅街区背景，方形半身漫画角色立绘，清晰线稿，轻厚涂，柔和暖光",
    ),
    NpcPortraitSpec(
        "melodias",
        "梅洛迪亚斯·杰弗逊",
        "melodias.png",
        "1920年代美国公共墓地男性守墓人，旧外套，紧张警觉，夜间墓地背景，方形半身漫画角色立绘，清晰线稿，轻厚涂，月光与暖色轮廓光",
    ),
    NpcPortraitSpec(
        "hilda",
        "希尔达·沃德",
        "hilda.png",
        "1920年代美国老妇人，沉稳疲惫，朴素时代服装，旧报纸和书桌背景，方形半身漫画角色立绘，清晰线稿，轻厚涂，柔和暖光",
    ),
)
PAPER_CHASE_ASSET_ROOT = "/assets/npc_portraits/paper-chase-zh-coc7"


async def seed_paper_chase_npc_portraits(db: AsyncSession, *, scenario_id: str) -> int:
    """发布内置模组时写入 NPC 头像 URL，重复执行保持幂等。"""
    written = 0
    for spec in PAPER_CHASE_NPC_PORTRAITS:
        asset = await db.scalar(
            select(ModuleAsset).where(
                ModuleAsset.scenario_id == scenario_id,
                ModuleAsset.entity_id == spec.entity_id,
                ModuleAsset.asset_type == "npc_portrait",
            )
        )
        url = f"{PAPER_CHASE_ASSET_ROOT}/{spec.filename}"
        if asset is None:
            db.add(
                ModuleAsset(
                    scenario_id=scenario_id,
                    entity_id=spec.entity_id,
                    asset_type="npc_portrait",
                    name=spec.name,
                    url=url,
                )
            )
            written += 1
        elif asset.url != url or asset.name != spec.name:
            asset.url, asset.name = url, spec.name
            written += 1
    return written
