"""持久化动作族覆盖观测测试。

本文件确保开放动作族未命中策略表时只产生诊断，不改变既有裁决结果。
"""

import logging

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    NoAdjudicationCheck,
)
from collaboration_framework.engine.persistent_results import (
    validate_persistent_effects,
)


def test_unknown_family_is_observable_without_changing_validation(caplog) -> None:
    adjudication = ActionAdjudication(
        request_id="unknown-family-observation",
        source_revision="revision-1",
        actor_id="actor-1",
        summary="观察周围",
        target=ActionTarget(kind="location", id="library"),
        method=ActionMethod(family="  观察  ", description="观察周围"),
        check=NoAdjudicationCheck(),
    )

    with caplog.at_level(logging.INFO):
        result = validate_persistent_effects(adjudication)

    assert result is None
    assert "persistent_family_policy_missing" in caplog.text
    record = next(item for item in caplog.records if item.message == "persistent_family_policy_missing")
    assert record.family == "观察"
    assert record.persistence_intent == "none"
