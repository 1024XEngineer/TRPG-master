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

from typing import Any, Literal

from collaboration_framework.contracts import (
    CheckRunView,
    PendingCheckDecisionView,
    PlayerView,
)
from pydantic import Field, field_validator, model_validator

from app.dto.common import CamelModel, UtcDatetime
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
    """action.plan.submit 事件 payload。

    `client_action_id` 是客户端为一次逻辑动作生成的稳定幂等键；网络重试必须
    复用原值。两个字段都在契约层拒绝空白文本。
    """

    client_action_id: str = Field(..., min_length=1, max_length=200)
    utterance: str = Field(..., min_length=1, max_length=2000)
    summarized_from: list[str] | None = None
    visibility: Literal["public", "private"] | None = None

    @field_validator("client_action_id", "utterance")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class CheckRollPayload(CamelModel):
    """为待处理动作提交玩家选择的技能与 D100 结果。"""

    client_action_id: str = Field(..., min_length=1, max_length=200)
    skill: str = Field(..., min_length=1)
    roll_value: int = Field(..., ge=1, le=100)


class AdjudicationChoicePayload(CamelModel):
    """Choose or cancel a v3 Engine-owned pending skill decision."""

    client_action_id: str = Field(..., min_length=1, max_length=200)
    request_id: str = Field(..., min_length=1, max_length=200)
    source_revision: str = Field(..., min_length=1)
    decision_id: str = Field(..., min_length=1)
    decision_version: int = Field(..., ge=1)
    candidate_id: str | None = Field(default=None, min_length=1)
    cancel: bool = False


class AdjudicationPostRollPayload(CamelModel):
    """Resolve a v3 Engine-owned post-roll decision."""

    client_action_id: str = Field(..., min_length=1, max_length=200)
    request_id: str = Field(..., min_length=1, max_length=200)
    source_revision: str = Field(..., min_length=1)
    check_id: str = Field(..., min_length=1)
    check_version: int = Field(..., ge=1)
    option_id: str = Field(..., min_length=1)
    revised_method: str | None = Field(default=None, min_length=1, max_length=1000)


class ActionPlanCancelPayload(CamelModel):
    client_action_id: str = Field(..., min_length=1, max_length=200)
    request_id: str = Field(..., min_length=1, max_length=200)


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


class ChatSendPayload(CamelModel):
    """chat.send 讨论区消息；该通道不会进入 Host Agent 上下文。"""

    text: str = Field(..., min_length=1, max_length=2000)
    client_message_id: str = Field(..., min_length=1, max_length=64)


class TimeAdvanceRespondPayload(CamelModel):
    """玩家对一个冻结的共享时间推进提案作出同意或拒绝。"""

    proposal_id: str = Field(..., min_length=1, max_length=100)
    proposal_version: int = Field(..., ge=1)
    source_revision: str = Field(..., min_length=1)
    accept: bool


# ── 服务端 → 客户端 ──────────────────────────────


class SessionBoundPayload(CamelModel):
    """session.bound 推送 payload。"""

    room_id: str
    player_id: str


class NarrationPushPayload(CamelModel):
    """narration.push 推送 payload。"""

    message_id: str | None = Field(default=None, min_length=1)
    text: str


class NarrationChunkPayload(CamelModel):
    """narration.chunk 推送 payload（issue #203）。

    片段只是同一条 `narration.push` 的渐进展示形式，不是权威消息：服务端先
    生成并校验完整叙事、落库去重成功，才按句切片下发，最后再发权威的
    `narration.push`。客户端按 `messageId` 归组、按 `sequence` 排序去重，
    拼接结果必须与最终 `narration.push` 的 `text` 完全一致；历史恢复和持久化
    始终只认 `narration.push`，临时拼接内容不得写入权威历史。
    """

    message_id: str = Field(..., min_length=1)
    sequence: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)


class OpeningStartedPayload(CamelModel):
    """权威开场正在由 Host 模型生成；模板模式不会发送。"""

    message_id: str = Field(..., min_length=1)


class ChatMessagePayload(CamelModel):
    """chat.message 讨论区广播 payload。"""

    message_id: str
    player_id: str
    nickname: str
    text: str
    sent_at: UtcDatetime
    client_message_id: str


