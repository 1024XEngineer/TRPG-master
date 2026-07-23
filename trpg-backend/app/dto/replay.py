"""复盘摘要 / 事件回放的 pydantic 响应模型。

`GET /rooms/{roomId}/summary` 返回规则引擎在结局时生成的结构化复盘，
`GET /rooms/{roomId}/replay` 按事件序号返回玩家可见的房间事件。
"""

from app.dto.common import CamelModel, UtcDatetime


class RoomSummaryRead(CamelModel):
    """GET /api/v1/rooms/{roomId}/summary 返回。"""

    room_id: str
    summary_text: str | None = None
    highlights: list[str] | None = None
    ending_id: str | None = None
    outcome: str | None = None
    structured_data: dict | None = None


class ReplayEventRead(CamelModel):
    """GET /api/v1/rooms/{roomId}/replay 返回项——对应 `events` 表的一行。"""

    model_config = {"from_attributes": True}
    id: str
    player_id: str | None = None
    event_type: str
    payload: dict
    sequence: int | None = None
    state_revision: int | None = None
    created_at: UtcDatetime
