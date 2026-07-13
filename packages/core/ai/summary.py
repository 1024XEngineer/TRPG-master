"""SummaryGenerator —— 对应 master §4.5 + AI编排详细设计 §五。

输入是 GameState 全貌（GodView）不是 PlayerView——复盘阶段不受"不泄底"约束，
呼应 GET /replay 全事件可见的既有边界。RoomSummary 此前只被引用未定义，
2026-07-12 补，字段取自 room_summaries 表 + API 对齐规范 §2.7 响应形状。
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.content.models import WinCondition
from core.state.models import GameState


class RoomSummaryStats(BaseModel):
    san_changes: dict[str, int] = Field(default_factory=dict, alias="sanChanges")
    character_fates: dict[str, str] = Field(default_factory=dict, alias="characterFates")
    duration_minutes: int = Field(default=0, alias="durationMinutes")

    model_config = {"populate_by_name": True}


class RoomSummary(BaseModel):
    room_id: str = Field(alias="roomId")
    ending_type: str = Field(alias="endingType")  # 命中的 WinCondition.id
    summary_text: str = Field(alias="summaryText")  # 唯一需要 LLM 生成的部分
    key_findings: list[str] = Field(default_factory=list, alias="keyFindings")
    stats: RoomSummaryStats
    generation_method: Literal["llm", "fallback_template"] = Field(alias="generationMethod")
    generated_at: int = Field(alias="generatedAt")

    model_config = {"populate_by_name": True}


@runtime_checkable
class SummaryGenerator(Protocol):
    async def generate(self, state: GameState, hit_win_condition: WinCondition) -> RoomSummary:
        ...


class StubSummaryGenerator:
    async def generate(self, state: GameState, hit_win_condition: WinCondition) -> RoomSummary:
        raise NotImplementedError(
            "SummaryGenerator.generate: 待实现——重试+降级模板兜底，'绝不失败'，见 AI编排详细设计 §5.3"
        )
