"""意图与裁决运行时类型 —— 对应 master §4.5（2026-07-11 AI 编排详细设计第一轮对齐）。

CheckRollResult 与 content 层的 CheckOutcome（模组内容"效果套餐"）此前撞名，
2026-07-11 已拆开为两个不同类型，此处只放运行时骰子结果。
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from core.content.models import CheckOutcome


class RefMatched(BaseModel):
    matched: Literal[True] = True
    id: str


class RefUnmatched(BaseModel):
    matched: Literal[False] = False
    text: str


Ref = Union[RefMatched, RefUnmatched]
"""🆕 软判据(LLM匹配)→硬求值(Rules只读)的标准结构，见 AI编排详细设计 §1.3。"""


class IntentInvestigate(BaseModel):
    kind: Literal["investigate"] = "investigate"
    target: Ref


class IntentMove(BaseModel):
    kind: Literal["move"] = "move"
    to_scene: Ref = Field(alias="toScene")

    model_config = {"populate_by_name": True}


class IntentTalk(BaseModel):
    kind: Literal["talk"] = "talk"
    npc: Ref
    utterance: str


class IntentSkillCheck(BaseModel):
    """🆕 路径B：玩家主动选技能摇骰，不经过内容匹配。"""

    kind: Literal["skillCheck"] = "skillCheck"
    skill: str


class IntentAsk(BaseModel):
    kind: Literal["ask"] = "ask"
    question: str


class IntentUnknown(BaseModel):
    """触发 §6.6 脱本导回状态机。"""

    kind: Literal["unknown"] = "unknown"
    raw: str


Intent = Union[IntentInvestigate, IntentMove, IntentTalk, IntentSkillCheck, IntentAsk, IntentUnknown]


class CheckRollResult(BaseModel):
    """🔧 原名 CheckOutcome，2026-07-11 改名——与 content 层 CheckOutcome 撞名，两者含义完全不同。"""

    skill: str
    roll: int
    target: int
    success: bool
    hidden: bool


ResolutionKind = Literal["checkpoint", "direct", "improvised", "blocked", "unrecognized"]
"""🆕 五路分支判别，见 AI编排详细设计 §1.4。"""


class ActionResult(BaseModel):
    ok: bool
    resolution_kind: ResolutionKind = Field(alias="resolutionKind")
    roll: Optional[CheckRollResult] = None
    """checkpoint 与 improvised(Tier2) 都可能有值。"""
    applied_outcome: Optional[CheckOutcome] = Field(default=None, alias="appliedOutcome")
    """仅 resolutionKind=='checkpoint' 时有值——结构性保证临场判定不执行预设效果。"""
    newly_discovered_entity_ids: list[str] = Field(default_factory=list, alias="newlyDiscoveredEntityIds")
    san_loss: Optional[int] = Field(default=None, alias="sanLoss")
    scene_changed_to: Optional[str] = Field(default=None, alias="sceneChangedTo")
    public_event_summary: str = Field(alias="publicEventSummary")

    model_config = {"populate_by_name": True}
