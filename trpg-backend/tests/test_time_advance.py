"""Issue #349 多人共享时间全员确认的服务级回归测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdjudicationExecution,
    AdvanceWorldTimeEffect,
    CreateTimeTaskStep,
    ModuleContentV3,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
    TimeTaskSpec,
    TimeTaskTargetSpec,
)
from collaboration_framework.contracts.validation import AdjudicationValidationError
from collaboration_framework.engine import AdjudicationEngineService, GameState
from collaboration_framework.engine.time_tasks import create_time_task
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.ws import TimeAdvancePendingPayload, TimeAdvanceResolvedPayload
from app.main import app
from app.models.engine import (
    GameEvent,
    GameSession,
    ModuleVersion,
    TimeAdvanceProposalRecord,
)
from app.service import time_advance
from tests.test_engine_runtime import _start_room


def _request(
    *,
    room_id: str,
    player_id: str,
    actor_id: str,
    revision: int,
    action_id: str,
) -> SubmitAdjudicationRequest:
    """构造只推进一个离散时间点的无检定裁决。"""

    return SubmitAdjudicationRequest(
        room_id=room_id,
        player_id=player_id,
        adjudication=ActionAdjudication(
            request_id=action_id,
            source_revision=str(revision),
            actor_id=actor_id,
            summary="等待到下一个时间点",
            target=ActionTarget(kind="world", id="coc-7e"),
            method=ActionMethod(family="wait", description="等待"),
            check=NoAdjudicationCheck(),
            success_effects=(AdvanceWorldTimeEffect(),),
        ),
    )


async def _proposal(
    db: AsyncSession,
    room_id: str,
) -> TimeAdvanceProposalRecord:
    record = await db.scalar(
        select(TimeAdvanceProposalRecord).where(TimeAdvanceProposalRecord.room_id == room_id)
    )
    assert record is not None
    return record


async def _time_event_count(db: AsyncSession, room_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(GameEvent)
            .where(
                GameEvent.room_id == room_id,
                GameEvent.type == "time.point_entered",
            )
        )
        or 0
    )


@pytest.mark.asyncio
async def test_single_player_advances_immediately_without_proposal(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """单人局的同意是隐式的，Engine 应当立即提交。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3491,
        player_count=1,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())

    execution = await engine.submit(
        _request(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
            revision=session.state_version,
            action_id="time-single-349",
        )
    )

    assert execution.status == "resolved"
    assert await _time_event_count(db_session, room.id) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(TimeAdvanceProposalRecord)
            .where(TimeAdvanceProposalRecord.room_id == room.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_proposal_creation_is_idempotent_per_room_revision(
    db_session: AsyncSession,
) -> None:
    """同一动作复用提案，同 revision 的另一动作不得创建第二条提案。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3490,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-create-idempotent-349",
    )

    first = await time_advance.create_from_adjudication(db_session, request)
    replay = await time_advance.create_from_adjudication(db_session, request)

    assert replay == first
    with pytest.raises(time_advance.TimeAdvanceError, match="已有待确认"):
        await time_advance.create_from_adjudication(
            db_session,
            _request(
                room_id=room.id,
                player_id=players[0].id,
                actor_id="actor_1",
                revision=session.state_version,
                action_id="time-create-conflict-349",
            ),
        )


@pytest.mark.asyncio
async def test_broadcast_payloads_carry_only_the_module_wording(
    db_session: AsyncSession,
) -> None:
    """确认弹窗不能是玩家侧收窄的漏洞（#415 §阶段一）。

    只删 PlayerView 字段而让弹窗照旧显示「第 3 天 20:00」等于没收窄，所以
    广播载荷里既不能有精确时刻，也不能有能反推出小时的 point id。精确目标
    仍留在提案记录上——它是提交校验与断线恢复的依据。
    """

    room, players, _ = await _start_room(
        db_session,
        room_number=3494,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    await time_advance.create_from_adjudication(
        db_session,
        _request(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
            revision=session.state_version,
            action_id="time-label-415",
        ),
    )

    record = await time_advance._active_record(db_session, room.id)
    assert record is not None
    # 追书人从 hour_12 起步，下一个点是 hour_18，走 evening 的缺省措辞。
    assert record.target_point_id == "hour_18"
    assert record.target_hour_of_day == 18
    assert record.target_label == "晚上"

    pending = time_advance._pending_payload(record).model_dump(by_alias=True)
    assert pending["targetLabel"] == "晚上"
    record.status = "approved"
    resolved = time_advance._resolved_payload(record).model_dump(by_alias=True)
    assert resolved["targetLabel"] == "晚上"

    assert pending["targetDayIndex"] == 0
    assert resolved["targetDayIndex"] == 0
    # 小时与能反推出小时的 point id 仍然不许过网；天数不在收窄范围内。
    leaked = {"targetPointId", "targetHourOfDay"}
    assert not leaked & pending.keys()
    assert not leaked & resolved.keys()


@pytest.mark.asyncio
async def test_terminal_point_refuses_before_any_vote_is_collected(
    db_session: AsyncSession,
) -> None:
    """多人房间在终点根本不该创建提案（#415 §阶段二）。

    让全员投完票才被拒是最难看的一种拒绝方式，所以应用层在建提案**之前**就要
    执行和 Engine 提交时同一个 `terminal_reached`。
    """

    room, players, _ = await _start_room(
        db_session,
        room_number=3496,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    version = await db_session.get(ModuleVersion, (session.module_id, session.module_version))
    assert version is not None
    # 追书人从 hour_12 开局；把开局那一刻本身声明成终点，房间一上来就在终点上。
    content = dict(version.content_json)
    content["time_policy"] = dict(content["time_policy"]) | {
        "terminal_point": {"point_id": "hour_12", "day_index": 0}
    }
    version.content_json = content
    await db_session.commit()

    with pytest.raises(time_advance.TimeAdvanceError, match="最后一个时间点"):
        await time_advance.create_from_adjudication(
            db_session,
            _request(
                room_id=room.id,
                player_id=players[0].id,
                actor_id="actor_1",
                revision=session.state_version,
                action_id="time-terminal-415",
            ),
        )

    assert await time_advance._active_record(db_session, room.id) is None


@pytest.mark.asyncio
async def test_proposal_targets_the_temporary_point_the_engine_would_enter(
    db_session: AsyncSession,
) -> None:
    """多人提案必须和引擎用同一套推进解析（#415）。

    Engine 校验/应用 advance_world_time 时传了 active_occurrences，应用层冻结
    目标时没传。只要下一跳是定时任务插入的临时点，两边就会算出不同的点：显式
    to_point_id 被误判「不是下一个点」，省略时存下的 label 与最终提交不一致 ——
    临时任务在多人房间永远到不了。
    """

    room, players, _ = await _start_room(
        db_session,
        room_number=3497,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    version = await db_session.get(ModuleVersion, (session.module_id, session.module_version))
    assert version is not None
    module = ModuleContentV3.model_validate(version.content_json)

    # 房间从 hour_12 开局；在 12 与 18 之间排一个 15:00 的任务。
    state = GameState.model_validate(session.state_json)
    step = CreateTimeTaskStep(
        id="schedule",
        task=TimeTaskSpec(
            task_key="afternoon_visitor",
            target=TimeTaskTargetSpec(day_index=0, hour_of_day=15),
            on_due_branch_id="default",
        ),
        next_step_id="finish",
    )
    state, task, _ = create_time_task(module, state, step, rule_id="scheduler")
    session.state_json = state.model_dump(mode="json")
    await db_session.commit()

    await time_advance.create_from_adjudication(
        db_session,
        _request(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
            revision=session.state_version,
            action_id="time-temp-point-415",
        ),
    )

    record = await time_advance._active_record(db_session, room.id)
    assert record is not None
    # 下一跳是 15:00 那个临时点，不是默认的 hour_18。
    assert record.target_point_id == task.occurrence_id
    assert record.target_hour_of_day == 15
    assert record.target_label == "下午"


@pytest.mark.asyncio
async def test_a_proposal_from_before_the_label_column_falls_back_to_the_hour(
    db_session: AsyncSession,
) -> None:
    """迁移前建的提案没有 label，按目标小时回退，不让广播炸掉。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3495,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    await time_advance.create_from_adjudication(
        db_session,
        _request(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
            revision=session.state_version,
            action_id="time-label-fallback-415",
        ),
    )
    record = await time_advance._active_record(db_session, room.id)
    assert record is not None
    record.target_label = None

    assert time_advance._pending_payload(record).target_label == "晚上"


@pytest.mark.asyncio
async def test_three_players_wait_then_commit_exactly_once(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """发起者自动同意，中间票只更新提案，最后一票由 Engine 提交一次。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3492,
        player_count=3,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    initial_state = GameState.model_validate(session.state_json)
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-party-349",
    )

    with pytest.raises(AdjudicationValidationError) as blocked:
        await engine.submit(request)
    assert blocked.value.result.code == "TIME_ADVANCE_BLOCKED"

    waiting = await time_advance.create_from_adjudication(db_session, request)
    assert waiting.status == "awaiting_time_consent"
    record = await _proposal(db_session, room.id)
    assert record.accepted_player_ids == [players[0].id]
    await time_advance.bind_parent_action(
        db_session,
        room_id=room.id,
        proposal_id=record.proposal_id,
        player_id=players[0].id,
        parent_action_id="time-parent-plan-349",
    )

    partial, resume_player, action_id = await time_advance.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[1].id,
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        accept=True,
    )
    assert isinstance(partial, TimeAdvancePendingPayload)
    assert partial.accepted_player_ids == [players[0].id, players[1].id]
    assert resume_player is action_id is None
    assert await _time_event_count(db_session, room.id) == 0

    resolved, resume_player, action_id = await time_advance.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[2].id,
        proposal_id=record.proposal_id,
        proposal_version=partial.proposal_version,
        source_revision=str(record.source_revision),
        accept=True,
    )
    assert isinstance(resolved, TimeAdvanceResolvedPayload)
    assert resolved.status == "approved"
    assert resume_player == players[0].id
    assert action_id == "time-parent-plan-349"
    assert await _time_event_count(db_session, room.id) == 1

    # 响应丢失后用旧版本重发，只返回已批准终态，不再推进。
    duplicate, _, _ = await time_advance.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[2].id,
        proposal_id=record.proposal_id,
        proposal_version=partial.proposal_version,
        source_revision=str(record.source_revision),
        accept=True,
    )
    assert isinstance(duplicate, TimeAdvanceResolvedPayload)
    assert duplicate.status == "approved"
    assert await _time_event_count(db_session, room.id) == 1
    await db_session.refresh(session)
    final_state = GameState.model_validate(session.state_json)
    assert final_state.world_time.current != initial_state.world_time.current

    # 规则提交后、叙事落库前，终态提案仍是单动作断线恢复锚点；叙事确认
    # 持久化后必须立即退出活跃查询，避免每次重连都重复恢复。
    wrapper = time_advance.ConsentAwareAdjudicationEngine(
        engine,
        app.state.test_session_factory,
    )
    assert (
        await wrapper.find_active_action_for_player(
            room_id=room.id,
            player_id=players[0].id,
        )
        == "time-parent-plan-349"
    )
    await time_advance.mark_narration_persisted(
        db_session,
        room_id=room.id,
        parent_action_id="time-parent-plan-349",
    )
    assert (
        await wrapper.find_active_action_for_player(
            room_id=room.id,
            player_id=players[0].id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_concurrent_duplicate_final_vote_resumes_only_once(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """同一名玩家并发重发最后一票时，只允许一个调用取得叙事恢复权。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3493,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-concurrent-349",
    )
    await time_advance.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room.id)

    async def vote() -> tuple[
        TimeAdvancePendingPayload | TimeAdvanceResolvedPayload,
        str | None,
        str | None,
    ]:
        async with app.state.test_session_factory() as isolated_db:
            return await time_advance.respond(
                isolated_db,
                engine=engine,
                room_id=room.id,
                player_id=players[1].id,
                proposal_id=record.proposal_id,
                proposal_version=record.proposal_version,
                source_revision=str(record.source_revision),
                accept=True,
            )

    results = await asyncio.gather(vote(), vote())

    assert isinstance(results[0][0], TimeAdvanceResolvedPayload)
    assert isinstance(results[1][0], TimeAdvanceResolvedPayload)
    assert results[0][0].status == "approved"
    assert results[1][0].status == "approved"
    assert sum(result[1] is not None for result in results) == 1
    assert await _time_event_count(db_session, room.id) == 1


