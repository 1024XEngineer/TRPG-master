"""Repeated checks share a capped source across SQL sessions and reconnects."""

from copy import deepcopy

from collaboration_framework.contracts import (
    CheckDecisionRequest,
    ModuleContentV3,
    PostRollDecisionRequest,
    SelectCheckChoice,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    SequenceDiceSource,
)
from sqlalchemy import select

from app.models.engine import GameEvent, GameSession, ModuleVersion
from tests.test_engine_runtime import _start_room
from tests.test_issue398_passive_check import _arm_first_sight, _committed_state, _see_true_form


async def prepare_chain(db, store_factory, *, losses=("1d6", "1d6", "1d6"), cap=6, configure=None):
    room, players, _ = await _start_room(db, room_number=196)
    actor_id = await _arm_first_sight(db, room.id)
    session = await db.get(GameSession, room.id)
    original = await db.get(ModuleVersion, (session.module_id, session.module_version))
    payload = deepcopy(original.content_json)
    payload["version"] = "test-sanity-chain"
    rule = next(r for r in payload["rules"] if r["id"] == "first_sight_of_douglas")
    check = next(s for s in rule["execution"]["steps"] if s["kind"] == "check")
    steps = []
    for i, loss in enumerate(losses):
        step = deepcopy(check)
        step["id"] = f"san-{i}"
        step["check"]["parameters"] = {
            "success_loss": "0",
            "failure_loss": loss,
            "sanity_source": "test.creature",
        }
        step["result_routes"] = {
            key: f"san-{i + 1}" if i + 1 < len(losses) else "finish"
            for key in check["result_routes"]
        }
        steps.append(step)
    mark = rule["execution"]["steps"][0]
    mark["next_step_id"] = "san-0"
    rule["execution"]["steps"] = [mark, *steps, {"id": "finish", "kind": "finish"}]
    rule["execution"]["branches"][0]["entry_step_id"] = mark["id"]
    payload["rules"] = [rule]
    payload["sanity_sources"] = [{"id": "test.creature", "habit_cap": cap}]
    if configure is not None:
        configure(payload)
    content = ModuleContentV3.model_validate(payload)
    db.add(
        ModuleVersion(
            module_id=content.module_id,
            version=content.version,
            world_ref=content.world_ref,
            content_schema_version=3,
            content_json=content.to_json_dict(),
        )
    )
    await db.flush()
    session.module_version = content.version
    state = GameState.model_validate(session.state_json)
    actor = state.actors[actor_id]
    from collaboration_framework.registry.sanity_periods import new_ledger

    state.actors[actor_id] = actor.model_copy(
        update={
            "resources": actor.resources.model_copy(update={"san": 60}),
            "sanity": new_ledger(60, state.world_time.current.absolute_hour),
            "state": {**actor.state, "attributes": {"INT": 70}},
        }
    )
    session.state_json = state.to_json_dict()
    await db.commit()
    async with store_factory().transaction(room.id) as tx:
        runtime = await tx.load_runtime()
    execution = await AdjudicationEngineService(store_factory()).submit(
        _see_true_form(room.id, players[0].id, actor_id, runtime.revision)
    )
    return room.id, players[0].id, actor_id, execution


async def accept_check(
    store_factory, room_id, player_id, execution, *, roll=81, loss=4, tag="next"
):
    pending = execution.pending_decision
    assert pending is not None
    rolled = await AdjudicationEngineService(
        store_factory(), dice=DiceRoller(SequenceDiceSource([roll]))
    ).decide(
        CheckDecisionRequest(
            room_id=room_id,
            player_id=player_id,
            request_id=tag + "-roll",
            source_revision=execution.view_revision,
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
        request_id=tag + "-accept",
        source_revision=rolled.view_revision,
        check_id=check.check_id,
        check_version=check.version,
        option_id="accept-current",
    )
    result = await AdjudicationEngineService(
        store_factory(),
        dice=DiceRoller(SequenceDiceSource(loss if isinstance(loss, tuple) else [loss])),
    ).decide_post_roll(request)
    return result, request


async def test_cap_survives_new_sessions_and_zero_loss_replay(db_session, engine_store_factory):
    room_id, player_id, actor_id, execution = await prepare_chain(db_session, engine_store_factory)
    for i, (loss, expected) in enumerate(((4, 56), (4, 54), (3, 54))):
        execution, request = await accept_check(
            engine_store_factory, room_id, player_id, execution, loss=loss, tag=f"loss-{i}"
        )
        db_session.expire_all()
        state = await _committed_state(db_session, room_id)
        assert state.actors[actor_id].resources.san == expected
        ledger = state.actors[actor_id].sanity
        assert ledger is not None
        assert len(ledger.losses) == i + 1
        replay = await AdjudicationEngineService(
            engine_store_factory(), dice=DiceRoller(SequenceDiceSource([]))
        ).decide_post_roll(request)
        assert replay.event_refs == execution.event_refs
    facts = (
        await db_session.scalars(
            select(GameEvent)
            .where(GameEvent.room_id == room_id, GameEvent.type == "actor.sanity_loss")
            .order_by(GameEvent.sequence)
        )
    ).all()
    assert [e.payload["actual_delta"] for e in facts] == [-4, -2, 0]
    assert [e.payload["rolls"] for e in facts] == [[4], [4], [3]]
    assert ledger.habituation == {"test.creature": 6}
    assert not state.rule_agendas


async def test_legacy_ledger_backfill_and_concurrent_remaining_cap(
    db_session, engine_store_factory
):
    import asyncio

    from collaboration_framework.contracts import ContractError

    room_id, player_id, actor_id, execution = await prepare_chain(db_session, engine_store_factory)
    execution, _ = await accept_check(
        engine_store_factory, room_id, player_id, execution, tag="first"
    )
    db_session.expire_all()
    session = await db_session.get(GameSession, room_id)
    payload = deepcopy(session.state_json)
    payload["actors"][actor_id].pop("sanity")
    session.state_json = payload
    await db_session.commit()
    pending = execution.pending_decision
    rolled = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([81]))
    ).decide(
        CheckDecisionRequest(
            room_id=room_id,
            player_id=player_id,
            request_id="second-roll",
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    check = rolled.check_run
    assert check is not None
    requests = [
        PostRollDecisionRequest(
            room_id=room_id,
            player_id=player_id,
            request_id=f"race-{i}",
            source_revision=rolled.view_revision,
            check_id=check.check_id,
            check_version=check.version,
            option_id="accept-current",
        )
        for i in range(2)
    ]
    results = await asyncio.gather(
        *(
            AdjudicationEngineService(
                engine_store_factory(), dice=DiceRoller(SequenceDiceSource([4]))
            ).decide_post_roll(request)
            for request in requests
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert any(isinstance(result, ContractError) for result in results)
    db_session.expire_all()
    state = await _committed_state(db_session, room_id)
    actor = state.actors[actor_id]
    assert actor.resources.san == 54
    assert actor.sanity is not None
    assert actor.sanity.coverage == "canonical_history"
    assert actor.sanity.habituation == {"test.creature": 6}
    assert len(actor.sanity.losses) == 2
