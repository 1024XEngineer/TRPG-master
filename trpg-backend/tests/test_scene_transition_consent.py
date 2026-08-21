"""多人共享场景切换必须经过 Engine 的全员确认门禁。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    EnterLocationEffect,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.validation import AdjudicationValidationError
from collaboration_framework.engine import AdjudicationEngineService, GameState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.ws import SceneTransitionPendingPayload, SceneTransitionResolvedPayload
from app.main import app
from app.models.engine import GameSession, SceneTransitionProposalRecord
from app.service import scene_transition
from tests.test_engine_runtime import _start_room


def _request(
    *,
    room_id: str,
    player_id: str,
    revision: int,
    action_id: str,
) -> SubmitAdjudicationRequest:
    return SubmitAdjudicationRequest(
        room_id=room_id,
        player_id=player_id,
        adjudication=ActionAdjudication(
            request_id=action_id,
            source_revision=str(revision),
            actor_id="actor_1",
            summary="全队前往公共墓地",
            target=ActionTarget(kind="location", id="cemetery"),
            method=ActionMethod(family="travel", description="前往公共墓地"),
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="cemetery"),),
        ),
    )


@pytest.mark.asyncio
async def test_multiplayer_scene_transition_requires_consent_then_commits_atomically(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3651,
        player_count=2,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id="scene-consent-365",
    )

    with pytest.raises(AdjudicationValidationError) as blocked:
        await engine.submit(request)
    assert blocked.value.result.code == "SCENE_TRANSITION_BLOCKED"

    execution = await engine.submit_with_scene_consent(
        request,
        consent_player_ids=tuple(sorted(player.id for player in players)),
    )
    assert execution.status == "resolved"
    refreshed = await db_session.get(GameSession, room.id)
    assert refreshed is not None
    assert GameState.model_validate(refreshed.state_json).scene_id == "cemetery"


@pytest.mark.asyncio
async def test_three_players_confirm_scene_transition_exactly_once(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3652,
        player_count=3,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id="scene-party-365",
    )

    waiting = await scene_transition.create_from_adjudication(db_session, request)
    assert waiting.status == "awaiting_scene_consent"
    assert waiting.scene_transition_proposal_id is not None
    pending = await scene_transition.get_pending(db_session, room.id)
    assert isinstance(pending, SceneTransitionPendingPayload)
    assert pending.accepted_player_ids == [players[0].id]

    partial, resume_player, action_id = await scene_transition.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[1].id,
        proposal_id=pending.proposal_id,
        proposal_version=pending.proposal_version,
        source_revision=pending.source_revision,
        accept=True,
    )
    assert isinstance(partial, SceneTransitionPendingPayload)
    assert resume_player is action_id is None

    resolved, resume_player, action_id = await scene_transition.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[2].id,
        proposal_id=partial.proposal_id,
        proposal_version=partial.proposal_version,
        source_revision=partial.source_revision,
        accept=True,
    )
    assert isinstance(resolved, SceneTransitionResolvedPayload)
    assert resolved.status == "approved"
    assert resume_player == players[0].id
    assert action_id == request.adjudication.request_id

    duplicate, duplicate_player, duplicate_action = await scene_transition.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[2].id,
        proposal_id=partial.proposal_id,
        proposal_version=partial.proposal_version,
        source_revision=partial.source_revision,
        accept=True,
    )
    assert duplicate == resolved
    assert duplicate_player is duplicate_action is None


async def _synchronize_empty_active_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force both creators past the check-before-insert window."""

    original = scene_transition._active_record
    both_empty = asyncio.Event()
    empty_reads = 0
    counter_lock = asyncio.Lock()

    async def synchronized(db: AsyncSession, room_id: str):  # noqa: ANN202
        nonlocal empty_reads
        record = await original(db, room_id)
        if record is not None:
            return record
        async with counter_lock:
            empty_reads += 1
            if empty_reads == 2:
                both_empty.set()
        await both_empty.wait()
        return None

    monkeypatch.setattr(scene_transition, "_active_record", synchronized)