class TimeAdvancePendingPayload(CamelModel):
    """广播完整待确认状态，供所有客户端幂等覆盖本地确认条。"""

    proposal_id: str
    proposal_version: int = Field(..., ge=1)
    source_revision: str
    target_point_id: str
    target_day_index: int = Field(..., ge=0)
    target_hour_of_day: int = Field(..., ge=0, le=23)
    requester_player_id: str
    required_player_ids: list[str]
    accepted_player_ids: list[str]
    expires_at: UtcDatetime


class TimeAdvanceResolvedPayload(CamelModel):
    """广播提案终态；批准时附带已经提交的权威世界时间。"""

    proposal_id: str
    status: Literal["approved", "rejected", "expired", "stale"]
    target_day_index: int = Field(..., ge=0)
    target_hour_of_day: int = Field(..., ge=0, le=23)
    committed_revision: str | None = None


class RoomActionStatePayload(CamelModel):
    """房间当前行动所有权的可重放快照，不包含模型计划或私密裁决。"""

    status: Literal["idle", "processing", "awaiting_player"]
    player_id: str | None = None
    actor_id: str | None = None
    client_action_id: str | None = None
    started_at: UtcDatetime | None = None
    revision: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_owner(self) -> "RoomActionStatePayload":
        owner = (self.player_id, self.actor_id, self.client_action_id, self.started_at)
        if self.status == "idle" and any(value is not None for value in owner):
            raise ValueError("idle 行动状态不得包含行动所有者")
        if self.status != "idle" and any(value is None for value in owner):
            raise ValueError("非 idle 行动状态必须包含完整行动所有者")
        return self


class ActionBroadcastPayload(CamelModel):
    """action.plan.submit 原话广播 payload。"""

    player_id: str
    client_action_id: str
    nickname: str
    character_name: str | None = None
    utterance: str


class TurnStartedPayload(CamelModel):
    correlation_id: str


class TurnPhaseChangedPayload(CamelModel):
    correlation_id: str
    phase: Literal[
        "reading_player_view",
        "understanding_action",
        "waiting_for_check",
        "executing_action",
        "refreshing_player_view",
        "generating_narration",
    ]


class ToolStartedPayload(CamelModel):
    correlation_id: str
    tool_name: str
    public_progress_label: str


class ToolCompletedPayload(CamelModel):
    correlation_id: str
    tool_name: str
    status: Literal["success", "error"]


class TurnFailedPayload(CamelModel):
    correlation_id: str
    code: str
    public_message: str
    retryable: bool


class PlanProgressPayload(CamelModel):
    correlation_id: str
    current_step: int = Field(..., ge=1)
    completed_steps: int = Field(..., ge=0)
    total_steps: int = Field(..., ge=2)
    phase: Literal[
        "understanding",
        "executing",
        "waiting_for_player",
        "stopped",
        "completed",
    ]
    public_progress_label: str | None = None
    safe_reason: str | None = None


class AdjudicationPendingPayload(CamelModel):
    correlation_id: str
    plan_id: str | None = None
    source_revision: str
    status: Literal["awaiting_skill_choice", "awaiting_post_roll_decision"]
    pending_decision: PendingCheckDecisionView | None = None
    check_run: CheckRunView | None = None


class ViewUpdatedPayload(CamelModel):
    player_id: str
    player_view: PlayerView


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


class CheckSkillOptionPayload(CamelModel):
    """A player-owned skill that may be selected for the pending check."""

    id: str
    name: str
    target_value: int = Field(..., ge=0)


class CheckRequestPayload(CamelModel):
    """向动作发起者推送经 Actor 技能值过滤后的可用检定项。"""

    player_id: str
    client_action_id: str
    summary: str
    difficulty: Literal["regular", "hard", "extreme"]
    skills: list[CheckSkillOptionPayload]


class CheckResultPayload(CamelModel):
    """check.result 推送最终权威结果。

    保留原始骰点，并通过 resolution_kind / luck_spent 说明幸运等 post-roll
    结算，避免把未达标骰点直接展示成普通成功（issue #327）。
    """

    player_id: str
    client_action_id: str
    skill: str
    skill_name: str
    character_name: str | None = None
    roll_value: int
    target_value: int
    difficulty: Literal["regular", "hard", "extreme"]
    success_level: Literal[
        "critical",
        "extreme",
        "hard",
        "regular",
        "failure",
        "fumble",
    ]
    passed: bool
    result: str
    resolution_kind: Literal["initial_roll", "accept_result", "spend_luck", "push"] = "initial_roll"
    luck_spent: int | None = Field(default=None, ge=1)


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
    correlation_id: str | None = None


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
