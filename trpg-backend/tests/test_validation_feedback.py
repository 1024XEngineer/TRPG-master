from collaboration_framework.contracts import (
    ActorBindingError,
    AdjudicationValidationError,
    ContractError,
    ValidationResult,
)
from pydantic import BaseModel, ValidationError

from app.controller.ws import _map_turn_error


def test_turn_error_uses_player_safe_validation_projection() -> None:
    error = AdjudicationValidationError(
        ValidationResult(
            status="rejected",
            code="CANON_SHADOW",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="当前目标不可用于这次行动",
            internal_reason="keeper-only canon entity exists at requested id",
            classification_coverage="partial_validation_failure",
        )
    )

    code, message, retryable = _map_turn_error(error)

    assert code == "TARGET_UNAVAILABLE"
    assert message == "当前目标不可用于这次行动"
    assert retryable is False
    assert "keeper" not in message


def test_only_revision_refresh_feedback_is_client_retryable() -> None:
    error = AdjudicationValidationError(
        ValidationResult(
            status="rejected",
            code="SOURCE_REVISION_STALE",
            repairability="retry_with_latest_revision",
            fault="player",
            player_safe_reason="动作基于过期的玩家视图，请刷新后重试",
            classification_coverage="partial_validation_failure",
        )
    )

    assert _map_turn_error(error) == (
        "SOURCE_REVISION_STALE",
        "动作基于过期的玩家视图，请刷新后重试",
        True,
    )


def test_contract_invalid_is_retryable_because_the_same_words_often_pass() -> None:
    """#313：`TURN_CONTRACT_INVALID` 后原话重试成功，说明它是非确定性失败。

    这是「模型这一次的输出没过契约」的兜底桶，和 `MODEL_OUTPUT_UNREADABLE` 同源。
    标成不可重试会让前端连重试按钮都不给（`actionErrorRetryable`），把一次重掷就
    能过的失败变成玩家必须自己重新打字的死路。
    """

    class _Probe(BaseModel):
        value: int

    try:
        _Probe(value="not-an-int")
    except ValidationError as exc:
        validation_error: Exception = exc

    for error in (ContractError("主持编排契约校验失败"), validation_error):
        code, message, retryable = _map_turn_error(error)
        assert code == "TURN_CONTRACT_INVALID"
        assert retryable is True
        assert "重试" in message


def test_actor_binding_error_keeps_stable_public_code() -> None:
    assert _map_turn_error(ActorBindingError("player_id/actor_id 未绑定到当前房间")) == (
        "ACTOR_NOT_CONTROLLED",
        "当前玩家不能控制该局内角色",
        False,
    )
