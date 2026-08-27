"""内置模组 NPC 头像资产清单和幂等导入逻辑。"""

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

HAPPY_FROG_VILLAGE_NPC_PORTRAITS = (
    NpcPortraitSpec(
        "villager_accounts",
        "周边村民",
        "villager_accounts.webp",
        "现代老林地周边的乡村居民，对林地与共同梦境讳莫如深，方形角色立绘",
    ),
    NpcPortraitSpec(
        "ezra",
        "埃兹拉",
        "ezra.webp",
        "现代城郊中年男性推销员，疲惫警觉，手指带淡绿色蹼膜，方形半身角色立绘",
    ),
    NpcPortraitSpec(
        "messenger",
        "幸福信使",
        "messenger.webp",
        "白发绿色斗篷少女，笑容真诚但令人不安，森林度假村背景，方形半身角色立绘",
    ),
    NpcPortraitSpec(
        "emily",
        "艾米丽",
        "emily.webp",
        "现代度假村接待女仆，笑容完美无瑕却僵硬，别墅大厅背景，方形半身角色立绘",
    ),
    NpcPortraitSpec(
        "james",
        "詹姆斯·莱恩",
        "james.webp",
        "现代年轻男性，沉浸在幸福美梦中，森林度假村背景，方形半身角色立绘",
    ),
    NpcPortraitSpec(
        "frog_head_guest",
        "宽衣游客",
        "frog_head_guest.webp",
        "现代度假村游客，用宽大衣物遮挡身体异样，神情麻木，方形角色立绘",
    ),
    NpcPortraitSpec(
        "dream_frogs",
        "梦游青蛙",
        "dream_frogs.webp",
        "森林池塘边几乎不躲避来人的鲜艳青蛙，梦境般氛围，方形角色立绘",
    ),
)
HAPPY_FROG_VILLAGE_ASSET_ROOT = "/assets/npc_portraits/happy-frog-village"


async def _seed_npc_portraits(
    db: AsyncSession,
    *,
    scenario_id: str,
    specs: tuple[NpcPortraitSpec, ...],
    asset_root: str,
) -> int:
    """写入一组 NPC 头像 URL，重复执行保持幂等。"""
    written = 0
    for spec in specs:
        asset = await db.scalar(
            select(ModuleAsset).where(
                ModuleAsset.scenario_id == scenario_id,
                ModuleAsset.entity_id == spec.entity_id,
                ModuleAsset.asset_type == "npc_portrait",
            )
        )
        url = f"{asset_root}/{spec.filename}"
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


async def seed_paper_chase_npc_portraits(db: AsyncSession, *, scenario_id: str) -> int:
    """发布《追书人》时写入 NPC 头像。"""
    return await _seed_npc_portraits(
        db,
        scenario_id=scenario_id,
        specs=PAPER_CHASE_NPC_PORTRAITS,
        asset_root=PAPER_CHASE_ASSET_ROOT,
    )


async def seed_happy_frog_village_npc_portraits(db: AsyncSession, *, scenario_id: str) -> int:
    """发布《幸福蛙蛙村》时写入 NPC 头像。"""
    return await _seed_npc_portraits(
        db,
        scenario_id=scenario_id,
        specs=HAPPY_FROG_VILLAGE_NPC_PORTRAITS,
        asset_root=HAPPY_FROG_VILLAGE_ASSET_ROOT,
    )
