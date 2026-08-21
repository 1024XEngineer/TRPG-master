"""多人共享世界时间的全员确认与裁决恢复服务。

本模块不直接改写 GameState。它冻结 Agent 已经产生的原始裁决，
收齐确认后由 AdjudicationEngineService 在自身事务和 revision CAS 中提交，
从而保留规则触发、事件回放与 ActionPlan 恢复语义。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

from collaboration_framework.contracts import (
    COMMITTED_ADJUDICATION_STATUSES,
    ActionAdjudication,
    AdjudicationExecution,
    AdjudicationRecovery,
    AdjudicationStatusView,
    AdvanceWorldTimeEffect,
    GetAdjudicationStatusRequest,
    ModuleContentV3,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.validation import AdjudicationValidationError
from collaboration_framework.engine import AdjudicationEngineService
from collaboration_framework.engine.models import GameState
from collaboration_framework.engine.timeline import advanced_to_next
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dto.ws import (
    SceneTransitionResolvedPayload,
    TimeAdvancePendingPayload,
    TimeAdvanceResolvedPayload,
)
from app.models.engine import GameSession, ModuleVersion, TimeAdvanceProposalRecord
from app.models.room import Room

PROPOSAL_TTL = timedelta(minutes=5)
_response_locks: dict[str, asyncio.Lock] = {}


class TimeAdvanceError(RuntimeError):
    """时间提案请求无效、已过期或与当前房间 revision 冲突。"""


class _SessionFactory(Protocol):
    def __call__(self) -> AsyncSession: ...


def _aware(value: datetime) -> datetime:
    """SQLite 会丢失时区信息，统一把 naive 时间解释为 UTC。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _pending_payload(record: TimeAdvanceProposalRecord) -> TimeAdvancePendingPayload:
    """将持久化记录投影成可以在断线后整体覆盖 UI 的快照。"""

    return TimeAdvancePendingPayload(
        proposal_id=record.proposal_id,
        proposal_version=record.proposal_version,
        source_revision=str(record.source_revision),
        target_point_id=record.target_point_id,
        target_day_index=record.target_day_index,
        target_hour_of_day=record.target_hour_of_day,
        requester_player_id=record.requester_player_id,
        required_player_ids=list(record.required_player_ids),
        accepted_player_ids=list(record.accepted_player_ids),
        expires_at=_aware(record.expires_at),
    )


def _resolved_payload(record: TimeAdvanceProposalRecord) -> TimeAdvanceResolvedPayload:
    """构造终态事件；状态检查在这一边界集中完成。"""

    statuses: tuple[Literal["approved", "rejected", "expired", "stale"], ...] = (
        "approved",
        "rejected",
        "expired",
        "stale",
    )
    if record.status not in statuses:
        raise TimeAdvanceError("待确认提案不能构造终态载荷")
    status = next(item for item in statuses if item == record.status)
    return TimeAdvanceResolvedPayload(
        proposal_id=record.proposal_id,
        status=status,
        target_day_index=record.target_day_index,
        target_hour_of_day=record.target_hour_of_day,
        committed_revision=(
            str(record.committed_revision) if record.committed_revision is not None else None
        ),
    )


def _execution(record: TimeAdvanceProposalRecord) -> AdjudicationExecution:
    """只从强类型 Contract 恢复应用层等待状态，拒绝损坏的 JSON。"""

    return AdjudicationExecution.model_validate(record.execution_json)


def _adjudication(record: TimeAdvanceProposalRecord) -> ActionAdjudication:
    """恢复冻结裁决，保留 persistence_intent 是否显式声明的内部标记。"""

    return ActionAdjudication.model_validate(
        record.adjudication_json,
        context={"allow_persistence_intent_explicit_marker": True},
    )


async def _active_record(
    db: AsyncSession,
    room_id: str,
) -> TimeAdvanceProposalRecord | None:
    return await db.scalar(
        select(TimeAdvanceProposalRecord)
        .where(
            TimeAdvanceProposalRecord.room_id == room_id,
            TimeAdvanceProposalRecord.status == "pending",
        )
        .order_by(TimeAdvanceProposalRecord.created_at.desc())
        .limit(1)
    )


