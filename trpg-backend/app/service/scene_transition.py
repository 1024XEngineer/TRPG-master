"""多人共享场景切换的全员确认与裁决恢复服务。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from collaboration_framework.contracts import (
    COMMITTED_ADJUDICATION_STATUSES,
    ActionAdjudication,
    AdjudicationExecution,
    AdjudicationRecovery,
    AdjudicationStatusView,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.validation import AdjudicationValidationError
from collaboration_framework.engine import AdjudicationEngineService
from collaboration_framework.engine.models import GameState
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.ws import SceneTransitionPendingPayload, SceneTransitionResolvedPayload
from app.models.engine import GameSession, SceneTransitionProposalRecord
from app.models.room import Room

PROPOSAL_TTL = timedelta(minutes=5)
_response_locks: dict[str, asyncio.Lock] = {}


class SceneTransitionError(RuntimeError):
    """场景提案请求无效、已过期或与当前房间 revision 冲突。"""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _pending_payload(record: SceneTransitionProposalRecord) -> SceneTransitionPendingPayload:
    return SceneTransitionPendingPayload(
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        source_scene_id=record.source_scene_id,
        target_scene_id=record.target_scene_id,
        requester_player_id=record.requester_player_id,
        required_player_ids=list(record.required_player_ids),
        accepted_player_ids=list(record.accepted_player_ids),
        expires_at=_aware(record.expires_at),
    )


def _resolved_payload(record: SceneTransitionProposalRecord) -> SceneTransitionResolvedPayload:
    statuses: tuple[Literal["approved", "rejected", "expired", "stale"], ...] = (
        "approved",
        "rejected",
        "expired",
        "stale",
    )
    if record.status not in statuses:
        raise SceneTransitionError("待确认提案不能构造终态载荷")
    status = next(item for item in statuses if item == record.status)
    return SceneTransitionResolvedPayload(
        proposal_id=record.proposal_id,
        status=status,
        source_scene_id=record.source_scene_id,
        target_scene_id=record.target_scene_id,
        committed_revision=(
            str(record.committed_revision) if record.committed_revision is not None else None
        ),
    )


def _execution(record: SceneTransitionProposalRecord) -> AdjudicationExecution:
    return AdjudicationExecution.model_validate(record.execution_json)


def _adjudication(record: SceneTransitionProposalRecord) -> ActionAdjudication:
    return ActionAdjudication.model_validate(
        record.adjudication_json,
        context={"allow_persistence_intent_explicit_marker": True},
    )


async def _active_record(
    db: AsyncSession,
    room_id: str,
) -> SceneTransitionProposalRecord | None:
    return await db.scalar(
        select(SceneTransitionProposalRecord)
        .where(
            SceneTransitionProposalRecord.room_id == room_id,
            SceneTransitionProposalRecord.status == "pending",
        )
        .order_by(SceneTransitionProposalRecord.created_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _record_for_action(
    db: AsyncSession,
    *,
    room_id: str,
    action_request_id: str,
) -> SceneTransitionProposalRecord | None:
    return await db.scalar(
        select(SceneTransitionProposalRecord)
        .where(
            SceneTransitionProposalRecord.room_id == room_id,
            SceneTransitionProposalRecord.action_request_id == action_request_id,
        )
        .order_by(SceneTransitionProposalRecord.created_at.desc())
        .limit(1)
    )


async def _is_stale(db: AsyncSession, record: SceneTransitionProposalRecord) -> bool:
    room = await db.get(Room, record.room_id)
    session = await db.get(GameSession, record.room_id)
    if room is None or room.phase != "InGame" or session is None:
        return True
    if session.state_version != record.source_revision:
        return True
    state = GameState.model_validate(session.state_json)
    current_players = sorted({actor.player_id for actor in state.actors.values()})
    return (
        current_players != sorted(record.required_player_ids)
        or state.scene_id != record.source_scene_id
    )


def _response_lock(room_id: str) -> asyncio.Lock:
    return _response_locks.setdefault(room_id, asyncio.Lock())


async def get_pending(
    db: AsyncSession,
    room_id: str,
    *,
    engine: AdjudicationEngineService | None = None,
) -> SceneTransitionPendingPayload | SceneTransitionResolvedPayload | None:
    """返回可恢复提案，并收敛 Engine 已提交或已经超时的记录。"""

    record = await _active_record(db, room_id)
    if record is None:
        return None
    if engine is not None:
        engine_status = await engine.get_status(
            GetAdjudicationStatusRequest(
                room_id=record.room_id,
                player_id=record.player_id,
                action_request_id=record.action_request_id,
            )
        )
        if (
            engine_status.status in COMMITTED_ADJUDICATION_STATUSES
            and engine_status.execution is not None
        ):
            # Engine 与提案分别提交。重连必须主动修复“共享场景已切换、
            # 提案仍是 pending”的崩溃窗口，随后由 ActionPlan 恢复 worker 续跑。
            record.status = "approved"
            record.accepted_player_ids = sorted(record.required_player_ids)
            record.committed_revision = int(engine_status.execution.view_revision)
            record.proposal_version += 1
            record.updated_at = datetime.now(UTC)
            await db.commit()
            return _resolved_payload(record)
    if _aware(record.expires_at) <= datetime.now(UTC):
        record.status = "expired"
        record.proposal_version += 1
        await db.commit()
        return _resolved_payload(record)
    if await _is_stale(db, record):
        record.status = "stale"
        record.proposal_version += 1
        await db.commit()
        return _resolved_payload(record)
    return _pending_payload(record)


async def create_from_adjudication(
    db: AsyncSession,
    request: SubmitAdjudicationRequest,
) -> AdjudicationExecution:
    adjudication = request.adjudication
    if adjudication.check.mode != "none":
        raise SceneTransitionError("带检定的场景切换必须先完成检定")
    effects = tuple(
        effect for effect in adjudication.success_effects if isinstance(effect, EnterLocationEffect)
    )
    if not effects:
        raise SceneTransitionError("裁决中没有可确认的场景切换效果")
    target_scene_id = effects[-1].location_id
    session = await db.get(GameSession, request.room_id)
    if session is None:
        raise SceneTransitionError("游戏尚未开始")
    source_revision = session.state_version
    if adjudication.source_revision != str(source_revision):
        raise SceneTransitionError("房间状态已变化，请刷新后重试")
    state = GameState.model_validate(session.state_json)
    player_by_actor = {actor_id: actor.player_id for actor_id, actor in state.actors.items()}
    if player_by_actor.get(adjudication.actor_id) != request.player_id:
        raise SceneTransitionError("当前玩家不能为该调查员发起场景切换")
    required = sorted(set(player_by_actor.values()))
    if len(required) <= 1:
        raise SceneTransitionError("单人房间不需要全员确认")
    existing = await _active_record(db, request.room_id)
    if existing is not None:
        if existing.action_request_id == adjudication.request_id:
            return _execution(existing)
        raise SceneTransitionError("房间已有待确认的场景提案")

    now = datetime.now(UTC)
    proposal_id = f"scene_{uuid4().hex}"
    execution = AdjudicationExecution(
        request_id=adjudication.request_id,
        action_request_id=adjudication.request_id,
        status="awaiting_scene_consent",
        view_revision=adjudication.source_revision,
        outcome="pending",
        scene_transition_proposal_id=proposal_id,
    )
    record = SceneTransitionProposalRecord(
        room_id=request.room_id,
        proposal_id=proposal_id,
        source_revision=source_revision,
        proposal_version=1,
        status="pending",
        player_id=request.player_id,
        action_request_id=adjudication.request_id,
        parent_action_id=adjudication.request_id,
        requester_player_id=request.player_id,
        source_scene_id=state.scene_id,
        target_scene_id=target_scene_id,
        required_player_ids=required,
        accepted_player_ids=[request.player_id],
        adjudication_json=adjudication.model_dump(
            mode="json",
            context={"preserve_persistence_intent_explicit": True},
        ),
        execution_json=execution.model_dump(mode="json"),
        expires_at=now + PROPOSAL_TTL,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _record_for_action(
            db,
            room_id=request.room_id,
            action_request_id=adjudication.request_id,
        )
        if winner is not None:
            return _execution(winner)
        raise SceneTransitionError("房间状态已有另一条场景提案") from exc
    return execution


async def bind_parent_action(
    db: AsyncSession,
    *,
    room_id: str,
    proposal_id: str,
    player_id: str,
    parent_action_id: str,
) -> None:
    record = await db.get(SceneTransitionProposalRecord, (room_id, proposal_id))
    if record is None or record.player_id != player_id:
        raise SceneTransitionError("场景提案不属于当前行动")
    if record.status != "pending":
        raise SceneTransitionError("只能为待确认提案绑定父行动")
    if record.parent_action_id != parent_action_id:
        record.parent_action_id = parent_action_id
        await db.commit()


async def mark_narration_persisted(
    db: AsyncSession,
    *,
    room_id: str,
    parent_action_id: str,
) -> None:
    record = await db.scalar(
        select(SceneTransitionProposalRecord)
        .where(
            SceneTransitionProposalRecord.room_id == room_id,
            SceneTransitionProposalRecord.parent_action_id == parent_action_id,
            SceneTransitionProposalRecord.narration_persisted.is_(False),
        )
        .order_by(SceneTransitionProposalRecord.created_at.desc())
        .limit(1)
    )
    if record is not None:
        record.narration_persisted = True
        await db.commit()


async def respond(
    db: AsyncSession,
    *,
    engine: AdjudicationEngineService,
    room_id: str,
    player_id: str,
    proposal_id: str,
    proposal_version: int,
    source_revision: str,
    accept: bool,
) -> tuple[
    SceneTransitionPendingPayload | SceneTransitionResolvedPayload,
    str | None,
    str | None,
]:
    async with _response_lock(room_id):
        record = await db.get(
            SceneTransitionProposalRecord,
            (room_id, proposal_id),
            with_for_update=True,
        )
        if record is None:
            raise SceneTransitionError("场景切换提案不存在")
        if record.status != "pending":
            return _resolved_payload(record), None, None
        if player_id not in record.required_player_ids:
            raise SceneTransitionError("当前玩家不属于该场景提案")
        already_accepted = player_id in record.accepted_player_ids
        if proposal_version > record.proposal_version:
            raise SceneTransitionError("场景提案版本超前，请刷新后重试")
        if already_accepted and not accept:
            raise SceneTransitionError("已确认的场景提案不能撤回")
        if source_revision != str(record.source_revision):
            raise SceneTransitionError("场景提案 revision 不匹配")

        # Engine 提交与提案终态分属两个事务。若进程恰好在前者提交后退出，
        # 重试必须把已有权威结果收敛为 approved，不能误判成 stale 或推进第二次。
        engine_status = await engine.get_status(
            GetAdjudicationStatusRequest(
                room_id=record.room_id,
                player_id=record.player_id,
                action_request_id=record.action_request_id,
            )
        )
        if (
            engine_status.status in COMMITTED_ADJUDICATION_STATUSES
            and engine_status.execution is not None
        ):
            record.status = "approved"
            record.accepted_player_ids = sorted(record.required_player_ids)
            record.committed_revision = int(engine_status.execution.view_revision)
            record.proposal_version += 1
            record.updated_at = datetime.now(UTC)
            await db.commit()
            return _resolved_payload(record), record.player_id, record.parent_action_id
        if _aware(record.expires_at) <= datetime.now(UTC):
            record.status = "expired"
            record.proposal_version += 1
            await db.commit()
            return _resolved_payload(record), record.player_id, record.parent_action_id
        if await _is_stale(db, record):
            record.status = "stale"
            record.proposal_version += 1
            await db.commit()
            return _resolved_payload(record), record.player_id, record.parent_action_id
        if not accept:
            record.status = "rejected"
            record.proposal_version += 1
            await db.commit()
            return _resolved_payload(record), record.player_id, record.parent_action_id
        if not already_accepted:
            record.accepted_player_ids = sorted({*record.accepted_player_ids, player_id})
            record.proposal_version += 1
        if set(record.accepted_player_ids) != set(record.required_player_ids):
            await db.commit()
            return _pending_payload(record), None, None

        request = SubmitAdjudicationRequest(
            room_id=record.room_id,
            player_id=record.player_id,
            adjudication=_adjudication(record),
        )
        try:
            execution = await engine.submit_with_scene_consent(
                request,
                consent_player_ids=tuple(sorted(record.required_player_ids)),
            )
        except AdjudicationValidationError:
            await db.refresh(record)
            record.status = "stale"
            record.proposal_version += 1
            await db.commit()
            return _resolved_payload(record), record.player_id, record.parent_action_id
        await db.refresh(record)
        record.status = "approved"
        record.committed_revision = int(execution.view_revision)
        record.proposal_version += 1
        record.updated_at = datetime.now(UTC)
        await db.commit()
        return _resolved_payload(record), record.player_id, record.parent_action_id


async def get_status(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    action_request_id: str,
) -> AdjudicationStatusView | None:
    record = await _record_for_action(
        db,
        room_id=room_id,
        action_request_id=action_request_id,
    )
    if record is None or record.player_id != player_id:
        return None
    execution = _execution(record)
    if record.status == "pending":
        return AdjudicationStatusView(
            action_request_id=action_request_id,
            status="awaiting_scene_consent",
            execution=execution,
        )
    if record.status in {"rejected", "expired", "stale"}:
        execution = execution.model_copy(
            update={"status": "cancelled", "outcome": "cancelled"},
            deep=True,
        )
        return AdjudicationStatusView(
            action_request_id=action_request_id,
            status="cancelled",
            execution=execution,
        )
    return None


async def recover_action(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    action_request_id: str,
) -> AdjudicationRecovery | None:
    record = await _record_for_action(
        db,
        room_id=room_id,
        action_request_id=action_request_id,
    )
    if record is None or record.player_id != player_id:
        return None
    execution = _execution(record)
    if record.status in {"rejected", "expired", "stale"}:
        execution = execution.model_copy(
            update={"status": "cancelled", "outcome": "cancelled"},
            deep=True,
        )
    adjudication = _adjudication(record)
    return AdjudicationRecovery(
        action_request_id=record.action_request_id,
        actor_id=adjudication.actor_id,
        summary=adjudication.summary,
        created_at=record.created_at,
        execution=execution,
    )


async def find_active_action_for_player(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
) -> str | None:
    record = await db.scalar(
        select(SceneTransitionProposalRecord)
        .where(
            SceneTransitionProposalRecord.room_id == room_id,
            SceneTransitionProposalRecord.player_id == player_id,
            SceneTransitionProposalRecord.narration_persisted.is_(False),
        )
        .order_by(SceneTransitionProposalRecord.created_at.desc())
        .limit(1)
    )
    return record.parent_action_id if record is not None else None


__all__ = [
    "SceneTransitionError",
    "bind_parent_action",
    "create_from_adjudication",
    "find_active_action_for_player",
    "get_pending",
    "get_status",
    "mark_narration_persisted",
    "recover_action",
    "respond",
]