@pytest.mark.asyncio
async def test_concurrent_duplicate_scene_proposals_reuse_database_winner(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3655,
        player_count=2,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    room_id = room.id
    request = _request(
        room_id=room_id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id="scene-concurrent-duplicate-389",
    )
    await _synchronize_empty_active_reads(monkeypatch)

    async def create():  # noqa: ANN202
        async with app.state.test_session_factory() as isolated_db:
            return await scene_transition.create_from_adjudication(isolated_db, request)

    first, second = await asyncio.gather(create(), create())

    assert first.scene_transition_proposal_id == second.scene_transition_proposal_id
    records = (
        await db_session.scalars(
            select(SceneTransitionProposalRecord).where(
                SceneTransitionProposalRecord.room_id == room_id
            )
        )
    ).all()
    assert len(records) == 1
    assert records[0].status == "pending"


@pytest.mark.asyncio
async def test_concurrent_distinct_scene_proposals_allow_only_one_pending(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3656,
        player_count=2,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    requests = tuple(
        _request(
            room_id=room.id,
            player_id=players[0].id,
            revision=session.state_version,
            action_id=f"scene-concurrent-distinct-389-{index}",
        )
        for index in range(2)
    )
    await _synchronize_empty_active_reads(monkeypatch)

    async def create(request: SubmitAdjudicationRequest):  # noqa: ANN202
        async with app.state.test_session_factory() as isolated_db:
            return await scene_transition.create_from_adjudication(isolated_db, request)

    results = await asyncio.gather(
        *(create(request) for request in requests),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, scene_transition.SceneTransitionError) for result in results) == 1
    records = (
        await db_session.scalars(
            select(SceneTransitionProposalRecord).where(
                SceneTransitionProposalRecord.room_id == room.id,
                SceneTransitionProposalRecord.status == "pending",
            )
        )
    ).all()
    assert len(records) == 1


@pytest.mark.asyncio
async def test_terminal_scene_proposal_retry_reuses_request_record(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3657,
        player_count=2,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    room_id = room.id
    request = _request(
        room_id=room_id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id="scene-terminal-retry-389",
    )
    first = await scene_transition.create_from_adjudication(db_session, request)
    record = await _proposal(db_session, room_id)
    record.status = "rejected"
    await db_session.commit()

    retried = await scene_transition.create_from_adjudication(db_session, request)

    assert retried.scene_transition_proposal_id == first.scene_transition_proposal_id
    records = (
        await db_session.scalars(
            select(SceneTransitionProposalRecord).where(
                SceneTransitionProposalRecord.room_id == room_id
            )
        )
    ).all()
    assert len(records) == 1
    assert records[0].status == "rejected"


async def _proposal(db: AsyncSession, room_id: str) -> SceneTransitionProposalRecord:
    record = await db.scalar(
        select(SceneTransitionProposalRecord).where(
            SceneTransitionProposalRecord.room_id == room_id
        )
    )
    assert record is not None
    return record


@pytest.mark.asyncio
async def test_engine_commit_before_proposal_commit_is_reconciled_as_approved(
    db_session: AsyncSession,
    engine_store_factory,
) -> None:
    """模拟 Engine 已提交但提案事务中断，重试应收敛为 approved 而不是 stale。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3653,
        player_count=2,
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id="scene-crash-window-365",
    )
    await scene_transition.create_from_adjudication(db_session, request)
    await engine.submit_with_scene_consent(
        request,
        consent_player_ids=tuple(sorted(player.id for player in players)),
    )

    resolved = await scene_transition.get_pending(
        db_session,
        engine=engine,
        room_id=room.id,
    )

    assert isinstance(resolved, SceneTransitionResolvedPayload)
    assert resolved.status == "approved"
    refreshed = await db_session.get(GameSession, room.id)
    assert refreshed is not None
    assert GameState.model_validate(refreshed.state_json).scene_id == "cemetery"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolution",
    ["rejected", "expired", "stale_revision", "stale_members", "stale_phase"],
)
async def test_cancel_paths_never_change_shared_scene(
    db_session: AsyncSession,
    engine_store_factory,
    resolution: str,
) -> None:
    """拒绝、超时、revision、成员或房间阶段变化都只取消原行动。"""

    room_number = 3660 + [
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
        prepare_checkpoint=True,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    initial_scene = GameState.model_validate(session.state_json).scene_id
    engine = AdjudicationEngineService(engine_store_factory())
    request = _request(
        room_id=room.id,
        player_id=players[0].id,
        revision=session.state_version,
        action_id=f"scene-cancel-{resolution}",
    )
    await scene_transition.create_from_adjudication(db_session, request)
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

    payload, resume_player, action_id = await scene_transition.respond(
        db_session,
        engine=engine,
        room_id=room.id,
        player_id=players[1].id,
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        accept=resolution != "rejected",
    )

    assert isinstance(payload, SceneTransitionResolvedPayload)
    expected = "stale" if resolution.startswith("stale") else resolution
    assert payload.status == expected
    assert resume_player == players[0].id
    assert action_id == request.adjudication.request_id
    refreshed = await db_session.get(GameSession, room.id)
    assert refreshed is not None
    assert GameState.model_validate(refreshed.state_json).scene_id == initial_scene
