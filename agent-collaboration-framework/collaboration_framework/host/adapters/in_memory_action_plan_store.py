"""Transactional in-memory ActionPlan store with CAS and room reservation."""

from __future__ import annotations

import asyncio
from datetime import datetime

from collaboration_framework.host.ports.action_plan import (
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


class InMemoryActionPlanRunStore(ActionPlanRunStore):
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], ActionPlanRun] = {}
        self._reservations: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _persistable(run: ActionPlanRun) -> ActionPlanRun:
        """Re-validate the way a persisting store does on its next read.

        Callers build updates with `model_copy(update=...)`, which skips
        validators — so an `ActionPlanRun` can be assembled in a state its own
        model rejects. A real store serialises to JSON and validates on read, and
        would then be unable to load the row it just wrote. Keeping the fake
        permissive hides exactly that class of bug, so it round-trips too.
        """

        return ActionPlanRun.from_persistence_json_dict(
            run.to_persistence_json_dict()
        )

    def _reservation_expired(self, room_id: str, parent_action_id: str) -> bool:
        """占用是否已过期，判据与持久化 store 完全一致。

        持久化侧存的是 `RoomActionReservation.updated_at`，而 CAS 每次都把它同步
        成 `run.updated_at`——两者恒等，所以这里直接读 run 的时间戳，不必再往
        `_reservations` 里塞一个会和 run 漂移的副本。
        """

        run = self._runs.get((room_id, parent_action_id))
        if run is None:
            return False
        return reservation_is_expired(run.updated_at)

    async def create(self, run: ActionPlanRun) -> ActionPlanRun:
        key = (run.room_id, run.parent_action_id)
        async with self._lock:
            existing = self._runs.get(key)
            if existing is not None:
                self._require_same_parent(existing, run)
                return existing.model_copy(deep=True)
            owner = self._reservations.get(run.room_id)
            if owner is not None and owner != run.parent_action_id:
                if self._reservation_expired(run.room_id, owner):
                    del self._reservations[run.room_id]
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
            self._runs[key] = run.model_copy(deep=True)
            self._reservations[run.room_id] = run.parent_action_id
            return run.model_copy(deep=True)

    async def load(self, room_id: str, parent_action_id: str) -> ActionPlanRun | None:
        async with self._lock:
            run = self._runs.get((room_id, parent_action_id))
            return run.model_copy(deep=True) if run is not None else None

    async def load_active_for_player(
        self,
        room_id: str,
        player_id: str,
    ) -> ActionPlanRun | None:
        async with self._lock:
            parent_action_id = self._reservations.get(room_id)
            if parent_action_id is None or self._reservation_expired(room_id, parent_action_id):
                return None
            run = self._runs[(room_id, parent_action_id)]
            if run.player_id != player_id:
                return None
            return run.model_copy(deep=True)

    async def load_active_for_room(self, room_id: str) -> ActionPlanRun | None:
        async with self._lock:
            parent_action_id = self._reservations.get(room_id)
            # 过期占用不再挡住房间，判断与写入分离：删除留给 `create()` 的抢占方。
            if parent_action_id is None or self._reservation_expired(room_id, parent_action_id):
                return None
            return self._runs[(room_id, parent_action_id)].model_copy(deep=True)

    async def compare_and_swap(
        self,
        *,
        expected_run_version: int,
        updated_run: ActionPlanRun,
    ) -> ActionPlanRun:
        key = (updated_run.room_id, updated_run.parent_action_id)
        async with self._lock:
            current = self._runs.get(key)
            if current is None:
                raise ActionPlanConflictError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
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
            reservation = self._reservations.get(updated_run.room_id)
            if (
                current.status in RESERVING_PLAN_STATUSES
                and reservation != current.parent_action_id
            ):
                raise ActionPlanConflictError(
                    "PLAN_RESERVATION_LOST",
                    "ActionPlanRun 已失去房间行动占用",
                )
            self._runs[key] = self._persistable(updated_run)
            if updated_run.status in RESERVING_PLAN_STATUSES:
                self._reservations[updated_run.room_id] = updated_run.parent_action_id
            elif reservation == updated_run.parent_action_id:
                del self._reservations[updated_run.room_id]
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
        key = (room_id, parent_action_id)
        async with self._lock:
            current = self._runs.get(key)
            if current is None:
                raise ActionPlanConflictError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
            if current.is_terminal:
                return current.model_copy(deep=True)
            if self._reservations.get(room_id) != parent_action_id:
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
            self._runs[key] = claimed.model_copy(deep=True)
            return claimed.model_copy(deep=True)

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
