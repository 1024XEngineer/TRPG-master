"""Cumulative threshold and calendar recovery survive independent SQL sessions."""

from copy import deepcopy

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import AdjudicationEngineService, DiceRoller, SequenceDiceSource
from sqlalchemy import select

from app.models.engine import GameEvent
from tests.test_issue398_passive_check import _committed_state
from tests.test_sanity_habituation_persistence import accept_check, prepare_chain


def treatment_module(payload):
    payload["sanity_policy"] = {
        "bout_mode": "summary",
        "window_boundary": "world_day",
        "calendar_anchor": "1924-01-31",
    }
    original = payload["rules"][0]
    commands = {
        "start": (
            "coc7.start_treatment",
            {"treatment_id": "care", "kind": "private", "safe": True},
        ),
        "review": (
            "coc7.review_treatment",
            {"treatment_id": "care", "review_month": 1, "safe": True},
        ),
    }
    for name, (action_id, parameters) in commands.items():
        rule = deepcopy(original)
        rule["id"] = "command_" + name
        rule["trigger"] = {
            "kind": "event",
            "event_type": "entity.state_changed",
            "entry_branch_id": "default",
            "when": {
                "op": "predicate",
                "predicate": "entity_state_is",
                "args": {"entity_id": "cemetery_figure", "key": "test_command", "value": name},
            },
        }
        rule["execution"] = {
            "branches": [{"id": "default", "entry_step_id": "invoke"}],
            "steps": [
                {
                    "id": "invoke",
                    "kind": "invoke_ruleset_action",
                    "action_id": action_id,
                    "actor_binding": "actor",
                    "parameters": parameters,
                    "next_step_id": "finish",
                },
                {"id": "finish", "kind": "finish"},
            ],
        }
        payload["rules"].append(rule)


async def command(factory, room, player, actor, tag, *, name=None):
    async with factory().transaction(room) as tx:
        runtime = await tx.load_runtime()
    effect = (
        ChangeEntityStateEffect(entity_id="cemetery_figure", key="test_command", value=name)
        if name
        else AdvanceWorldTimeEffect()
    )
    return SubmitAdjudicationRequest(
        room_id=room,
        player_id=player,
        adjudication=ActionAdjudication(
            request_id=tag,
            source_revision=runtime.revision,
            actor_id=actor,
            summary="治疗或等待",
            target=ActionTarget(kind="location", id=runtime.game_state.scene_id),
            method=ActionMethod(family="rest", description="休养"),
            check=NoAdjudicationCheck(),
            success_effects=(effect,),
        ),
    )


async def prepare_threshold(db, factory, *, care=False):
    room, player, actor, execution = await prepare_chain(
        db, factory, losses=("1d6",) * 4, cap=None, configure=treatment_module if care else None
    )
    for i, loss in enumerate((4, 4, 3)):
        execution, _ = await accept_check(
            factory, room, player, execution, loss=loss, tag=f"loss-{i}"
        )
    return room, player, actor, execution


