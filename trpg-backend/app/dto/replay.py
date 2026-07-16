"""复盘摘要 / 事件回放的 pydantic 响应模型（issue #77 §2 新增端点）。

`GET /rooms/{roomId}/summary` 依赖 AI 编排生成复盘内容（归 #48/#68），本期
固定返回 `NOT_IMPLEMENTED`。`GET /rooms/{roomId}/replay` 则是真实实现——
读的是 ws.py 在 narration.push / action.submit 时写入的 `events` 表，是本期
少数"服务端真的在写、也真的在读"的完整数据闭环之一。
"""

from datetime import datetime

from app.dto.common import CamelModel


class RoomSummaryRead(CamelModel):
    """GET /api/v1/rooms/{roomId}/summary 返回。"""

    room_id: str
    summary_text: str | None = None
    highlights: list[str] | None = None


class ReplayEventRead(CamelModel):
    """GET /api/v1/rooms/{roomId}/replay 返回项——对应 `events` 表的一行。"""

    model_config = {"from_attributes": True}
    id: str
    player_id: str | None = None
    event_type: str
    payload: dict
    created_at: datetime
