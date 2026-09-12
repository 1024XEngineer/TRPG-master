import pytest
from pydantic import ValidationError

from app.core.host_rule_loop import RuleLoopStep, new_rule_loop


def test_rule_loop_state_is_versioned_and_scoped() -> None:
    state = new_rule_loop(client_action_id="action-1", player_id="player-1", actor_id="actor-1")
    step = RuleLoopStep(
        index=0,
        step_id="action-1:rule:0",
        request_id="action-1:rule:0",
        source_revision="7",
        rule_id="unlock",
        option_id="pick",
    )
    updated = state.model_copy(update={"steps": (step,), "step_index": 1})
    restored = type(state).model_validate(updated.dump())
    assert restored.schema_version == 1
    assert restored.current() == step
    assert restored.step_index == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("step_id", "another-action:rule:0"),
        ("request_id", "another-action:rule:0"),
        ("feedback_correlation_id", "another-action:step:0"),
        ("index", 1),
    ],
)
def test_recovery_rejects_a_step_from_another_action(field, value) -> None:
    state = new_rule_loop(client_action_id="action-1", player_id="player-1", actor_id="actor-1")
    step = RuleLoopStep(
        index=0,
        step_id="action-1:rule:0",
        request_id="action-1:rule:0",
        source_revision="1",
        rule_id="observe",
        option_id="door",
    ).model_dump(mode="json")
    step[field] = value
    with pytest.raises(ValidationError):
        type(state).model_validate({**state.dump(), "steps": [step]})