@pytest.mark.asyncio
async def test_concurrent_distinct_votes_merge_from_same_old_version(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """三人局最后两票可基于同一旧快照并发提交，且世界时间只推进一次。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3495,
        player_count=3,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-distinct-concurrent-349",
    )
    await time_advance.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room.id)

    async def vote(player_id: str) -> tuple[object, str | None, str | None]:
        async with app.state.test_session_factory() as isolated_db:
            return await time_advance.respond(
                isolated_db,
                engine=engine,
                room_id=room.id,
                player_id=player_id,
                proposal_id=record.proposal_id,
                proposal_version=record.proposal_version,
                source_revision=str(record.source_revision),
                accept=True,
            )

    results = await asyncio.gather(vote(players[1].id), vote(players[2].id))

    assert isinstance(results[0][0], TimeAdvancePendingPayload)
    assert isinstance(results[1][0], TimeAdvanceResolvedPayload)
    assert results[1][0].status == "approved"
    assert sum(result[1] is not None for result in results) == 1
    assert await _time_event_count(db_session, room.id) == 1


@pytest.mark.asyncio
async def test_accepted_player_cannot_revoke_vote(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """发起者已自动同意，之后拒绝属于冲突，不能修改提案集合。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3496,
        player_count=3,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-no-revoke-349",
    )
    await time_advance.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room.id)

    with pytest.raises(time_advance.TimeAdvanceError, match="不能撤回"):
        await time_advance.respond(
            db_session,
            engine=engine,
            room_id=room.id,
            player_id=players[0].id,
            proposal_id=record.proposal_id,
            proposal_version=record.proposal_version,
            source_revision=str(record.source_revision),
            accept=False,
        )

    await db_session.refresh(record)
    assert record.status == "pending"
    assert record.accepted_player_ids == [players[0].id]


