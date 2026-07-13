"""PlayerView / SceneActionMenu —— 对应 master §4.5。

PlayerView 是权限裁剪产物（喂给 LLM/手机的唯一形态）；SceneActionMenu 仅供
IntentParser 内部解析用，**不进 view.private、不下发客户端**（AI编排详细设计 §1.2）。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PlayerVisibleClue(BaseModel):
    """★ 2026-07-13 补：master §4.3.4"敏感字段类型级隔离"要求 entity.secrets
    在 ViewProjector/Narrator 的类型签名里结构上拿不到——但骨架代码原先
    PlayerView.visible_clues 直接用了 content 层的完整 Entity 类型（带
    secrets 字段），构造函数层面没错但类型上并不能阻止未来的实现疏忽地把
    secrets 塞进去，达不到"结构上不可能"这个强度。故拆出这个只含玩家可见
    字段的窄类型，真正在类型层面切断 secrets 泄漏的可能。见架构演进日志同日条目。
    """

    id: str
    name: str
    content: Optional[str] = None


class PlayerView(BaseModel):
    for_whom: str = Field(alias="forWhom")  # playerId 或人格标识
    visible_scene_description: str = Field(alias="visibleSceneDescription")
    visible_clues: list[PlayerVisibleClue] = Field(default_factory=list, alias="visibleClues")
    visible_san: int = Field(alias="visibleSan")
    # 🚧 缺 HP/MP/幸运，master §5.2.2 view.private 待办项，不在本轮范围
    # 注意：绝不含未触发的底牌/暗骰结果/其他玩家私密信息/Entity.secrets

    model_config = {"populate_by_name": True}


class SceneActionMenuEntity(BaseModel):
    id: str
    name: str


class SceneActionMenuExit(BaseModel):
    scene_id: str = Field(alias="sceneId")
    title: str

    model_config = {"populate_by_name": True}


class SceneActionMenu(BaseModel):
    entities: list[SceneActionMenuEntity] = Field(default_factory=list)
    """当前 Scene.contents 里 entity_present/clue_access 关联的 Entity，仅 id+name。"""
    exits: list[SceneActionMenuExit] = Field(default_factory=list)
    """Scene.exits 对应的可去地点，可下发客户端（跟 entities 不同）。"""
