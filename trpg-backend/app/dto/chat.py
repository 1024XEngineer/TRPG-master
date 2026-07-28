"""讨论区消息的 REST DTO（issue #107）。

`GET /rooms/{roomId}/messages` 的返回体。字段跟 WS 广播的
`ChatMessagePayload`（app/dto/ws.py）保持一致——同一条消息不管是实时广播
收到的还是刷新后从历史接口拉回的，客户端看到的形状都一样，渲染层不需要
两套适配逻辑。
"""

from app.dto.common import CamelModel, UtcDatetime


class ChatMessageRead(CamelModel):
    """讨论区一条消息。`sent_at` 用 UtcDatetime（对外时间字段的统一约定，
    见 app/dto/common.py）。"""

    message_id: str
    player_id: str
    nickname: str
    text: str
    sent_at: UtcDatetime
    client_message_id: str
