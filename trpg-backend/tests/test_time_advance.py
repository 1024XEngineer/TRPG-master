"""Issue #349 多人共享时间全员确认的服务级回归测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.validation import AdjudicationValidationError
from collaboration_framework.engine import AdjudicationEngineService, GameState
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.engine import GameEvent, GameSession, TimeAdvanceProposalRecord
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
        select(TimeAdvanceProposalRecord).where(
            TimeAdvanceProposalRecord.room_id == room_id
        )
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
    assert await db_session.scalar(
        select(func.count())
        .select_from(TimeAdvanceProposalRecord)
        .where(TimeAdvanceProposalRecord.room_id == room.id)
    ) == 0


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
    assert await wrapper.find_active_action_for_player(
        room_id=room.id,
        player_id=players[0].id,
    ) == "time-parent-plan-349"
    await time_advance.mark_narration_persisted(
        db_session,
        room_id=room.id,
        parent_action_id="time-parent-plan-349",
    )
    assert await wrapper.find_active_action_for_player(
        room_id=room.id,
        player_id=players[0].id,
    ) is None


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

    async def vote() -> tuple[object, str | None, str | None]:
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

    assert [result[0].status for result in results] == ["approved", "approved"]
    assert sum(result[1] is not None for result in results) == 1
    assert await _time_event_count(db_session, room.id) == 1


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

    assert resolved is not None
    assert resolved.status == "approved"
    assert await _time_event_count(db_session, room.id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["rejected", "expired", "stale_revision", "stale_members"])
async def test_cancel_paths_never_change_world_time(
    db_session: AsyncSession,
    engine_store_factory,
    resolution: str,
) -> None:
    """拒绝、超时、revision 变化和成员变化都只取消原行动。"""

    room_number = 3500 + [
        "rejected",
        "expired",
        "stale_revision",
        "stale_members",
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
