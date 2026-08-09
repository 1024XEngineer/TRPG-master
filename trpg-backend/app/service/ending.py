"""Grounded EndingDraft generation and irreversible confirmation (#212 §10)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from collaboration_framework.contracts import (
    ConfirmEndingDraftRequest,
    ConfirmEndingDraftResult,
    CreateEndingDraftRequest,
    EndingDraft,
    EndingResolution,
    ModuleContentV3,
)
from collaboration_framework.engine import GameState
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engine import (
    CheckRunRecord,
    EndingCommandExecution,
    EndingDraftRecord,
    GameEvent,
    GameSession,
    ModuleVersion,
    PendingCheckDecisionRecord,
    RoomActionReservation,
)
from app.models.room import Player, Room
from app.service import chat as chat_service


class EndingError(RuntimeError):
    pass


class EndingNotFoundError(EndingError):
    pass


class EndingUnavailableError(EndingError):
    pass


class EndingConflictError(EndingError):
    pass


class EndingDraftStaleError(EndingConflictError):
    pass


async def _runtime(
    db: AsyncSession, room_id: str
) -> tuple[GameSession, GameState, ModuleContentV3]:
    session = await db.get(GameSession, room_id)
    if session is None:
        raise EndingNotFoundError("房间运行时不存在")
    await db.refresh(session)
    version = await db.get(ModuleVersion, (session.module_id, session.module_version))
    if version is None or version.content_schema_version != 3:
        raise EndingUnavailableError("结局草稿只支持 ModuleContent v3 房间")
    return (
        session,
        GameState.model_validate(deepcopy(session.state_json)),
        ModuleContentV3.model_validate(deepcopy(version.content_json)),
    )


def _actor_for_player(state: GameState, player: Player) -> str:
    actor_id = next(
        (actor_id for actor_id, actor in state.actors.items() if actor.player_id == player.id),
        None,
    )
    if actor_id is None:
        raise EndingUnavailableError("当前玩家没有局内角色")
    return actor_id


async def _has_pending_work(db: AsyncSession, room_id: str) -> bool:
    reservation = await db.get(RoomActionReservation, room_id)
    if reservation is not None:
        return True
    decision = await db.scalar(
        select(PendingCheckDecisionRecord.decision_id).where(
            PendingCheckDecisionRecord.room_id == room_id,
            PendingCheckDecisionRecord.status.in_(("awaiting_skill_choice", "rolled")),
        )
    )
    if decision is not None:
        return True
    check = await db.scalar(
        select(CheckRunRecord.check_id).where(
            CheckRunRecord.room_id == room_id,
            CheckRunRecord.status == "awaiting_post_roll_decision",
        )
    )
    return check is not None


async def _evidence_refs(
    db: AsyncSession,
    *,
    room_id: str,
    actor_id: str,
    state: GameState,
) -> tuple[str, ...]:
    information_refs = set(state.discovered_facts)
    information_refs.update(state.actor_discovered_facts.get(actor_id, ()))
    event_ids = tuple(
        await db.scalars(
            select(GameEvent.event_id)
            .where(
                GameEvent.room_id == room_id,
                or_(
                    GameEvent.visibility == "public",
                    (GameEvent.visibility == "private") & (GameEvent.actor_id == actor_id),
                ),
            )
            .order_by(GameEvent.sequence)
        )
    )
    refs = sorted(information_refs)
    seen = set(refs)
    refs.extend(event_id for event_id in event_ids if event_id not in seen)
    return tuple(refs)


def _select_anchor(module: ModuleContentV3, evidence: set[str]):
    return next(
        (
            anchor
            for anchor in module.ending_anchors
            if set(anchor.required_fact_refs).issubset(evidence)
        ),
        None,
    )


def _grounded_text(module: ModuleContentV3, required_refs: tuple[str, ...]) -> tuple[str, str, str]:
    information = {item.id: item for item in module.information}
    confirmed = [information[ref].player_content for ref in required_refs if ref in information]
    title = f"{module.presentation.title}之后"
    summary = (
        "已确认的事实：" + "；".join(confirmed)
        if confirmed
        else "本次调查以已提交的行动结果为基础告一段落。"
    )
    epilogue = (
        "在这些已提交的证据基础上，调查者选择为此次经历收束。没有被事件确认的命运仍保持未知。"
    )
    return title, summary, epilogue


async def create_draft(
    db: AsyncSession,
    *,
    room_id: str,
    player: Player,
    request: CreateEndingDraftRequest,
) -> EndingDraft:
    existing = await db.scalar(
        select(EndingDraftRecord).where(
            EndingDraftRecord.room_id == room_id,
            EndingDraftRecord.request_id == request.request_id,
        )
    )
    if existing is not None:
        if existing.player_id != player.id or existing.request_json != request.to_json_dict():
            raise EndingConflictError("request_id 已被不同的结局草稿请求使用")
        return EndingDraft.model_validate(deepcopy(existing.draft_json))

    session, state, module = await _runtime(db, room_id)
    actor_id = _actor_for_player(state, player)
    if request.source_revision != str(session.state_version):
        raise EndingDraftStaleError("结局草稿基于过期的房间 revision")
    if state.phase != "playing" or not state.core_resolved or not state.ending_available:
        raise EndingUnavailableError("主线尚未开放结局与后日谈")
    if module.ending_policy.require_no_pending_action and await _has_pending_work(db, room_id):
        raise EndingUnavailableError("当前仍有未完成的行动或检定")

    evidence_refs = await _evidence_refs(db, room_id=room_id, actor_id=actor_id, state=state)
    anchor = _select_anchor(module, set(evidence_refs))
    if anchor is None:
        raise EndingUnavailableError("没有满足已提交证据的结局锚点")
    title, summary, epilogue = _grounded_text(module, anchor.required_fact_refs)
    draft = EndingDraft(
        draft_id=f"ending_draft_{uuid4().hex}",
        request_id=request.request_id,
        source_revision=request.source_revision,
        mode=request.mode,
        player_intent=request.player_intent,
        title=title,
        summary=summary,
        epilogue=epilogue,
        evidence_refs=evidence_refs,
    )
    db.add(
        EndingDraftRecord(
            room_id=room_id,
            draft_id=draft.draft_id,
            request_id=request.request_id,
            player_id=player.id,
            anchor_id=anchor.id,
            version=draft.version,
            status=draft.status,
            request_json=request.to_json_dict(),
            draft_json=draft.to_json_dict(),
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise EndingConflictError("结局草稿请求发生竞争，请重试") from exc
    return draft


async def confirm_draft(
    db: AsyncSession,
    *,
    room_id: str,
    draft_id: str,
    player: Player,
    request: ConfirmEndingDraftRequest,
) -> ConfirmEndingDraftResult:
    record = await db.get(EndingDraftRecord, (room_id, draft_id))
    if record is None or record.player_id != player.id:
        raise EndingNotFoundError("结局草稿不存在")
    command_json = {
        "draft_id": draft_id,
        "player_id": player.id,
        "command": request.to_json_dict(),
    }
    replay = await db.get(EndingCommandExecution, (room_id, request.request_id))
    if replay is not None:
        if replay.request_json != command_json:
            raise EndingConflictError("request_id 已被不同的结局确认命令使用")
        return ConfirmEndingDraftResult.model_validate(deepcopy(replay.result_json))

    draft = EndingDraft.model_validate(deepcopy(record.draft_json))
    if record.status != "active" or draft.status != "active":
        raise EndingConflictError("结局草稿已不可确认")
    if request.draft_version != record.version:
        raise EndingConflictError("结局草稿 version 已变化")

    session, state, module = await _runtime(db, room_id)
    actor_id = _actor_for_player(state, player)
    if request.source_revision != draft.source_revision or draft.source_revision != str(
        session.state_version
    ):
        expired = draft.model_copy(update={"status": "expired", "version": draft.version + 1})
        record.status = "expired"
        record.version = expired.version
        record.draft_json = expired.to_json_dict()
        await db.commit()
        raise EndingDraftStaleError("房间已继续发展，结局草稿已失效")
    if state.phase != "playing" or not state.core_resolved or not state.ending_available:
        raise EndingUnavailableError("当前不能确认结局")
    if module.ending_policy.require_no_pending_action and await _has_pending_work(db, room_id):
        raise EndingUnavailableError("当前仍有未完成的行动或检定")

    evidence_now = set(await _evidence_refs(db, room_id=room_id, actor_id=actor_id, state=state))
    if not set(draft.evidence_refs).issubset(evidence_now):
        raise EndingConflictError("结局草稿引用了未提交的证据")
    anchor = next((item for item in module.ending_anchors if item.id == record.anchor_id), None)
    if anchor is None or not set(anchor.required_fact_refs).issubset(draft.evidence_refs):
        raise EndingConflictError("结局草稿不满足结局锚点的证据约束")

    new_revision = session.state_version + 1
    event_id = f"ending-confirmed-{uuid4().hex}"
    resolution = EndingResolution(
        draft_id=draft_id,
        source_revision=draft.source_revision,
        anchor_id=anchor.id,
        fact_refs=draft.evidence_refs,
        facets=draft.facets,
        confirmed_by=player.id,
        confirmed_event_id=event_id,
    )
    ended_state = state.model_copy(
        update={
            "phase": "ended",
            "ending_id": anchor.id,
            "ending_available": False,
            "ending_resolution": resolution,
            "event_sequence": new_revision,
        },
        deep=True,
    )
    now = datetime.now(UTC)
    state_update = await db.execute(
        update(GameSession)
        .where(
            GameSession.room_id == room_id,
            GameSession.state_version == session.state_version,
            GameSession.agenda_state_version == session.agenda_state_version,
        )
        .values(
            state_json=ended_state.to_json_dict(),
            state_version=new_revision,
            agenda_state_version=session.agenda_state_version + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(state_update, "rowcount", None) != 1:
        await db.rollback()
        raise EndingDraftStaleError("确认结局时房间发生并发更新")
    room_update = await db.execute(
        update(Room)
        .where(Room.id == room_id, Room.phase.in_(("InGame", "Suspended")))
        .values(phase="Completed", ended_at=now, updated_at=now)
    )
    if getattr(room_update, "rowcount", None) != 1:
        await db.rollback()
        raise EndingConflictError("房间阶段已变化，无法确认结局")

    result = ConfirmEndingDraftResult(
        request_id=request.request_id,
        resolution=resolution,
        revision=str(new_revision),
    )
    db.add(
        GameEvent(
            room_id=room_id,
            sequence=new_revision,
            event_id=event_id,
            client_action_id=request.request_id,
            type="ending.confirmed",
            actor_id=actor_id,
            visibility="public",
            cause="ending_draft_confirmed",
            payload={
                "draft_id": draft_id,
                "anchor_id": anchor.id,
                "fact_refs": list(draft.evidence_refs),
                "facets": draft.facets,
            },
        )
    )
    confirmed = draft.model_copy(update={"status": "confirmed", "version": draft.version + 1})
    record.status = "confirmed"
    record.version = confirmed.version
    record.draft_json = confirmed.to_json_dict()
    db.add(
        EndingCommandExecution(
            room_id=room_id,
            request_id=request.request_id,
            request_json=command_json,
            result_json=result.to_json_dict(),
            committed_state_version=new_revision,
        )
    )
    await chat_service.clear_room_chat(db, room_id)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise EndingConflictError("结局确认发生竞争，请刷新") from exc
    return result
