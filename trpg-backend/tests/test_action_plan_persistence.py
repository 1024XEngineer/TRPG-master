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
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PostRollDecisionRequest,
    RequiredAdjudicationCheck,
    SelectCheckChoice,
    SkillCheckCandidate,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    RuleEngineService,
    SequenceDiceSource,
)
from collaboration_framework.host.application import (
    ActionPlanOrchestrator,
    PlayerViewProjector,
)
from collaboration_framework.host.ports import ActionPlanBusyError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyActionPlanRunStore, SqlAlchemyEngineStore
from app.models.engine import (
    ActionPlanRunRecord,
    AdjudicationCommandExecution,
    GameEvent,
    RoomActionReservation,
)
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


class SqlPendingPlanAdjudicator(SqlPlanAdjudicator):
    def __init__(self, world_ref: str, entity_id: str) -> None:
        super().__init__(world_ref)
        self.entity_id = entity_id

    async def adjudicate(self, context):
        self.revisions.append(context.player_view.revision)
        if context.step_index != 1:
            return await super().adjudicate(context)
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="world", id=self.world_ref),
            method=ActionMethod(family="research", description=context.step.semantic_goal),
            check=RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="recoverable-choice",
                        skill_id="spot-hidden",
                        difficulty="regular",
                        method_summary="观察当前可见材料",
                        player_safe_reason="使用当前 Actor 的公开技能",
                    ),
                )
            ),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id=self.entity_id,
                    key="recovery_effect_applied",
                    value=True,
                ),
            ),
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


class SqlFirstStepCheckAdjudicator(SqlPendingPlanAdjudicator):
    """Put the check on step 0 so the plan stops before any step completes."""

    async def adjudicate(self, context):
        shifted = context.model_copy(update={"step_index": 1}, deep=True)
        if context.step_index == 0:
            proposal = await super().adjudicate(shifted)
            return proposal.model_copy(update={"summary": context.step.semantic_goal}, deep=True)
        return await SqlPlanAdjudicator.adjudicate(self, context)


async def test_sql_failed_plan_step_stays_loadable_after_the_run_stops(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
    action_plan_store_factory: Callable[[], SqlAlchemyActionPlanRunStore],
) -> None:
    """A failed plan step must not persist a run the store can no longer read.

    Regression for the TURN_CONTRACT_INVALID a player hit on a compound action:
    the step's check failed, the run went to `stopped` while still holding its
    worker lease, and `ActionPlanRun` rejects that pair. The SQLAlchemy store
    validates on read, so the follow-up lease release could not load the row it
    had just written — leaving it permanently unreadable and every retry of the
    same clientActionId failing.
    """

    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    engine_store = engine_store_factory()
    async with engine_store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    entity_id = runtime.module_content.entities[0].id
    original = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-failed-step-246",
        utterance="我要侦查会客室周围，然后去墓地找守墓人",
    )
    plan = ActionPlan(
        goal=original.utterance,
        steps=(
            ActionPlanStep(kind="action", semantic_goal="侦查会客室周围"),
            ActionPlanStep(kind="travel", semantic_goal="前往公共墓地"),
        ),
    )
    # Step 0 needs a check; a 100 fails it outright.
    adjudicator = SqlFirstStepCheckAdjudicator(runtime.module_content.world_ref, entity_id)
    engine = AdjudicationEngineService(
        engine_store,
        dice=DiceRoller(SequenceDiceSource([100])),
    )
    service = ActionPlanOrchestrator(
        store=action_plan_store_factory(),
        adjudicator=adjudicator,
        executor=engine,
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )

    waiting = await service.start_or_resume(original, plan=plan)
    assert waiting.run.status == "waiting_for_player"
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None

    resolved = await engine.decide(
        CheckDecisionRequest(
            request_id="sql-failed-step-246:select",
            room_id=room.id,
            player_id=players[0].id,
            source_revision=pending.view_revision,
            decision_id=pending.pending_decision.decision_id,
            decision_version=pending.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="recoverable-choice"),
        )
    )
    # A failed roll first offers post-roll options; accepting settles the step
    # as a failure, which is the transition that used to corrupt the run.
    assert resolved.status == "awaiting_post_roll_decision"
    assert resolved.check_run is not None
    accepted = await engine.decide_post_roll(
        PostRollDecisionRequest(
            request_id="sql-failed-step-246:accept",
            room_id=room.id,
            player_id=players[0].id,
            source_revision=resolved.view_revision,
            check_id=resolved.check_run.check_id,
            check_version=resolved.check_run.version,
            option_id="accept-current",
        )
    )
    assert accepted.outcome == "failure"

    stopped = await service.resume_owned(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        parent_action_id=original.client_action_id,
    )
    assert stopped.run.status == "stopped"
    assert stopped.run.steps[0].safe_failure_code == "STEP_FAILED"
    assert stopped.run.lease_owner is None

    # The row must survive a real read, and the room must not stay reserved.
    reloaded = await action_plan_store_factory().load(room.id, original.client_action_id)
    assert reloaded is not None
    assert reloaded.status == "stopped"
    assert reloaded.lease_owner is None
    reservation = await db_session.get(RoomActionReservation, room.id)
    assert reservation is None