@pytest.mark.asyncio
async def test_engine_commit_before_proposal_commit_is_reconciled_as_approved(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """模拟 Engine 已提交但提案事务中断，重试应收敛为 approved。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3494,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-crash-window-349",
    )
    await time_advance.create_from_adjudication(db_session, request)
    await engine.submit_with_time_consent(
        request,
        consent_player_ids=tuple(sorted(player.id for player in players)),
    )

    resolved = await time_advance.get_pending(
        db_session,
        engine=engine,
        room_id=room.id,
    )

    assert isinstance(resolved, TimeAdvanceResolvedPayload)
    assert resolved.status == "approved"
    assert await _time_event_count(db_session, room.id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolution",
    ["rejected", "expired", "stale_revision", "stale_members", "stale_phase"],
)
async def test_cancel_paths_never_change_world_time(
    db_session: AsyncSession,
    engine_store_factory,
    resolution: str,
) -> None:
    """拒绝、超时、revision、成员或房间阶段变化都只取消原行动。"""

    room_number = 3500 + [
        "rejected",
        "expired",
        "stale_revision",
        "stale_members",
        "stale_phase",
    ].index(resolution)
    room, players, _ = await _start_room(
        db_session,
        room_number=room_number,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    initial_state = GameState.model_validate(session.state_json)
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id=f"time-cancel-{resolution}",
    )
    await time_advance.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room.id)

    if resolution == "expired":
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
    elif resolution == "stale_revision":
        session.state_version += 1
        await db_session.commit()
    elif resolution == "stale_members":
        state = GameState.model_validate(session.state_json)
        session.state_json = state.model_copy(
            update={"actors": {"actor_1": state.actors["actor_1"]}},
            deep=True,
        ).to_json_dict()
        await db_session.commit()
    elif resolution == "stale_phase":
        room.phase = "Suspended"
        await db_session.commit()

    payload, resume_player, action_id = await time_advance.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[1].id,
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        accept=resolution != "rejected",
    )

    assert isinstance(payload, TimeAdvanceResolvedPayload)
    expected = "stale" if resolution.startswith("stale") else resolution
    assert payload.status == expected
    assert resume_player == players[0].id
    assert action_id == request.adjudication.request_id
    assert await _time_event_count(db_session, room.id) == 0
    await db_session.refresh(session)
    final_state = GameState.model_validate(session.state_json)
    assert final_state.world_time == initial_state.world_time


@pytest.mark.asyncio
async def test_wrapper_recovers_pending_and_cancelled_status(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """装饰器让 ActionPlan 在重启后仍能查到待确认或已取消的原裁决。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3510,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    raw_engine = AdjudicationEngineService(engine_store_factory())
    wrapper = time_advance.ConsentAwareAdjudicationEngine(
        raw_engine,
        app.state.test_session_factory,
    )
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-recover-349",
    )

    waiting = await wrapper.submit(request)
    assert waiting.status == "awaiting_time_consent"
    pending = await wrapper.get_status(
        time_advance.GetAdjudicationStatusRequest(
            room_id=room.id,
            player_id=players[0].id,
            action_request_id=request.adjudication.request_id,
        )
    )
    assert pending.status == "awaiting_time_consent"

    record = await _proposal(db_session, room.id)
    await time_advance.respond(
        db_session,
        engine=raw_engine,
        room_id=room.id,
        player_id=players[1].id,
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        accept=False,
    )
    cancelled = await wrapper.get_status(
        time_advance.GetAdjudicationStatusRequest(
            room_id=room.id,
            player_id=players[0].id,
            action_request_id=request.adjudication.request_id,
        )
    )
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_initiator_abort_rejects_pending_time_and_blocks_later_accept(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=4121,
        player_count=3,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-abort-412",
    )
    await time_advance.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room.id)
    await time_advance.bind_parent_action(
        db_session,
        room_id=room.id,
        proposal_id=record.proposal_id,
        player_id=players[0].id,
        parent_action_id="time-parent-412",
    )
    initial_time = GameState.model_validate(session.state_json).world_time.current

    aborted = await time_advance.abort_pending(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[0].id,
        parent_action_id="time-parent-412",
    )
    replay = await time_advance.abort_pending(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[0].id,
        parent_action_id="time-parent-412",
    )

    assert isinstance(aborted, TimeAdvanceResolvedPayload)
    assert aborted.status == "rejected"
    assert replay is None
    assert await _time_event_count(db_session, room.id) == 0

    later, resume_player, action_id = await time_advance.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[2].id,
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        accept=True,
    )
    assert isinstance(later, TimeAdvanceResolvedPayload)
    assert later.status == "rejected"
    assert resume_player is action_id is None
    await db_session.refresh(session)
    assert GameState.model_validate(session.state_json).world_time.current == initial_time
    assert await _time_event_count(db_session, room.id) == 0


