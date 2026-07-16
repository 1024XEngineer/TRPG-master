"""WebSocket 事件 payload 的 pydantic 模型（issue #75）。

在这之前，`/ws/{roomId}`（app/controller/ws.py）的 6 个事件全部是手搓的裸
dict——发送端直接 `send_json({"type": ..., "payload": {...}})`，接收端直接
`payload.get("ready")` / `payload.get("utterance")`。这意味着"把 Pydantic
模型导出成 JSON Schema 再生成 TS 类型"这条管线对 WS 完全无从谈起：没有模型
可导。这个文件把现有 6 个事件的 payload 补成真正的 Pydantic 模型，ws.py
也相应改成用这些模型收发（不再靠 .get() 兜底），管线才能覆盖到 WS。

跟 dto/room.py 等 REST DTO 一样使用 CamelModel：JSON 层 camelCase，Python 层
snake_case。

事件信封本身（C→S 的 `{type, playerId, payload}`、S→C 的 `{type, payload}`）
不在这里建模——`type` 是纯字符串字面量、`payload` 的具体形状随 `type` 变化，
用一个通用的信封模型没法表达"payload 形状取决于 type"这种判别关系，ws.py
里仍然按 `type` 分支后，把对应分支的 payload dict 交给下面某一个模型做校验，
维持了跟其它 DTO 一样的一比一颗粒度（一个事件的 payload = 一个模型）。
"""

from app.dto.common import CamelModel

# ── 客户端 → 服务端 ──────────────────────────────


class RoomJoinPayload(CamelModel):
    """room.join 事件 payload。

    handler 目前不读取这里的任何字段——房间 ID 来自 URL 路径，玩家身份来自
    信封的 playerId，roomCode/nickname 是前端沿用 trpg-app 原型习惯发送的
    冗余字段。两个字段都设默认值，是因为现有测试/部分调用路径会发送空
    payload（见 tests/test_ws.py），模型必须能校验通过。
    """

    room_code: str | None = None
    nickname: str | None = None


class PlayerReadyPayload(CamelModel):
    """player.ready 事件 payload。"""

    ready: bool = False


class GameStartPayload(CamelModel):
    """game.start 事件 payload——目前不带任何字段。

    定义一个空模型（而不是完全跳过校验）是为了让 game.start 也走跟其它事件
    一致的"接收端过一次模型校验"路径，行为对齐、不搞特例。
    """


class ActionSubmitPayload(CamelModel):
    """action.submit 事件 payload。"""

    utterance: str = ""


# ── 服务端 → 客户端 ──────────────────────────────


class SessionBoundPayload(CamelModel):
    """session.bound 推送 payload。"""

    room_id: str
    player_id: str


class NarrationPushPayload(CamelModel):
    """narration.push 推送 payload。"""

    text: str