async def test_threshold_precommit_retry_keeps_baseline_dice_and_one_insanity(
    db_session, engine_store_factory
):
    room, player, actor, execution = await prepare_threshold(db_session, engine_store_factory)
    pending = execution.pending_decision
    rolled = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([81]))
    ).decide(
        CheckDecisionRequest(
            room_id=room,
            player_id=player,
            request_id="last-roll",
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    check = rolled.check_run
    assert check is not None
    request = PostRollDecisionRequest(
        room_id=room,
        player_id=player,
        request_id="last-accept",
        source_revision=rolled.view_revision,
        check_id=check.check_id,
        check_version=check.version,
        option_id="accept-current",
    )

    def crash(_room):
        raise RuntimeError("threshold-precommit")

    with pytest.raises(RuntimeError, match="threshold-precommit"):
        await AdjudicationEngineService(
            engine_store_factory(before_commit=crash),
            dice=DiceRoller(SequenceDiceSource([1, 3, 2])),
        ).decide_post_roll(request)
    db_session.expire_all()
    state = await _committed_state(db_session, room)
    assert state.actors[actor].resources.san == 49
    ledger = state.actors[actor].sanity
    assert ledger is not None
    assert ledger.window is not None
    assert ledger.window.baseline_san == 60
    assert ledger.window.loss_total == 11
    assert not state.actors[actor].conditions
    retry = request.model_copy(update={"request_id": "restart-last"})
    result = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([6, 9, 9]))
    ).decide_post_roll(retry)
    assert result.pending_decision is None
    db_session.expire_all()
    state = await _committed_state(db_session, room)
    a = state.actors[actor]
    assert a.sanity is not None
    assert a.sanity.window is not None
    assert a.resources.san == 48
    assert a.sanity.window.loss_total == 12
    assert len(a.sanity.losses) == 4
    assert len(a.sanity.bouts) == 1
    assert (a.sanity.bouts[0].type_roll, a.sanity.bouts[0].duration_roll) == (3, 2)
    replay = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([]))
    ).decide_post_roll(retry)
    assert replay.event_refs == result.event_refs
    events = (
        await db_session.scalars(
            select(GameEvent).where(GameEvent.room_id == room).order_by(GameEvent.sequence)
        )
    ).all()
    assert sum(e.type == "actor.indefinite_insanity" for e in events) == 1
    assert len({e.sequence for e in events}) == len(events)


async def test_monthly_care_expiry_is_not_cure_and_recovery_retries_atomically(
    db_session, engine_store_factory
):
    room, player, actor, execution = await prepare_threshold(
        db_session, engine_store_factory, care=True
    )
    execution, _ = await accept_check(
        engine_store_factory, room, player, execution, loss=(1, 3, 2), tag="last"
    )
    start = await command(engine_store_factory, room, player, actor, "start-care", name="start")
    result = await AdjudicationEngineService(engine_store_factory()).submit(start)
    assert result.status == "resolved"
    for i in range(100):
        async with engine_store_factory().transaction(room) as tx:
            runtime = await tx.load_runtime()
        course = runtime.game_state.actors[actor].sanity.treatment
        if runtime.game_state.world_time.current.absolute_hour >= course.due_absolute_hour:
            break
        advance = await command(engine_store_factory, room, player, actor, f"month-{i}")
        await AdjudicationEngineService(engine_store_factory()).submit(advance)
    else:
        raise AssertionError("world time did not reach the review deadline")
    db_session.expire_all()
    state = await _committed_state(db_session, room)
    a = state.actors[actor]
    assert a.sanity is not None
    assert a.sanity.window is not None
    assert a.conditions == ("indefinite_insanity",)
    assert a.sanity.window.loss_total == 0
    assert a.sanity.window.baseline_san == 48
    assert not state.time_tasks
    assert a.sanity.treatment is not None
    assert a.sanity.treatment.review_due_notified
    review = await command(engine_store_factory, room, player, actor, "review-care", name="review")

    def crash(_room):
        raise RuntimeError("review-precommit")

    with pytest.raises(RuntimeError, match="review-precommit"):
        await AdjudicationEngineService(
            engine_store_factory(before_commit=crash),
            dice=DiceRoller(SequenceDiceSource([50, 3, 1])),
        ).submit(review)
    db_session.expire_all()
    unchanged = await _committed_state(db_session, room)
    assert unchanged.actors == state.actors
    assert unchanged.time_tasks == state.time_tasks
    result = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([99, 6, 9, 9]))
    ).submit(review)
    assert result.status == "resolved"
    db_session.expire_all()
    final = await _committed_state(db_session, room)
    assert final.actors[actor].resources.san == 51
    assert final.actors[actor].conditions == ()
    ledger = final.actors[actor].sanity
    assert ledger is not None
    assert ledger.treatment is not None
    assert ledger.treatment.status == "recovered"
    replay = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([]))
    ).submit(review)
    assert replay.event_refs == result.event_refs
    events = (
        await db_session.scalars(
            select(GameEvent).where(GameEvent.room_id == room).order_by(GameEvent.sequence)
        )
    ).all()
    assert sum(e.type == "actor.treatment_reviewed" for e in events) == 1
    assert len({e.sequence for e in events}) == len(events)