@pytest.mark.asyncio
async def test_cancelling_a_rule_failed_execution_clears_its_failure_code(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """取消一个带 `rule_failure_code` 的 execution 不能写出读不回来的记录。

    `AdjudicationExecution` 有一条跨字段不变量：只有 `rule_failed` 能带
    `rule_failure_code`（#398 §阶段一）。但取消路径用的是 `model_copy`，而
    `model_copy` 不跑 `model_validator(mode="after")`——`ContractModel` 也没开
    `revalidate_instances`。所以「改 status 但留着旧的 failure_code」当场没人
    拦，等到 `model_validate(record.execution_json)` 把它读回来才炸，而那时已经
    是另一个请求了。

    今天存进 `execution_json` 的永远是 `awaiting_time_consent`，所以这条是潜在的；
    这里把存量记录直接改成 `rule_failed` 来把它逼出来。`scene_transition.py` 的
    两处是同一份代码、同一个修法。
    """

    room, players, _ = await _start_room(
        db_session,
        room_number=3512,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    raw_engine = AdjudicationEngineService(engine_store_factory())
    wrapper = time_advance.ConsentAwareAdjudicationEngine(
        raw_engine,
        app.state.test_session_factory,
    )
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor_1",
        revision=session.state_version,
        action_id="time-rule-failed-398",
    )
    assert (await wrapper.submit(request)).status == "awaiting_time_consent"

    record = await time_advance._record_for_action(
        db_session,
        room_id=room.id,
        action_request_id=request.adjudication.request_id,
    )
    assert record is not None
    stored = AdjudicationExecution.model_validate(record.execution_json)
    record.execution_json = stored.model_copy(
        update={
            "status": "rule_failed",
            "outcome": "success",
            "rule_failure_code": "step_kind_has_no_executor",
            "time_advance_proposal_id": None,
        }
    ).to_json_dict()
    record.status = "rejected"
    await db_session.commit()

    cancelled = await wrapper.get_status(
        time_advance.GetAdjudicationStatusRequest(
            room_id=room.id,
            player_id=players[0].id,
            action_request_id=request.adjudication.request_id,
        )
    )

    assert cancelled.status == "cancelled"
    assert cancelled.execution is not None
    assert cancelled.execution.rule_failure_code is None
    # 真正的验收：这份 execution 能被重新读回来，而不是下一次读取才抛。
    AdjudicationExecution.model_validate(cancelled.execution.to_json_dict())