async def _record_for_action(
    db: AsyncSession,
    *,
    room_id: str,
    action_request_id: str,
) -> TimeAdvanceProposalRecord | None:
    return await db.scalar(
        select(TimeAdvanceProposalRecord)
        .where(
            TimeAdvanceProposalRecord.room_id == room_id,
            TimeAdvanceProposalRecord.action_request_id == action_request_id,
        )
        .order_by(TimeAdvanceProposalRecord.created_at.desc())
        .limit(1)
    )


async def _is_stale(db: AsyncSession, record: TimeAdvanceProposalRecord) -> bool:
    """统一检查会使冻结提案失效的房间阶段、revision 与 Actor 成员集合。"""

    room = await db.get(Room, record.room_id)
    session = await db.get(GameSession, record.room_id)
    if room is None or room.phase != "InGame" or session is None:
        return True
    if session.state_version != record.source_revision:
        return True
    state = GameState.model_validate(session.state_json)
    current_players = sorted({actor.player_id for actor in state.actors.values()})
    return current_players != sorted(record.required_player_ids)


def _response_lock(room_id: str) -> asyncio.Lock:
    """串行化单进程内的最后一票；数据库行锁负责多实例间的同一边界。"""

    return _response_locks.setdefault(room_id, asyncio.Lock())


