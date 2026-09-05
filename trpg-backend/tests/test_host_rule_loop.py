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
