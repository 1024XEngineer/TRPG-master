"""运行时状态模型 —— 对应 master §4.5 GameState/PlayerState/Event/EventPayload。

GameState 是 God View（唯一真相），仅 core/rules.RulesEngine 可写。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from core.content.models import Rule  # noqa: F401  (供未来 Entity 规则相关扩展引用)


class PlayerState(BaseModel):
    player_id: str = Field(alias="playerId")
    character_id: str = Field(alias="characterId")
    location: str  # ★ 对应 characters.location，支持分头行动（ADR-12）
    san: int
    unknown_streak: int = Field(default=0, alias="unknownStreak")  # §6.6 脱本导回状态机计数

    model_config = {"populate_by_name": True}


class GameState(BaseModel):
    room_id: str = Field(alias="roomId")  # 🔴 2026-07-13 补：master §4.5 此前遗漏，见架构演进日志同日条目
    module_id: str = Field(alias="moduleId")
    phase: str  # 对应 §5.2.4 房间生命周期状态机
    players: list[PlayerState] = Field(default_factory=list)
    entity_states: dict[str, dict[str, Union[bool, int, float, str]]] = Field(
        default_factory=dict, alias="entityStates"
    )
    rolling_summary: Optional[str] = Field(default=None, alias="rollingSummary")  # §6.5 历史滚动摘要

    model_config = {"populate_by_name": True}


# ===== EventPayload：判别式联合类型（对应 master §4.5，2026-07-12 补 san.check.result） =====


class ActionSubmitPayload(BaseModel):
    type: Literal["action.submit"] = "action.submit"
    player_id: str = Field(alias="playerId")
    utterance: str
    input_mode: Literal["voice", "text"] = Field(alias="inputMode")

    model_config = {"populate_by_name": True}


class NarrationPushPayload(BaseModel):
    type: Literal["narration.push"] = "narration.push"
    scene_id: str = Field(alias="sceneId")
    persona: str
    text: str

    model_config = {"populate_by_name": True}


class TurnBoundaryPayload(BaseModel):
    type: Literal["turn.begin", "turn.end"]
    player_id: str = Field(alias="playerId")

    model_config = {"populate_by_name": True}


class CheckResultPayload(BaseModel):
    type: Literal["check.result"] = "check.result"
    player_id: str = Field(alias="playerId")
    skill: str
    roll: int
    target: int
    success: bool
    hidden: bool
    checkpoint_id: Optional[str] = Field(default=None, alias="checkpointId")

    model_config = {"populate_by_name": True}


class SanCheckResultPayload(BaseModel):
    """🆕 2026-07-12 补：此前只有技能检定（check.result）有落库变体，理智检定没有，
    会导致 GET /replay 漏掉理智检定历史，见 [[2026-07-12 架构规范自查与前端代码实际核对]]。
    """

    type: Literal["san.check.result"] = "san.check.result"
    player_id: str = Field(alias="playerId")
    san_loss_final: int = Field(alias="sanLossFinal")
    luck_spent: Optional[int] = Field(default=None, alias="luckSpent")

    model_config = {"populate_by_name": True}


class ClueGrantedPayload(BaseModel):
    type: Literal["clue.granted"] = "clue.granted"
    player_id: str = Field(alias="playerId")
    entity_id: str = Field(alias="entityId")

    model_config = {"populate_by_name": True}


class PlayerJoinedLeftPayload(BaseModel):
    type: Literal["player.joined", "player.left"]
    player_id: str = Field(alias="playerId")
    nickname: str

    model_config = {"populate_by_name": True}


class SystemMsgPayload(BaseModel):
    type: Literal["system.msg"] = "system.msg"
    text: str


class GameEndedPayload(BaseModel):
    type: Literal["game.ended"] = "game.ended"
    win_condition_id: str = Field(alias="winConditionId")
    text: str

    model_config = {"populate_by_name": True}


EventPayload = Annotated[
    Union[
        ActionSubmitPayload,
        NarrationPushPayload,
        TurnBoundaryPayload,
        CheckResultPayload,
        SanCheckResultPayload,
        ClueGrantedPayload,
        PlayerJoinedLeftPayload,
        SystemMsgPayload,
        GameEndedPayload,
    ],
    Field(discriminator="type"),
]


class Event(BaseModel):
    id: str
    room_id: str = Field(alias="roomId")  # 🔴 2026-07-13 补：master §4.5 此前遗漏，见架构演进日志同日条目
    ts: int
    player_id: Optional[str] = Field(default=None, alias="playerId")
    visibility: Literal["public", "scene", "private"]
    payload: EventPayload

    model_config = {"populate_by_name": True}