async def test_sql_pending_plan_rebuild_replays_decision_without_duplicate_effect(
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
    entity_id = runtime.module_content.entities[0].id
    original = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-pending-rebuild-246",
        utterance="先移动，再调查",
    )
    plan = ActionPlan(
        goal=original.utterance,
        steps=(
            ActionPlanStep(kind="action", semantic_goal="先完成第一步"),
            ActionPlanStep(kind="action", semantic_goal="再完成需要玩家选择的第二步"),
        ),
    )
    first_store = action_plan_store_factory()
    first_service = ActionPlanOrchestrator(
        store=first_store,
        adjudicator=SqlPendingPlanAdjudicator(runtime.module_content.world_ref, entity_id),
        executor=AdjudicationEngineService(
            engine_store,
            dice=DiceRoller(SequenceDiceSource([1])),
        ),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )

    waiting = await first_service.start_or_resume(original, plan=plan)
    assert waiting.run.status == "waiting_for_player"
    assert waiting.run.current_step_index == 1
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None

    decision_request = CheckDecisionRequest(
        request_id="sql-pending-rebuild-246:select",
        room_id=room.id,
        player_id=players[0].id,
        source_revision=pending.view_revision,
        decision_id=pending.pending_decision.decision_id,
        decision_version=pending.pending_decision.decision_version,
        choice=SelectCheckChoice(candidate_id="recoverable-choice"),
    )
    rebuilt_engine = AdjudicationEngineService(
        engine_store_factory(),
        dice=DiceRoller(SequenceDiceSource([1])),
    )
    resolved = await rebuilt_engine.decide(decision_request)
    replay = await rebuilt_engine.decide(decision_request)
    assert resolved.status == "awaiting_post_roll_decision"
    assert replay == resolved
    assert resolved.check_run is not None
    post_roll_request = PostRollDecisionRequest(
        request_id="sql-pending-rebuild-246:accept",
        room_id=room.id,
        player_id=players[0].id,
        source_revision=resolved.view_revision,
        check_id=resolved.check_run.check_id,
        check_version=resolved.check_run.version,
        option_id="accept-current",
    )
    resolved = await rebuilt_engine.decide_post_roll(post_roll_request)
    replay = await rebuilt_engine.decide_post_roll(post_roll_request)
    assert resolved.status == "resolved"
    assert replay == resolved

    rebuilt_plan = ActionPlanOrchestrator(
        store=action_plan_store_factory(),
        adjudicator=SqlPendingPlanAdjudicator(runtime.module_content.world_ref, entity_id),
        executor=AdjudicationEngineService(engine_store_factory()),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store_factory())),
    )
    completed = await rebuilt_plan.start_or_resume(original, plan=plan)
    assert completed.run.status == "awaiting_narration"
    assert completed.run.current_step_index == 2

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
    # Two step submissions + skill selection + explicit result acceptance.
    assert len(commands) == 4
    assert [event.type for event in events].count("entity.state_changed") == 1
    assert [event.type for event in events].count("action.succeeded") == 2

    terminal = await rebuilt_plan.mark_narration_completed(
        room_id=room.id,
        parent_action_id=original.client_action_id,
    )
    assert terminal.status == "completed"


async def test_sql_expired_room_reservation_stops_blocking_the_room(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
    action_plan_store_factory: Callable[[], SqlAlchemyActionPlanRunStore],
) -> None:
    """过期占用不再挡住房间，且接管者会把这一行清掉。

    这里同时守着一个 SQLite 专属的坑：`updated_at` 声明了 `timezone=True`，但
    SQLite 不保存时区，取回来是 naive 的。少了 `reservation_is_expired` 里的
    UTC 兜底，这个用例会以 TypeError 失败而不是断言失败。
    """

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
    store = action_plan_store_factory()
    service = ActionPlanOrchestrator(
        store=store,
        adjudicator=SqlPlanAdjudicator(runtime.module_content.world_ref),
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )
    first = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-stale-first",
        utterance="依次完成四个行动",
    )
    await service.start_or_resume(
        first,
        plan=four_step_plan(),
        worker_id="sql-worker-stale",
        auto_continue=False,
    )
    assert await store.load_active_for_room(room_id) is not None

    # 显式写进 SET 子句的值优先于列上的 onupdate，所以这次回拨不会被改回 now()。
    await db_session.execute(
        update(RoomActionReservation)
        .where(RoomActionReservation.room_id == room_id)
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=6))
    )
    await db_session.commit()

    assert await store.load_active_for_room(room_id) is None

    second = PlayerInput(
        room_id=room.id,
        player_id=players[0].id,
        actor_id=actor_id,
        client_action_id="sql-stale-second",
        utterance="改做另一件事",
    )
    taken_over = await service.start_or_resume(
        second,
        plan=four_step_plan(),
        worker_id="sql-worker-takeover",
        auto_continue=False,
    )
    assert taken_over.run.parent_action_id == "sql-stale-second"

    db_session.expire_all()
    reservation = await db_session.get(RoomActionReservation, room_id)
    assert reservation is not None
    assert reservation.parent_action_id == "sql-stale-second"
