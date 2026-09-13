"""SAN settlement through the real published rule and SQL transaction."""

from collaboration_framework.contracts import (
    CheckDecisionRequest,
    PostRollDecisionRequest,
    SelectCheckChoice,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    SequenceDiceSource,
)

from app.models.engine import GameSession
from tests.test_engine_runtime import _start_room
from tests.test_issue398_passive_check import _arm_first_sight, _committed_state, _see_true_form


async def start_sanity_check(db, store_factory, *, san=60, roll=81):
    room, players, _ = await _start_room(db, room_number=195)
    room_id, player_id = room.id, players[0].id
    actor_id = await _arm_first_sight(db, room_id)
    session = await db.get(GameSession, room_id)
    state = GameState.model_validate(session.state_json)
    actor = state.actors[actor_id]
    from collaboration_framework.registry.sanity_periods import new_ledger

    state.actors[actor_id] = actor.model_copy(
        update={
            "resources": actor.resources.model_copy(update={"san": san}),
            "sanity": new_ledger(san, state.world_time.current.absolute_hour),
        }
    )
    session.state_json = state.to_json_dict()
    await db.commit()
    store = store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _see_true_form(room_id, player_id, actor_id, runtime.revision)
    )
    pending = execution.pending_decision
    assert pending is not None
    rolled = await AdjudicationEngineService(
        store_factory(), dice=DiceRoller(SequenceDiceSource([roll]))
    ).decide(
        CheckDecisionRequest(
            request_id="san-roll",
            room_id=room_id,
            player_id=player_id,
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    assert rolled.check_run is not None
    request = PostRollDecisionRequest(
        request_id="san-accept",
        room_id=room_id,
        player_id=player_id,
        source_revision=rolled.view_revision,
        check_id=rolled.check_run.check_id,
        check_version=rolled.check_run.version,
        option_id="accept-current",
    )
    return actor_id, request


async def test_failed_sanity_check_commits_loss_before_resuming_parent(
    db_session,
    engine_store_factory,
):
    actor_id, request = await start_sanity_check(db_session, engine_store_factory)
    db_session.expire_all()
    before = await _committed_state(db_session, request.room_id)
    assert before.actors[actor_id].resources.san == 60
    assert before.entities["cemetery_figure"]["willing_to_talk"] is False
    result = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([4]))
    ).decide_post_roll(request)
    db_session.expire_all()
    after = await _committed_state(db_session, request.room_id)
    assert after.actors[actor_id].resources.san == 56
    assert result.status == "resolved"
    assert after.entities["cemetery_figure"]["willing_to_talk"] is True
    assert after.rule_agendas == {}


async def test_failure_before_commit_recovers_the_prepared_loss(
    db_session,
    engine_store_factory,
):
    import pytest
    from sqlalchemy import select

    from app.models.engine import EngineRandomness, GameEvent

    actor_id, request = await start_sanity_check(db_session, engine_store_factory)

    def crash(_room_id):
        raise RuntimeError("injected-before-commit")

    with pytest.raises(RuntimeError, match="injected-before-commit"):
        await AdjudicationEngineService(
            engine_store_factory(before_commit=crash), dice=DiceRoller(SequenceDiceSource([4]))
        ).decide_post_roll(request)
    db_session.expire_all()
    state = await _committed_state(db_session, request.room_id)
    assert state.actors[actor_id].resources.san == 60
    assert state.entities["cemetery_figure"]["willing_to_talk"] is False
    events = (
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == request.room_id, GameEvent.type == "actor.sanity_loss"
            )
        )
    ).all()
    assert events == []
    assert (
        await db_session.get(
            EngineRandomness, (request.room_id, f"check:{request.check_id}:{request.check_version}")
        )
        is not None
    )
    # New request and fresh service cannot obtain the new source's 6.
    recovered_request = request.model_copy(update={"request_id": "recover-new-request"})
    result = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([6]))
    ).decide_post_roll(recovered_request)
    assert result.status == "resolved"
    db_session.expire_all()
    assert (await _committed_state(db_session, request.room_id)).actors[
        actor_id
    ].resources.san == 56
    facts = (
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == request.room_id, GameEvent.type == "actor.sanity_loss"
            )
        )
    ).all()
    assert len(facts) == 1
    assert facts[0].payload["rolls"] == [4]
    assert facts[0].payload["outcome_id"] == request.check_id
    replay = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([]))
    ).decide_post_roll(recovered_request)
    assert replay.event_refs == result.event_refs


async def test_concurrent_accepts_only_charge_once(db_session, engine_store_factory):
    import asyncio

    from collaboration_framework.contracts import ContractError
    from sqlalchemy import select

    from app.models.engine import GameEvent

    actor_id, request = await start_sanity_check(db_session, engine_store_factory)
    results = await asyncio.gather(
        *(
            AdjudicationEngineService(
                engine_store_factory(), dice=DiceRoller(SequenceDiceSource([4]))
            ).decide_post_roll(request.model_copy(update={"request_id": f"concurrent-{i}"}))
            for i in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert any(isinstance(r, ContractError) for r in results), results
    db_session.expire_all()
    assert (await _committed_state(db_session, request.room_id)).actors[
        actor_id
    ].resources.san == 56
    facts = (
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == request.room_id, GameEvent.type == "actor.sanity_loss"
            )
        )
    ).all()
    assert len(facts) == 1
