from collaboration_framework.contracts import (
    AdjudicationValidationError,
    ValidationResult,
)

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
