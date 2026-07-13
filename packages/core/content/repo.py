"""ContentRepo —— 对应 master §4.5 `interface ContentRepo`。

房间无关、只读，天然可被多房间共享。MVP 状态见模块拆分设计.md §四：
真实现（内置 1 个最小模组）。`load_module` 是 async——真实实现要做
真实的数据库 I/O（SQLAlchemy 异步引擎），同步接口会阻塞事件循环。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import select

from core.content.db_models import EntityRow, ModulePackRow, ModuleSceneRow
from core.content.models import (
    Entity,
    ModuleMeta,
    ModulePack,
    Scene,
    SceneContent,
    StatBlock,
)
from core.db import get_sessionmaker


@runtime_checkable
class ContentRepo(Protocol):
    async def load_module(self, module_id: str) -> ModulePack:
        """加载模组包，见 master §4.3.5 命名空间格式。"""
        ...


class StubContentRepo:
    """骨架阶段桩实现——内部实现留空，接口签名与串联关系是真的。"""

    async def load_module(self, module_id: str) -> ModulePack:
        raise NotImplementedError("ContentRepo.load_module: 待接入真实存储（PostgreSQL，ADR-17）")


class SqlAlchemyContentRepo:
    """真实实现（ADR-17：PostgreSQL）。

    本次只组装 checkpoints/san_triggers/pregens/assets/win 对应的表还没建，
    先返回空列表——不影响 IntentInvestigate 这条 walking skeleton 链路，
    待后续里程碑需要战斗规则引擎/建卡/胜负判定时再建表补齐。
    """

    async def load_module(self, module_id: str) -> ModulePack:
        async with get_sessionmaker()() as session:
            pack_row = await session.get(ModulePackRow, module_id)
            if pack_row is None:
                raise ValueError(f"module not found: {module_id}")

            scene_rows = (
                await session.execute(select(ModuleSceneRow).where(ModuleSceneRow.module_id == module_id))
            ).scalars().all()
            entity_rows = (
                await session.execute(select(EntityRow).where(EntityRow.module_id == module_id))
            ).scalars().all()

            return ModulePack(
                meta=ModuleMeta(
                    id=pack_row.id,
                    title=pack_row.title,
                    version=pack_row.version,
                    authors=pack_row.authors or [],
                    players_min=pack_row.players_min,
                    players_max=pack_row.players_max,
                    difficulty=pack_row.difficulty,
                    estimated_duration=pack_row.estimated_duration,
                    source=pack_row.source,
                ),
                world_ref=pack_row.world_ref,
                setting=pack_row.setting,
                keeper_notes=pack_row.keeper_notes,
                scenes=[
                    Scene(
                        id=row.id,
                        title=row.title,
                        description=row.description or "",
                        contents=[SceneContent(**c) for c in row.contents],
                        exits=row.exits,
                        map_ref=row.map_ref,
                    )
                    for row in scene_rows
                ],
                entities=[
                    Entity(
                        id=row.id,
                        kind=row.kind,
                        name=row.name,
                        content=row.content,
                        public_persona=row.public_persona,
                        secrets=row.secrets,
                        stats=StatBlock(**row.stats) if row.stats else None,
                        state=row.state,
                        rules=row.rules,
                        is_core=row.is_core,
                        intentional_single_path=row.intentional_single_path,
                    )
                    for row in entity_rows
                ],
            )