async def get_pending(
    db: AsyncSession,
    room_id: str,
    *,
    engine: AdjudicationEngineService | None = None,
) -> TimeAdvancePendingPayload | TimeAdvanceResolvedPayload | None:
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
            # Engine 与提案分别提交。重连必须主动修复“世界时间已推进、
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
    """冻结任意已绑定玩家发起的多人时间裁决，不检查房主身份。

    发起者只是自动拥有一票；房主与其他玩家完全等价，最终仍要求冻结的
    全体玩家集合确认后才提交世界时间。
    """

    adjudication = request.adjudication
    if adjudication.check.mode != "none":
        raise TimeAdvanceError("带检定的时间效果必须先完成检定")
    if any(isinstance(effect, AdvanceWorldTimeEffect) for effect in adjudication.failure_effects):
        raise TimeAdvanceError("失败分支的时间效果不能提前确认")
    jumps = tuple(
        effect
        for effect in adjudication.success_effects
        if isinstance(effect, AdvanceWorldTimeEffect)
    )
    if not jumps:
        raise TimeAdvanceError("裁决中没有可确认的时间推进效果")

    session = await db.get(GameSession, request.room_id)
    if session is None:
        raise TimeAdvanceError("游戏尚未开始")
    source_revision = session.state_version
    if adjudication.source_revision != str(source_revision):
        raise TimeAdvanceError("房间状态已变化，请刷新后重试")
    state = GameState.model_validate(session.state_json)
    player_by_actor = {actor_id: actor.player_id for actor_id, actor in state.actors.items()}
    if player_by_actor.get(adjudication.actor_id) != request.player_id:
        raise TimeAdvanceError("当前玩家不能为该调查员发起时间推进")
    required = sorted(set(player_by_actor.values()))
    if len(required) <= 1:
        raise TimeAdvanceError("单人房间不需要全员确认")

    existing = await _active_record(db, request.room_id)
    if existing is not None:
        if existing.action_request_id == adjudication.request_id:
            return _execution(existing)
        raise TimeAdvanceError("房间已有待确认的时间提案")

    version = await db.get(ModuleVersion, (session.module_id, session.module_version))
    if version is None or version.content_schema_version != 3:
        raise TimeAdvanceError("当前模组没有可推进的离散时间线")
    module = ModuleContentV3.model_validate(version.content_json)
    target_time = state.world_time
    for effect in jumps:
        target_time = advanced_to_next(module, target_time)
        if effect.to_point_id is not None and effect.to_point_id != target_time.current_point_id:
            raise TimeAdvanceError("冻结裁决的目标不是时间线上的下一个点")

    now = datetime.now(UTC)
    proposal_id = f"time_{uuid4().hex}"
    execution = AdjudicationExecution(
        request_id=adjudication.request_id,
        action_request_id=adjudication.request_id,
        status="awaiting_time_consent",
        view_revision=adjudication.source_revision,
        outcome="pending",
        time_advance_proposal_id=proposal_id,
    )
    record = TimeAdvanceProposalRecord(
        room_id=request.room_id,
        proposal_id=proposal_id,
        source_revision=source_revision,
        proposal_version=1,
        status="pending",
        player_id=request.player_id,
        action_request_id=adjudication.request_id,
        parent_action_id=adjudication.request_id,
        requester_player_id=request.player_id,
        target_point_id=target_time.current_point_id,
        target_day_index=target_time.current.day_index,
        target_hour_of_day=target_time.current.hour_of_day,
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
        # 同一动作重试复用已有记录；其它数据库完整性错误不伪装成成功。
        await db.rollback()
        winner = await db.scalar(
            select(TimeAdvanceProposalRecord).where(
                TimeAdvanceProposalRecord.room_id == request.room_id,
                TimeAdvanceProposalRecord.action_request_id == adjudication.request_id,
            )
        )
        if winner is not None and winner.action_request_id == adjudication.request_id:
            return _execution(winner)
        raise TimeAdvanceError("房间状态已有另一条时间提案") from exc
    return execution


async def bind_parent_action(
    db: AsyncSession,
    *,
    room_id: str,
    proposal_id: str,
    player_id: str,
    parent_action_id: str,
) -> None:
    """把步骤裁决绑定到父行动，使最后一票能够恢复原 ActionPlan。"""

    record = await db.get(TimeAdvanceProposalRecord, (room_id, proposal_id))
    if record is None or record.player_id != player_id:
        raise TimeAdvanceError("时间提案不属于当前行动")
    if record.status != "pending":
        raise TimeAdvanceError("只能为待确认提案绑定父行动")
    if record.parent_action_id != parent_action_id:
        record.parent_action_id = parent_action_id
        await db.commit()


async def mark_narration_persisted(
    db: AsyncSession,
    *,
    room_id: str,
    parent_action_id: str,
) -> None:
    """在权威叙事落库后关闭终态提案的断线恢复锚点。"""

    record = await db.scalar(
        select(TimeAdvanceProposalRecord)
        .where(
            TimeAdvanceProposalRecord.room_id == room_id,
            TimeAdvanceProposalRecord.parent_action_id == parent_action_id,
            TimeAdvanceProposalRecord.narration_persisted.is_(False),
        )
        .order_by(TimeAdvanceProposalRecord.created_at.desc())
        .limit(1)
    )
    if record is not None:
        record.narration_persisted = True
        await db.commit()


async def abort_pending(
    db: AsyncSession,
    *,
    engine: AdjudicationEngineService,
    room_id: str,
    player_id: str,
    parent_action_id: str,
    action_request_id: str | None = None,
) -> TimeAdvanceResolvedPayload | None:
    """发起者中止剩余计划时作废待确认时间提案。"""

    async with _response_lock(room_id):
        matchers = [
            TimeAdvanceProposalRecord.parent_action_id == parent_action_id,
            TimeAdvanceProposalRecord.action_request_id == parent_action_id,
        ]
        if action_request_id:
            matchers.extend(
                (
                    TimeAdvanceProposalRecord.parent_action_id == action_request_id,
                    TimeAdvanceProposalRecord.action_request_id == action_request_id,
                )
            )
        record = await db.scalar(
            select(TimeAdvanceProposalRecord)
            .where(
                TimeAdvanceProposalRecord.room_id == room_id,
                TimeAdvanceProposalRecord.player_id == player_id,
                TimeAdvanceProposalRecord.status == "pending",
                or_(*matchers),
            )
            .order_by(TimeAdvanceProposalRecord.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if record is None:
            return None
        engine_status = await engine.get_status(
            GetAdjudicationStatusRequest(
                room_id=record.room_id,
                player_id=record.player_id,
                action_request_id=record.action_request_id,
            )
        )
        if engine_status.status == "resolved" and engine_status.execution is not None:
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
        record.status = "rejected"
        record.proposal_version += 1
        record.updated_at = datetime.now(UTC)
        await db.commit()
        return _resolved_payload(record)


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
    TimeAdvancePendingPayload | TimeAdvanceResolvedPayload,
    str | None,
    str | None,
]:
    """在进程锁和数据库行锁内处理一票，避免并发最后一票重复恢复叙事。"""

    async with _response_lock(room_id):
        return await _respond_locked(
            db,
            engine=engine,
            room_id=room_id,
            player_id=player_id,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            source_revision=source_revision,
            accept=accept,
        )


async def _respond_locked(
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
    TimeAdvancePendingPayload | TimeAdvanceResolvedPayload,
    str | None,
    str | None,
]:
    """幂等记录一票；收齐后在行锁释放前重放冻结裁决。"""

    record = await db.get(
        TimeAdvanceProposalRecord,
        (room_id, proposal_id),
        with_for_update=True,
    )
    if record is None:
        raise TimeAdvanceError("时间推进提案不存在")
    if record.status != "pending":
        return _resolved_payload(record), None, None
    if player_id not in record.required_player_ids:
        raise TimeAdvanceError("当前玩家不属于该时间提案")
    already_accepted = player_id in record.accepted_player_ids
    # 多名玩家可能基于同一份快照同时确认。旧版本仍可把各自的一票并入集合，
    # 只有客户端声称看到了服务端尚不存在的未来版本时才拒绝。
    if proposal_version > record.proposal_version:
        raise TimeAdvanceError("时间提案版本超前，请刷新后重试")
    if already_accepted and not accept:
        raise TimeAdvanceError("已确认的时间提案不能撤回")
    if source_revision != str(record.source_revision):
        raise TimeAdvanceError("时间提案 revision 不匹配")

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

    # 提案行仍由当前事务锁定；GameSession 只读，真正的 revision CAS 由
    # Engine 自己的事务完成，避免两个事务交叉持有房间行与提案行。
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

    # PostgreSQL 会持续持有提案行锁，SQLite 则由上层进程锁串行；Engine
    # 使用自己的事务完成房间 revision CAS。崩溃恢复由上面的 get_status 收敛。
    request = SubmitAdjudicationRequest(
        room_id=record.room_id,
        player_id=record.player_id,
        adjudication=_adjudication(record),
    )
    try:
        execution = await engine.submit_with_time_consent(
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


class ConsentAwareAdjudicationEngine:
    """装饰生产裁决服务，只拦截 Engine 明确标记的多人时间门禁。"""

    def __init__(
        self,
        engine: AdjudicationEngineService,
        session_factory: async_sessionmaker[AsyncSession] | _SessionFactory,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory

    async def submit(self, request: SubmitAdjudicationRequest) -> AdjudicationExecution:
        try:
            return await self._engine.submit(request)
        except AdjudicationValidationError as exc:
            if exc.result.code == "SCENE_TRANSITION_BLOCKED":
                from app.service import scene_transition

                async with self._session_factory() as db:
                    return await scene_transition.create_from_adjudication(db, request)
            if exc.result.code != "TIME_ADVANCE_BLOCKED":
                raise
            async with self._session_factory() as db:
                return await create_from_adjudication(db, request)

    async def get_status(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationStatusView:
        async with self._session_factory() as db:
            from app.service import scene_transition

            scene_status = await scene_transition.get_status(
                db,
                room_id=request.room_id,
                player_id=request.player_id,
                action_request_id=request.action_request_id,
            )
            if scene_status is not None:
                return scene_status
            record = await _record_for_action(
                db,
                room_id=request.room_id,
                action_request_id=request.action_request_id,
            )
            if record is not None and record.player_id == request.player_id:
                if record.status == "pending":
                    execution = _execution(record)
                    return AdjudicationStatusView(
                        action_request_id=request.action_request_id,
                        status="awaiting_time_consent",
                        execution=execution,
                    )
                if record.status in {"rejected", "expired", "stale"}:
                    execution = _execution(record).model_copy(
                        update={"status": "cancelled", "outcome": "cancelled"},
                        deep=True,
                    )
                    return AdjudicationStatusView(
                        action_request_id=request.action_request_id,
                        status="cancelled",
                        execution=execution,
                    )
        return await self._engine.get_status(request)

    async def recover_action(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationRecovery | None:
        recovered = await self._engine.recover_action(request)
        if recovered is not None:
            return recovered
        async with self._session_factory() as db:
            from app.service import scene_transition

            scene_recovered = await scene_transition.recover_action(
                db,
                room_id=request.room_id,
                player_id=request.player_id,
                action_request_id=request.action_request_id,
            )
            if scene_recovered is not None:
                return scene_recovered
            record = await _record_for_action(
                db,
                room_id=request.room_id,
                action_request_id=request.action_request_id,
            )
            if record is None or record.player_id != request.player_id:
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
        self,
        *,
        room_id: str,
        player_id: str,
    ) -> str | None:
        async with self._session_factory() as db:
            from app.service import scene_transition

            scene_action = await scene_transition.find_active_action_for_player(
                db,
                room_id=room_id,
                player_id=player_id,
            )
            if scene_action is not None:
                return scene_action
            record = await db.scalar(
                select(TimeAdvanceProposalRecord)
                .where(
                    TimeAdvanceProposalRecord.room_id == room_id,
                    TimeAdvanceProposalRecord.player_id == player_id,
                    TimeAdvanceProposalRecord.narration_persisted.is_(False),
                )
                .order_by(TimeAdvanceProposalRecord.created_at.desc())
                .limit(1)
            )
            if record is not None:
                return record.parent_action_id
        return await self._engine.find_active_action_for_player(
            room_id=room_id,
            player_id=player_id,
        )

    async def submit_with_scene_consent(
        self,
        request: SubmitAdjudicationRequest,
        *,
        consent_player_ids: tuple[str, ...],
    ) -> AdjudicationExecution:
        return await self._engine.submit_with_scene_consent(
            request,
            consent_player_ids=consent_player_ids,
        )

    async def decide(self, request):  # noqa: ANN001, ANN201
        """检定决策不属于时间确认，原样交给 Engine。"""

        return await self._engine.decide(request)

    async def decide_post_roll(self, request):  # noqa: ANN001, ANN201
        """检定后决策不属于时间确认，原样交给 Engine。"""

        return await self._engine.decide_post_roll(request)

    async def abort_consent(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        action_request_id: str | None = None,
    ) -> tuple[SceneTransitionResolvedPayload | TimeAdvanceResolvedPayload, ...]:
        """作废当前计划挂起的场景或时间提案，供取消剩余步骤之前调用。"""

        from app.service import scene_transition

        payloads: list[SceneTransitionResolvedPayload | TimeAdvanceResolvedPayload] = []
        async with self._session_factory() as db:
            scene_payload = await scene_transition.abort_pending(
                db,
                engine=self._engine,
                room_id=room_id,
                player_id=player_id,
                parent_action_id=parent_action_id,
                action_request_id=action_request_id,
            )
            if scene_payload is not None:
                payloads.append(scene_payload)
            time_payload = await abort_pending(
                db,
                engine=self._engine,
                room_id=room_id,
                player_id=player_id,
                parent_action_id=parent_action_id,
                action_request_id=action_request_id,
            )
            if time_payload is not None:
                payloads.append(time_payload)
        return tuple(payloads)


__all__ = [
    "ConsentAwareAdjudicationEngine",
    "TimeAdvanceError",
    "abort_pending",
    "bind_parent_action",
    "create_from_adjudication",
    "get_pending",
    "mark_narration_persisted",
    "respond",
]
