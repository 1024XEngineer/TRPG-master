"""SQLAlchemy ActionPlan store with CAS, worker leases and room reservation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from collaboration_framework.host.ports import (
    ActionPlanBusyError,
    ActionPlanConflictError,
    ActionPlanRunStore,
    ActionPlanVersionConflictError,
)
from collaboration_framework.host.schemas import (
    RESERVING_PLAN_STATUSES,
    ActionPlanRun,
    reservation_is_expired,
)
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.engine import ActionPlanRunRecord, RoomActionReservation


class SqlAlchemyActionPlanRunStore(ActionPlanRunStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, run: ActionPlanRun) -> ActionPlanRun:
        try:
            async with self._session_factory() as session, session.begin():
                existing = await session.get(
                    ActionPlanRunRecord,
                    (run.room_id, run.parent_action_id),
                )
                if existing is not None:
                    current = self._run_from_record(existing)
                    self._require_same_parent(current, run)
                    return current
                reservation = await session.get(RoomActionReservation, run.room_id)
                if reservation is not None:
                    # 过期占用在这里被接管者顺手清掉：读路径只判断、不写库，
                    # 真正的删除留给第一个来抢占的人，省掉一次额外事务。
                    if reservation_is_expired(reservation.updated_at):
                        await session.delete(reservation)
                        await session.flush()
                    else:
                        raise ActionPlanBusyError(
                            "ACTION_IN_PROGRESS",
                            "当前房间已有未完成行动计划",
                        )
                if run.status not in RESERVING_PLAN_STATUSES:
                    raise ActionPlanConflictError(
                        "PLAN_CREATE_TERMINAL",
                        "新建 ActionPlanRun 必须处于可推进状态",
                    )
                session.add(self._record_from_run(run))
                await session.flush()
                session.add(
                    RoomActionReservation(
                        room_id=run.room_id,
                        parent_action_id=run.parent_action_id,
                        plan_id=run.plan_id,
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
                await session.flush()
                return run.model_copy(deep=True)
        except ActionPlanBusyError:
            raise
        except IntegrityError as exc:
            raise ActionPlanBusyError(
                "ACTION_IN_PROGRESS",
                "当前房间已有未完成行动计划",
            ) from exc

    async def load(self, room_id: str, parent_action_id: str) -> ActionPlanRun | None:
        async with self._session_factory() as session:
            record = await session.get(ActionPlanRunRecord, (room_id, parent_action_id))
            return self._run_from_record(record) if record is not None else None

    async def load_active_for_player(
        self,
        room_id: str,
        player_id: str,
    ) -> ActionPlanRun | None:
        run = await self.load_active_for_room(room_id)
        if run is None or run.player_id != player_id:
            return None
        return run

    async def load_active_for_room(self, room_id: str) -> ActionPlanRun | None:
        async with self._session_factory() as session:
            reservation = await session.get(RoomActionReservation, room_id)
            if reservation is None:
                return None
            # 过期的占用不再挡住房间：ws 层据此放行新的提交，`create()` 会在
            # 抢占时把这一行删掉。这里只读不写，保持读路径无副作用。
            if reservation_is_expired(reservation.updated_at):
                return None
            record = await session.get(
                ActionPlanRunRecord,
                (room_id, reservation.parent_action_id),
            )
            if record is None:
                raise ActionPlanConflictError(
                    "PLAN_RESERVATION_ORPHANED",
                    "房间行动占用引用了不存在的 ActionPlanRun",
                )
            return self._run_from_record(record)

    async def compare_and_swap(
        self,
        *,
        expected_run_version: int,
        updated_run: ActionPlanRun,
    ) -> ActionPlanRun:
        async with self._session_factory() as session, session.begin():
            current_record = await session.get(
                ActionPlanRunRecord,
                (updated_run.room_id, updated_run.parent_action_id),
            )
            if current_record is None:
                raise ActionPlanConflictError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
            current = self._run_from_record(current_record)
            self._require_same_parent(current, updated_run)
            if current.run_version != expected_run_version:
                raise ActionPlanVersionConflictError(
                    "PLAN_VERSION_CONFLICT",
                    "ActionPlanRun 已被其他 worker 更新",
                )
            if updated_run.run_version != expected_run_version + 1:
                raise ActionPlanConflictError(
                    "PLAN_VERSION_INVALID",
                    "CAS 更新必须将 run_version 精确增加 1",
                )
            reservation = await session.get(RoomActionReservation, updated_run.room_id)
            if current.status in RESERVING_PLAN_STATUSES and (
                reservation is None
                or reservation.parent_action_id != current.parent_action_id
                or reservation.plan_id != current.plan_id
            ):
                raise ActionPlanConflictError(
                    "PLAN_RESERVATION_LOST",
                    "ActionPlanRun 已失去房间行动占用",
                )
            values = self._record_values(updated_run)
            result = await session.execute(
                update(ActionPlanRunRecord)
                .where(
                    ActionPlanRunRecord.room_id == updated_run.room_id,
                    ActionPlanRunRecord.parent_action_id == updated_run.parent_action_id,
                    ActionPlanRunRecord.run_version == expected_run_version,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if getattr(result, "rowcount", None) != 1:
                raise ActionPlanVersionConflictError(
                    "PLAN_VERSION_CONFLICT",
                    "ActionPlanRun 已被其他 worker 更新",
                )
            if updated_run.status in RESERVING_PLAN_STATUSES:
                if reservation is None:
                    raise ActionPlanConflictError(
                        "PLAN_RESERVATION_LOST",
                        "ActionPlanRun 已失去房间行动占用",
                    )
                reservation.updated_at = updated_run.updated_at
            elif reservation is not None:
                await session.delete(reservation)
            await session.flush()
            return updated_run.model_copy(deep=True)

    async def claim(
        self,
        *,
        room_id: str,
        parent_action_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ActionPlanRun:
        if lease_expires_at <= now:
            raise ActionPlanConflictError(
                "PLAN_LEASE_INVALID",
                "worker lease 必须在未来过期",
            )
        async with self._session_factory() as session, session.begin():
            record = await session.get(ActionPlanRunRecord, (room_id, parent_action_id))
            if record is None:
                raise ActionPlanConflictError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
            current = self._run_from_record(record)
            if current.is_terminal:
                return current
            reservation = await session.get(RoomActionReservation, room_id)
            if reservation is None or reservation.parent_action_id != parent_action_id:
                raise ActionPlanConflictError(
                    "PLAN_RESERVATION_LOST",
                    "ActionPlanRun 已失去房间行动占用",
                )
            if (
                current.lease_owner is not None
                and current.lease_owner != worker_id
                and current.lease_expires_at is not None
                and current.lease_expires_at > now
            ):
                raise ActionPlanBusyError(
                    "PLAN_WORKER_BUSY",
                    "ActionPlanRun 正由其他 worker 推进",
                )
            status = (
                "active"
                if current.status in {"checkpointed", "retryable_failure"}
                else current.status
            )
            claimed = current.model_copy(
                update={
                    "status": status,
                    "run_version": current.run_version + 1,
                    "lease_owner": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "updated_at": now,
                },
                deep=True,
            )
            result = await session.execute(
                update(ActionPlanRunRecord)
                .where(
                    ActionPlanRunRecord.room_id == room_id,
                    ActionPlanRunRecord.parent_action_id == parent_action_id,
                    ActionPlanRunRecord.run_version == current.run_version,
                )
                .values(**self._record_values(claimed))
                .execution_options(synchronize_session=False)
            )
            if getattr(result, "rowcount", None) != 1:
                raise ActionPlanVersionConflictError(
                    "PLAN_VERSION_CONFLICT",
                    "ActionPlanRun 已被其他 worker 更新",
                )
            reservation.updated_at = now
            await session.flush()
            return claimed.model_copy(deep=True)

    @staticmethod
    def _record_from_run(run: ActionPlanRun) -> ActionPlanRunRecord:
        return ActionPlanRunRecord(
            room_id=run.room_id,
            parent_action_id=run.parent_action_id,
            plan_id=run.plan_id,
            parent_input_fingerprint=run.parent_input_fingerprint,
            player_id=run.player_id,
            actor_id=run.actor_id,
            status=run.status,
            current_step_index=run.current_step_index,
            run_version=run.run_version,
            plan_schema_version=run.plan_schema_version,
            run_json=run.to_persistence_json_dict(),
            lease_owner=run.lease_owner,
            lease_expires_at=run.lease_expires_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _record_values(run: ActionPlanRun) -> dict[str, object]:
        return {
            "status": run.status,
            "current_step_index": run.current_step_index,
            "run_version": run.run_version,
            "run_json": run.to_persistence_json_dict(),
            "lease_owner": run.lease_owner,
            "lease_expires_at": run.lease_expires_at,
            "updated_at": run.updated_at,
        }

    @staticmethod
    def _run_from_record(record: ActionPlanRunRecord) -> ActionPlanRun:
        if record.plan_schema_version != 1:
            raise ActionPlanConflictError(
                "PLAN_SCHEMA_UNSUPPORTED",
                "不支持的 ActionPlanRun schema version",
            )
        run = ActionPlanRun.from_persistence_json_dict(deepcopy(record.run_json))
        if (
            run.room_id != record.room_id
            or run.parent_action_id != record.parent_action_id
            or run.plan_id != record.plan_id
            or run.parent_input_fingerprint != record.parent_input_fingerprint
            or run.player_id != record.player_id
            or run.actor_id != record.actor_id
            or run.status != record.status
            or run.current_step_index != record.current_step_index
            or run.run_version != record.run_version
            or run.plan_schema_version != record.plan_schema_version
            or run.lease_owner != record.lease_owner
        ):
            raise ActionPlanConflictError(
                "PLAN_RECORD_CORRUPT",
                "ActionPlanRun 列值与 run_json 不一致",
            )
        return run

    @staticmethod
    def _require_same_parent(current: ActionPlanRun, candidate: ActionPlanRun) -> None:
        immutable = (
            "plan_id",
            "parent_action_id",
            "parent_input_fingerprint",
            "room_id",
            "player_id",
            "actor_id",
            "created_revision",
            "plan_schema_version",
            "policy_snapshot",
            "plan",
            "created_at",
        )
        if any(getattr(current, field) != getattr(candidate, field) for field in immutable):
            raise ActionPlanConflictError(
                "PARENT_ACTION_CONFLICT",
                "同一 parent action id 已绑定到不同输入、所有者或计划",
            )
