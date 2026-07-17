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
from app.dto.room import RoomPlayerRead

# ── 客户端 → 服务端 ──────────────────────────────


class RoomJoinPayload(CamelModel):
    """room.join 事件 payload。

    `reconnect_token` 必填：它是玩家在这个房间里的身份密钥（`players.reconnect_token`，
    建房/加入时下发给本人）。WS 连接握手只校验了「你是某个登录账号」，但连接
    时带的 playerId 是任意的、而且被公开房间预览暴露——只认 playerId 会让任何
    登录用户绑定成别人（冒充房主 game.start / 提交行动，PR #78 review 指出）。
    绑定时要求出示该玩家的 reconnect_token，才能证明「你就是这个玩家本人」。

    roomCode/nickname 是前端沿用原型习惯发送的冗余字段，服务端不读，保留可选
    以免影响现有调用方。
    """

    reconnect_token: str = Field(..., min_length=1)
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


class CheckRollPayload(CamelModel):
    """check.roll 事件 payload（issue #77 新增）——玩家请求做一次技能检定。

    `skill` 必填：说清楚要检定哪个技能是这个动作本身的意义所在。这条链路
    本期是 NOT_IMPLEMENTED 桩（见 issue"三处原型取舍"表格——真正的服务端
    权威掷骰依赖规则引擎裁决，归 #48/#68），handler 校验完这个 payload 就
    直接回 `error` 事件，不会真的掷骰或读写 `check_results` 表。
    """

    skill: str = Field(..., min_length=1)


class SanCheckRollPayload(CamelModel):
    """san.check.roll 事件 payload（issue #77 新增）。

    定义一个空模型（而不是完全跳过校验）理由同 GameStartPayload：让它也走
    跟其它事件一致的"接收端过一次模型校验"路径。本期同样是 NOT_IMPLEMENTED 桩。
    """


class RoomRejoinPayload(CamelModel):
    """room.rejoin 事件 payload（issue #77 新增，仅铺协议，见决策 6）。

    `reconnect_token` 是房间身份体系的重连凭证（`players.reconnect_token`，
    不是账号登录 token），本期只校验格式、不做真实的断线重连逻辑。
    """

    reconnect_token: str = Field(..., min_length=1)


# ── 服务端 → 客户端 ──────────────────────────────


class SessionBoundPayload(CamelModel):
    """session.bound 推送 payload。"""

    room_id: str
    player_id: str


class NarrationPushPayload(CamelModel):
    """narration.push 推送 payload。"""

    text: str


class RoomStatePayload(CamelModel):
    """room.state 推送 payload（issue #77 新增，替代 HTTP 轮询伪广播）。

    本期协议槽位已留好（信封类型/校验器/SDK 方法齐全），但 ws.py 里没有任何
    地方会真的发出这个事件——大厅玩家列表仍然是前端 `GET /rooms/{roomCode}`
    轮询获取（issue"三处原型取舍"表格，真正切换依赖前端改动，本期不动
    trpg-frontend）。
    """

    room_id: str
    phase: str
    players: list[RoomPlayerRead]


class PlayerJoinedPayload(CamelModel):
    """player.joined 推送 payload（issue #77 新增，同上，本期不会真的发出）。"""

    player: RoomPlayerRead


class TurnBeginPayload(CamelModel):
    """turn.begin 推送 payload（issue #77 新增，回合制约束，本期不会真的发出）。"""

    player_id: str


class GameEndedPayload(CamelModel):
    """game.ended 推送 payload（issue #77 新增，触发复盘，本期不会真的发出）。"""

    reason: str | None = None


class ViewPrivatePayload(CamelModel):
    """view.private 推送 payload（issue #77 新增，私密视角/不泄底的载体）。

    本期协议槽位已留好，但 `narration.push` 仍然是全房间广播（issue
    "三处原型取舍"表格），没有任何地方会真的发出这个事件——真正的信息
    不对称需要规则引擎知道"这条叙事该给谁看"，归 #48/#68。
    """

    player_id: str
    text: str


class CheckRequestPayload(CamelModel):
    """check.request 推送 payload（issue #77 新增，本期不会真的发出）。"""

    player_id: str
    skill: str
    target_value: int | None = None


class CheckResultPayload(CamelModel):
    """check.result 推送 payload（issue #77 新增）。

    直接返回终值，不做两段式初步结果（issue 决策 4：幸运消耗机制推迟，
    协议一并简化）。本期不会真的发出。
    """

    player_id: str
    skill: str
    roll_value: int
    target_value: int | None = None
    result: str


class SanCheckRequestPayload(CamelModel):
    """san.check.request 推送 payload（issue #77 新增，本期不会真的发出）。"""

    player_id: str
    current_san: int | None = None


class SanCheckResultPayload(CamelModel):
    """san.check.result 推送 payload（issue #77 新增，同 CheckResultPayload
    直接返回终值，本期不会真的发出）。"""

    player_id: str
    roll_value: int
    san_loss: int
    result: str


class ClueGrantedPayload(CamelModel):
    """clue.granted 推送 payload（issue #77 新增，线索发现，本期不会真的发出）。"""

    player_id: str
    clue_name: str
    description: str | None = None


class ErrorPayload(CamelModel):
    """error 推送 payload（issue #77 新增）——本期唯一会被真的发出的新增
    S→C 事件：`check.roll`/`san.check.roll`/`room.rejoin` 这三个 NOT_IMPLEMENTED
    桩、以及原来 game.start 失败时被静默丢弃（`continue`，见 ws.py 旧逻辑）
    的错误，都改成通过这个事件明确告知发起者，而不是让客户端干等。
    """

    code: str
    message: str


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
