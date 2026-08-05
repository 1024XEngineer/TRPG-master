from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanStep,
    ActionTarget,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
)
from collaboration_framework.engine import AdjudicationEngineService, RuleEngineService
from collaboration_framework.host.application import (
    ActionPlanOrchestrator,
    PlayerViewProjector,
)
from collaboration_framework.host.ports import ActionPlanBusyError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyActionPlanRunStore, SqlAlchemyEngineStore
from app.models.engine import ActionPlanRunRecord, RoomActionReservation
from tests.test_engine_runtime import _start_room


class SqlPlanAdjudicator:
    def __init__(self, world_ref: str) -> None:
        self.world_ref = world_ref
        self.revisions: list[str] = []

    async def adjudicate(self, context):
        self.revisions.append(context.player_view.revision)
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="world", id=self.world_ref),
            method=ActionMethod(family=context.step.kind, description=context.step.semantic_goal),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


def four_step_plan() -> ActionPlan:
    return ActionPlan(
        goal="完成四步计划",
        steps=tuple(
            ActionPlanStep(kind="action", semantic_goal=f"执行第 {index} 步")
            for index in range(1, 5)
        ),
    )


async def test_sql_plan_resumes_across_store_and_service_rebuild(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
    action_plan_store_factory: Callable[[], SqlAlchemyActionPlanRunStore],
) -> None:
    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    room_id = room.id
    engine_store = engine_store_factory()
    async with engine_store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    original = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-plan-225",
        utterance="依次完成四个行动",
    )
    first_adjudicator = SqlPlanAdjudicator(runtime.module_content.world_ref)
    first_store = action_plan_store_factory()
    first = ActionPlanOrchestrator(
        store=first_store,
        adjudicator=first_adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )

    checkpointed = await first.start_or_resume(
        original,
        plan=four_step_plan(),
        worker_id="sql-worker-1",
        auto_continue=False,
    )
    assert checkpointed.run.status == "checkpointed"
    assert checkpointed.run.current_step_index == 3

    rebuilt_engine_store = engine_store_factory()
    rebuilt_store = action_plan_store_factory()
    rebuilt_adjudicator = SqlPlanAdjudicator(runtime.module_content.world_ref)
    rebuilt = ActionPlanOrchestrator(
        store=rebuilt_store,
        adjudicator=rebuilt_adjudicator,
        executor=AdjudicationEngineService(rebuilt_engine_store),
        player_view_projector=PlayerViewProjector(RuleEngineService(rebuilt_engine_store)),
    )
    resumed = await rebuilt.start_or_resume(
        original,
        plan=four_step_plan(),
        worker_id="sql-worker-2",
    )

    assert resumed.run.status == "awaiting_narration"
    assert resumed.run.current_step_index == 4
    assert first_adjudicator.revisions == ["0", "1", "2"]
    assert rebuilt_adjudicator.revisions == ["3"]
    records = (
        await db_session.scalars(
            select(ActionPlanRunRecord).where(ActionPlanRunRecord.room_id == room.id)
        )
    ).all()
    reservations = (
        await db_session.scalars(
            select(RoomActionReservation).where(RoomActionReservation.room_id == room_id)
        )
    ).all()
    assert len(records) == 1
    assert records[0].status == "awaiting_narration"
    assert len(reservations) == 1

    completed = await rebuilt.mark_narration_completed(
        room_id=room.id,
        parent_action_id=original.client_action_id,
    )
    assert completed.status == "completed"
    db_session.expire_all()
    assert (
        await db_session.scalar(
            select(RoomActionReservation).where(RoomActionReservation.room_id == room_id)
        )
        is None
    )


async def test_sql_plan_worker_lease_blocks_then_allows_recovery(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
    action_plan_store_factory: Callable[[], SqlAlchemyActionPlanRunStore],
) -> None:
    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    engine_store = engine_store_factory()
    async with engine_store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    original = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-plan-lease-225",
        utterance="先保留计划",
    )
    store = action_plan_store_factory()
    service = ActionPlanOrchestrator(
        store=store,
        adjudicator=SqlPlanAdjudicator(runtime.module_content.world_ref),
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )
    checkpointed = await service.start_or_resume(
        original,
        plan=four_step_plan(),
        worker_id="setup-worker",
        auto_continue=False,
    )
    run = checkpointed.run
    now = datetime.now(UTC)
    claimed = await store.claim(
        room_id=room.id,
        parent_action_id=original.client_action_id,
        worker_id="worker-a",
        now=now,
        lease_expires_at=now + timedelta(seconds=30),
    )
    assert claimed.lease_owner == "worker-a"

    with pytest.raises(ActionPlanBusyError):
        await store.claim(
            room_id=room.id,
            parent_action_id=original.client_action_id,
            worker_id="worker-b",
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(seconds=31),
        )

    recovered = await store.claim(
        room_id=room.id,
        parent_action_id=original.client_action_id,
        worker_id="worker-b",
        now=now + timedelta(seconds=31),
        lease_expires_at=now + timedelta(seconds=61),
    )
    assert recovered.lease_owner == "worker-b"
    assert recovered.run_version == run.run_version + 2
