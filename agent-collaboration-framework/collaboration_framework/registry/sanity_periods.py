"""CoC7 game-period accounting with explicit, non-retroactive upgrade boundaries."""

from collaboration_framework.contracts.sanity import SanityLedger, SanityWindow


def new_ledger(san, absolute_hour, boundary="keeper_rest"):
    if san is None:
        return SanityLedger()
    return SanityLedger(
        window=SanityWindow(
            id=f"day:{absolute_hour // 24}"
            if boundary == "world_day"
            else "rest:initial",
            day_index=absolute_hour // 24,
            start_absolute_hour=absolute_hour,
            start_sequence=0,
            baseline_san=san,
        )
    )


def ensure_window(runtime, actor_id, ledger):
    if ledger.window is not None:
        return ledger
    san = runtime.game_state.actors[actor_id].resources.san
    if san is None:
        return ledger
    # The old schema did not retain a period baseline. This is a new, declared
    # coverage boundary, never a reconstruction of losses earlier in that day.
    window = SanityWindow(
        id=f"upgrade:{runtime.revision}",
        day_index=runtime.game_state.world_time.current.day_index,
        start_absolute_hour=runtime.game_state.world_time.current.absolute_hour,
        start_sequence=runtime.game_state.event_sequence,
        baseline_san=san,
        coverage="upgrade_cutover",
    )
    return ledger.model_copy(
        update={
            "window": window,
            "history_gaps": tuple(
                dict.fromkeys((*ledger.history_gaps, "period_baseline_missing"))
            ),
        }
    )


def count_loss(ledger, loss):
    def add(window):
        if window.id != loss.window_id or loss.outcome_id in window.consumed_outcomes:
            return window
        return window.model_copy(
            update={
                "loss_total": window.loss_total + loss.actual,
                "consumed_outcomes": (*window.consumed_outcomes, loss.outcome_id),
            }
        )

    return ledger.model_copy(
        update={
            "window": add(ledger.window) if ledger.window else None,
            "previous_windows": tuple(
                add(window) for window in ledger.previous_windows
            ),
        }
    )


def reset_window(state, actor_id, ledger, key, sequence):
    from .sanity_ledger import replace_ledger

    if ledger.window is not None and ledger.window.id == key:
        return state
    san = state.actors[actor_id].resources.san
    if san is None:
        return state
    window = SanityWindow(
        id=key,
        day_index=state.world_time.current.day_index,
        start_absolute_hour=state.world_time.current.absolute_hour,
        start_sequence=sequence,
        baseline_san=san,
    )
    history = (
        (*ledger.previous_windows, ledger.window)
        if ledger.window
        else ledger.previous_windows
    )
    return replace_ledger(
        state,
        actor_id,
        ledger.model_copy(update={"window": window, "previous_windows": history}),
    )


def on_time_point(context):
    from .sanity_ledger import ledger_for

    state = context.state
    policy = context.runtime.module_content.sanity_policy
    if policy is None or policy.window_boundary != "world_day":
        return state
    day = state.world_time.current.day_index
    for actor_id in tuple(state.actors):
        runtime = context.runtime.model_copy(update={"game_state": state})
        ledger = ledger_for(runtime, actor_id)
        if ledger.window is not None and ledger.window.day_index == day:
            continue
        event = context.services.emit(
            "actor.sanity_window_started",
            {"actor_id": actor_id, "window_id": f"day:{day}"},
            visibility="hidden",
        )
        state = reset_window(state, actor_id, ledger, f"day:{day}", event.sequence)
    return state
