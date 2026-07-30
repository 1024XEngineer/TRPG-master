"""面向本地开发终端的单回合可读业务日志。

业务事实仍由 ``events``、``game_events`` 和 ``action_executions`` 持久化；
这里仅在权威数据成功写入或回合成功完成后打印一份人类可读镜像，不参与恢复、
去重或规则判定。
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from collaboration_framework.engine import StateModifiedEvent

logger = structlog.get_logger()

_DIFFICULTY_LABELS = {
    "regular": "常规",
    "hard": "困难",
    "extreme": "极难",
}
_SUCCESS_LEVEL_LABELS = {
    "critical": "大成功",
    "extreme": "极难成功",
    "hard": "困难成功",
    "regular": "成功",
    "failure": "失败",
    "fumble": "大失败",
}


def _short_ref(value: str) -> str:
    return value.split("-", 1)[0][:8]


def _single_line(value: str, *, limit: int = 1200) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}…"


def _display_value(value: Any, *, limit: int = 400) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[: limit - 1]}…"


def log_player_input(
    *,
    room_id: str,
    player_id: str,
    character_name: str,
    correlation_id: str,
    utterance: str,
) -> None:
    logger.info(
        "【回合开始】玩家输入",
        room=_short_ref(room_id),
        action=correlation_id,
        player=_short_ref(player_id),
        character=character_name,
        input=_single_line(utterance),
    )


def log_check_result(
    *,
    room_id: str,
    correlation_id: str,
    character_name: str,
    skill_name: str,
    target_value: int,
    roll_value: int,
    difficulty: str,
    success_level: str,
    passed: bool,
) -> None:
    logger.info(
        "【检定结果】",
        room=_short_ref(room_id),
        action=correlation_id,
        character=character_name,
        skill=skill_name,
        target=target_value,
        roll=roll_value,
        difficulty=_DIFFICULTY_LABELS.get(difficulty, difficulty),
        result=_SUCCESS_LEVEL_LABELS.get(success_level, success_level),
        passed=passed,
    )


def log_state_changes(
    *,
    room_id: str,
    correlation_id: str,
    events: tuple[StateModifiedEvent, ...],
) -> None:
    for event in events:
        logger.info(
            "【状态修改】",
            room=_short_ref(room_id),
            action=correlation_id,
            path=event.payload.path,
            before=_display_value(event.payload.from_value),
            after=_display_value(event.payload.to),
            cause=event.cause,
            visibility=event.visibility,
        )


def log_narration_output(
    *,
    room_id: str,
    correlation_id: str | None,
    text: str,
    clarification: bool,
) -> None:
    logger.info(
        "【叙事输出】",
        room=_short_ref(room_id),
        action=correlation_id,
        kind="澄清" if clarification else "叙事",
        text=_single_line(text),
    )


def log_turn_completed(
    *,
    room_id: str,
    correlation_id: str,
    intent_summary: str,
    resolution: str,
    outcome: str,
    revision: str,
    duration_ms: int,
    narration_sent: bool,
) -> None:
    logger.info(
        "【回合完成】",
        room=_short_ref(room_id),
        action=correlation_id,
        intent=_single_line(intent_summary),
        resolution=resolution,
        outcome=outcome,
        revision=revision,
        duration_ms=max(0, duration_ms),
        narration="已发送" if narration_sent else "已去重",
    )


def log_turn_failed(
    *,
    room_id: str,
    correlation_id: str,
    stage: str,
    code: str,
    error_type: str,
    error_reason: str = "",
) -> None:
    logger.warning(
        "【回合失败】",
        room=_short_ref(room_id),
        action=correlation_id,
        stage=stage,
        code=code,
        error_type=error_type,
        error_reason=error_reason,
    )


__all__ = [
    "log_check_result",
    "log_narration_output",
    "log_player_input",
    "log_state_changes",
    "log_turn_completed",
    "log_turn_failed",
]
