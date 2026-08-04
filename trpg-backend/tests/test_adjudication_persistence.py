from collections.abc import Callable

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    CheckDecisionRequest,
    RequiredAdjudicationCheck,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    SequenceDiceSource,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.models.engine import (
    AdjudicationCommandExecution,
    CheckRunRecord,
    GameEvent,
    PendingCheckDecisionRecord,
)
from tests.test_engine_runtime import _start_room


async def test_pending_check_and_authoritative_roll_survive_service_rebuild(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    store = engine_store_factory()
    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    information_id = runtime.module_content.information_items[0].id
    request = SubmitAdjudicationRequest(
        room_id=room.id,
        player_id=players[0].id,
        adjudication=ActionAdjudication(
            request_id="sql-action-212",
            source_revision=runtime.revision,
            actor_id=actor_id,
            summary="检查已知材料",
            target=ActionTarget(kind="information", id=information_id),
            method=ActionMethod(family="research", description="逐项核对材料"),
            check=RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="spot-candidate",
                        skill_id="spot-hidden",
                        difficulty="regular",
                        method_summary="仔细观察材料",
                        player_safe_reason="侧重发现异常细节",
                    ),
                )
            ),
        ),
    )
    pending = await AdjudicationEngineService(store).submit(request)
    assert pending.pending_decision is not None
    decision_request = CheckDecisionRequest(
        request_id="sql-choice-212",
        room_id=room.id,
        player_id=players[0].id,
        source_revision=pending.view_revision,
        decision_id=pending.pending_decision.decision_id,
        decision_version=pending.pending_decision.decision_version,
        choice=SelectCheckChoice(candidate_id="spot-candidate"),
    )

    rolled = await AdjudicationEngineService(
        engine_store_factory(),
        dice=DiceRoller(SequenceDiceSource([64])),
    ).decide(decision_request)
    replay = await AdjudicationEngineService(engine_store_factory()).decide(
        decision_request
    )

    assert rolled.check_run is not None
    assert rolled.check_run.roll.value == 64
    assert replay.check_run == rolled.check_run
    decisions = (
        await db_session.scalars(
            select(PendingCheckDecisionRecord).where(
                PendingCheckDecisionRecord.room_id == room.id
            )
        )
    ).all()
    runs = (
        await db_session.scalars(
            select(CheckRunRecord).where(CheckRunRecord.room_id == room.id)
        )
    ).all()
    commands = (
        await db_session.scalars(
            select(AdjudicationCommandExecution).where(
                AdjudicationCommandExecution.room_id == room.id
            )
        )
    ).all()
    events = (
        await db_session.scalars(
            select(GameEvent).where(GameEvent.room_id == room.id).order_by(GameEvent.sequence)
        )
    ).all()
    assert [decision.status for decision in decisions] == ["rolled"]
    assert [run.check_json["roll"]["value"] for run in runs] == [64]
    assert len(commands) == 2
    assert [event.type for event in events] == ["check.choice_requested", "check.rolled"]
