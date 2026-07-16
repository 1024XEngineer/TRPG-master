"""WebSocket 事件 payload 的 pydantic 模型（issue #75）。

在这之前，`/ws/{roomId}`（app/controller/ws.py）的 6 个事件全部是手搓的裸
dict——发送端直接 `send_json({"type": ..., "payload": {...}})`，接收端直接
`payload.get("ready")` / `payload.get("utterance")`。这意味着"把 Pydantic
模型导出成 JSON Schema 再生成 TS 类型"这条管线对 WS 完全无从谈起：没有模型
可导。这个文件把现有 6 个事件的 payload 补成真正的 Pydantic 模型，ws.py
也相应改成用这些模型收发（不再靠 .get() 兜底），管线才能覆盖到 WS。

跟 dto/room.py 等 REST DTO 一样使用 CamelModel：JSON 层 camelCase，Python 层
snake_case。

信封（ClientEnvelope/ServerEnvelope，定义在文件最后）故意把 `payload` 留成
`dict[str, Any]`，不是每个事件各自一份"信封+具体 payload 类型"的判别联合：
`type` 是运行时才知道的字符串，payload 的具体形状要看 type 是什么，pydantic
的模型定义没法在"这个字段的类型"层面表达"取决于另一个字段的值"这种关系
（除非再手动叠一层 discriminated union，对只有 6～20 个事件的量级来说是过度
设计）。ws.py 里的用法是：先用 ClientEnvelope 解出 type/playerId/原始
payload dict，再按 type 分支，把 payload dict 交给下面对应的具体 payload
模型再校验一次——这样信封层和 payload 层各自都是真正在被使用的模型，而不是
为了"看起来完整"摆在这里的装饰品。信封模型不进 scripts/export_schema.py 的
导出清单：payload 是 `dict[str, Any]`，导出成 JSON Schema/TS 只会得到一个
`{[k: string]: unknown}`，对 SDK 没有实际价值——SDK 那边的信封类型
（ServerToClientEvent）继续手写，见 trpg-sdk/src/types.ts。
"""

from typing import Any

from pydantic import Field

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
    """player.ready 事件 payload。

    `ready` 必填、不给默认值：协议上「设置准备状态」这个动作必须说清楚要设成
    什么，缺字段是一条畸形消息，应该被丢弃，而不是被悄悄当成 `False` 处理。
    这里给默认值的代价不只在后端——它会顺着 codegen 变成 SDK 的
    `ready?: boolean`，让 `setReady(playerId, {})` 也能通过类型检查并静默地把
    玩家设成未准备（见 PR #76 review）。改动前的手写 SDK 类型本来就是必填的。
    """

    ready: bool


class GameStartPayload(CamelModel):
    """game.start 事件 payload——目前不带任何字段。

    定义一个空模型（而不是完全跳过校验）是为了让 game.start 也走跟其它事件
    一致的"接收端过一次模型校验"路径，行为对齐、不搞特例。
    """


class ActionSubmitPayload(CamelModel):
    """action.submit 事件 payload。

    `utterance` 必填，理由同 PlayerReadyPayload.ready：一条不带行动内容的
    action.submit 是畸形消息。给默认空串会让 SDK 侧变成 `utterance?: string`，
    于是 `submitAction(playerId, {})` 类型检查通过、运行时静默无操作。

    注意「必填」只管字段存在，空白内容（`""` / `"   "`）仍由下游的
    `strip()` + 空值判断拦掉，两者不冲突。
    """

    utterance: str


# ── 服务端 → 客户端 ──────────────────────────────


class SessionBoundPayload(CamelModel):
    """session.bound 推送 payload。"""

    room_id: str
    player_id: str


class NarrationPushPayload(CamelModel):
    """narration.push 推送 payload。"""

    text: str


# ── 信封 ────────────────────────────────────────


class ClientEnvelope(CamelModel):
    """客户端 → 服务端信封：`{type, playerId, payload}`。

    `payload` 留成未细分的 dict——具体形状要看 `type`，ws.py 拿到这层校验过
    的信封后，再按 `type` 把 `payload` 交给上面对应的具体 payload 模型校验。
    """

    type: str
    player_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ServerEnvelope(CamelModel):
    """服务端 → 客户端信封：`{type, payload}`。"""

    type: str
    payload: dict[str, Any]
