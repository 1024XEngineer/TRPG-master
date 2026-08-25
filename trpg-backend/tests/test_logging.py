from __future__ import annotations

import logging

from collaboration_framework.engine import StateModifiedEvent
from structlog.testing import capture_logs

from app.core.logging import AccessNoiseFilter
from app.core.turn_observability import (
    log_action_plan_latency,
    log_check_result,
    log_narration_output,
    log_player_input,
    log_state_changes,
    log_turn_completed,
    log_turn_failed,
)


def _access_record(method: str, path: str, status_code: int) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1000", method, path, "1.1", status_code),
        exc_info=None,
    )


def test_access_noise_filter_drops_only_successful_noise() -> None:
    access_filter = AccessNoiseFilter()

    assert access_filter.filter(_access_record("OPTIONS", "/api/v1/rooms/ABC123", 200)) is False
    assert access_filter.filter(_access_record("GET", "/api/v1/rooms/ABC123", 200)) is False
    assert (
        access_filter.filter(
            _access_record(
                "GET",
                "/api/v1/rooms/7561a0b7-01c4-4209-87ae-15618f692e87/conversation",
                200,
            )
        )
        is False
    )
    assert access_filter.filter(_access_record("GET", "/api/v1/health", 200)) is False

    assert access_filter.filter(_access_record("GET", "/api/v1/rooms/ABC123", 503)) is True
    assert access_filter.filter(_access_record("OPTIONS", "/api/v1/rooms/ABC123", 403)) is True
    assert access_filter.filter(_access_record("POST", "/api/v1/rooms/ABC123/end", 200)) is True
    assert access_filter.filter(_access_record("GET", "/api/v1/games", 200)) is True


def test_turn_business_logs_are_readable_and_correlated() -> None:
    state_event = StateModifiedEvent.model_validate(
        {
            "event_id": "evt_0001",
            "sequence": 1,
            "room_id": "7561a0b7-01c4-4209-87ae-15618f692e87",
            "actor_id": "actor-1",
            "client_action_id": "action-1",
            "cause": "observe_caretaker.success",
            "visibility": "public",
            "payload": {
                "path": "entities.melodias.bottle_noticed",
                "from": False,
                "to": True,
            },
        }
    )

    with capture_logs() as logs:
        log_player_input(
            room_id=state_event.room_id,
            player_id="player-12345678",
            character_name="杜调查员",
            correlation_id="action-1",
            utterance="我仔细观察\n墓地看守",
        )
        log_check_result(
            room_id=state_event.room_id,
            correlation_id="action-1",
            character_name="杜调查员",
            skill_name="侦查",
            target_value=60,
            roll_value=23,
            difficulty="hard",
            success_level="hard",
            passed=True,
        )
        log_state_changes(
            room_id=state_event.room_id,
            correlation_id="action-1",
            events=(state_event,),
        )
        log_narration_output(
            room_id=state_event.room_id,
            correlation_id="action-1",
            text="你注意到看守的口袋里露出一截玻璃瓶。",
            clarification=False,
        )
        log_turn_completed(
            room_id=state_event.room_id,
            correlation_id="action-1",
            intent_summary="观察墓地看守",
            resolution="checkpoint",
            outcome="success",
            revision="1",
            duration_ms=42,
            narration_sent=True,
        )

    assert [item["event"] for item in logs] == [
        "【回合开始】玩家输入",
        "【检定结果】",
        "【状态修改】",
        "【叙事输出】",
        "【回合完成】",
    ]
    assert logs[0]["input"] == "我仔细观察 墓地看守"
    assert logs[1]["result"] == "困难成功"
    assert logs[2]["before"] == "false"
    assert logs[2]["after"] == "true"
    assert logs[3]["text"] == "你注意到看守的口袋里露出一截玻璃瓶。"
    assert logs[4]["action"] == "action-1"
    assert logs[4]["narration"] == "已发送"


def test_turn_failure_log_has_stable_diagnostics() -> None:
    with capture_logs() as logs:
        log_turn_failed(
            room_id="room-12345678",
            correlation_id="action-2",
            stage="检定结算",
            code="DATABASE_CONFLICT",
            error_type="OperationalError",
        )

    assert logs == [
        {
            "room": "room",
            "action": "action-2",
            "stage": "检定结算",
            "code": "DATABASE_CONFLICT",
            "error_type": "OperationalError",
            "error_reason": "",
            "event": "【回合失败】",
            "log_level": "warning",
        }
    ]


def test_action_plan_latency_log_contains_only_safe_aggregate_fields() -> None:
    with capture_logs() as logs:
        log_action_plan_latency(
            room_id="room-12345678-secret",
            correlation_id="action-12345678-secret",
            status="completed",
            time_to_waiting_check_ms=None,
            time_to_first_narration_ms=37,
            time_to_final_narration_ms=42,
            end_to_end_ms=42,
        )

    assert logs == [
        {
            "room": "room",
            "action": "action",
            "status": "completed",
            "time_to_waiting_check_ms": None,
            "time_to_first_narration_ms": 37,
            "time_to_final_narration_ms": 42,
            "end_to_end_ms": 42,
            "event": "action_plan_turn_latency",
            "log_level": "info",
        }
    ]
