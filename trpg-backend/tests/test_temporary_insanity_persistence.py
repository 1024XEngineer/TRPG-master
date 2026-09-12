"""Recover the same INT decision and sampled conditions through SQL Store."""

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    CheckDecisionRequest,
    GetAdjudicationStatusRequest,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import AdjudicationEngineService, DiceRoller, SequenceDiceSource

from tests.test_issue398_passive_check import _committed_state
from tests.test_sanity_habituation_persistence import accept_check, prepare_chain


async def prepare_int(db, factory):
    room_id, player_id, actor_id, execution = await prepare_chain(db, factory, losses=("1d6",))
    execution, loss_request = await accept_check(
        factory, room_id, player_id, execution, loss=5, tag="san"
    )
    assert execution.pending_decision is not None
    status = await AdjudicationEngineService(factory()).get_status(
        GetAdjudicationStatusRequest(
            room_id=room_id, player_id=player_id, action_request_id=execution.action_request_id
        )
    )
    assert status.execution is not None
    assert status.execution.pending_decision is not None
    assert status.execution.pending_decision.decision_id == execution.pending_decision.decision_id
    pending = status.execution.pending_decision
    rolled = await AdjudicationEngineService(
        factory(), dice=DiceRoller(SequenceDiceSource([21]))
    ).decide(
        CheckDecisionRequest(
            room_id=room_id,
            player_id=player_id,
            request_id="int-roll",
            source_revision=status.execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    check = rolled.check_run
    assert check is not None
    request = PostRollDecisionRequest(
        room_id=room_id,
        player_id=player_id,
        request_id="int-accept",
        source_revision=rolled.view_revision,
        check_id=check.check_id,
        check_version=check.version,
        option_id="accept-current",
    )
    return actor_id, request


async def test_int_recovery_after_precommit_crash_keeps_one_loss_and_same_durations(
    db_session, engine_store_factory
):
    actor_id, request = await prepare_int(db_session, engine_store_factory)

    def crash(_room_id):
        raise RuntimeError("before-insanity-commit")

    with pytest.raises(RuntimeError, match="before-insanity-commit"):
        await AdjudicationEngineService(
            engine_store_factory(before_commit=crash),
            dice=DiceRoller(SequenceDiceSource([8, 3, 2])),
        ).decide_post_roll(request)
    db_session.expire_all()
    state = await _committed_state(db_session, request.room_id)
    assert state.actors[actor_id].resources.san == 55
    assert not state.actors[actor_id].conditions
    assert not state.time_tasks
    recovered_request = request.model_copy(update={"request_id": "int-recovered"})
    result = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([1, 1, 1]))
    ).decide_post_roll(recovered_request)
    db_session.expire_all()
    state = await _committed_state(db_session, request.room_id)
    actor = state.actors[actor_id]
    assert actor.sanity is not None
    assert len(actor.sanity.losses) == 1
    assert actor.sanity.bouts[0].duration_hours == 2
    assert actor.sanity.bouts[0].type_roll == 3
    assert (
        next(c for c in actor.condition_states if c.condition_id == "temporary_insanity").details[
            "duration_hours"
        ]
        == 8
    )
    assert not state.rule_agendas
    replay = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([]))
    ).decide_post_roll(recovered_request)
    assert replay.event_refs == result.event_refs


async def test_hour_expiry_survives_session_restart_and_preserves_unrelated_conditions(
    db_session, engine_store_factory
):
    actor_id, request = await prepare_int(db_session, engine_store_factory)
    await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([8, 3, 2]))
    ).decide_post_roll(request)
    db_session.expire_all()
    before = await _committed_state(db_session, request.room_id)
    start = before.world_time.current.absolute_hour
    steps = 0
    while True:
        async with engine_store_factory().transaction(request.room_id) as tx:
            runtime = await tx.load_runtime()
        if runtime.game_state.world_time.current.absolute_hour >= start + 8:
            break
        action = ActionAdjudication(
            request_id=f"time-{steps}",
            source_revision=runtime.revision,
            actor_id=actor_id,
            summary="等待",
            target=ActionTarget(kind="location", id=runtime.game_state.scene_id),
            method=ActionMethod(family="rest", description="等待"),
            check=NoAdjudicationCheck(),
            success_effects=(AdvanceWorldTimeEffect(),),
        )
        await AdjudicationEngineService(engine_store_factory()).submit(
            SubmitAdjudicationRequest(
                room_id=request.room_id, player_id=request.player_id, adjudication=action
            )
        )
        steps += 1
        assert steps < 8
    db_session.expire_all()
    state = await _committed_state(db_session, request.room_id)
    assert state.actors[actor_id].resources.san == 55
    assert not state.actors[actor_id].conditions
    assert all(task.status == "completed" for task in state.time_tasks.values())
