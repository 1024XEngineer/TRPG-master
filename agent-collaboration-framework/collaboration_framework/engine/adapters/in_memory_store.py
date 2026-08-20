"""Transactional multi-room in-memory implementation of EngineStore."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime

from collaboration_framework.contracts import (
    ContractError,
    ModuleContentV3,
)

from ..models import (
    CheckRun,
    CompletedAction,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineRuntimeSnapshot,
    GameState,
    PendingCheckDecision,
    RuleAgenda,
    StateModifiedEvent,
)
from ..ports import EngineTransaction, RevisionConflictError
from ..rules_v3 import agenda_claim_key, agenda_is_claimable


@dataclass(frozen=True)
class _RoomData:
    module_content: ModuleContentV3
    game_state: GameState
    revision: str
    events: tuple[StateModifiedEvent, ...]
    completed_actions: dict[str, CompletedAction]
    domain_events: tuple[DomainEvent, ...]
    adjudication_commands: dict[str, CompletedAdjudicationCommand]
    pending_checks: dict[str, PendingCheckDecision]
    check_runs: dict[str, CheckRun]


@dataclass
class _RoomRecord:
    data: _RoomData
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class InMemoryEngineStore:
    """Offline store with the same isolation and commit rules required of SQL."""

    def __init__(
        self,
        *,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        self._rooms: dict[str, _RoomRecord] = {}
        self._before_commit = before_commit

    def register_room(
        self,
        *,
        module_content: ModuleContentV3,
        initial_state: GameState,
    ) -> None:
        room_id = initial_state.room_id
        if room_id in self._rooms:
            raise ContractError(f"房间运行时已经存在: {room_id}")
        self._rooms[room_id] = _RoomRecord(
            data=_RoomData(
                module_content=module_content.model_copy(deep=True),
                game_state=initial_state.model_copy(deep=True),
                revision=str(initial_state.event_sequence),
                events=(),
                completed_actions={},
                domain_events=(),
                adjudication_commands={},
                pending_checks={},
                check_runs={},
            )
        )

    @asynccontextmanager
    async def transaction(self, room_id: str) -> AsyncIterator[EngineTransaction]:
        record = self._record(room_id)
        async with record.lock:
            transaction = _InMemoryEngineTransaction(
                room_id=room_id,
                record=record,
                before_commit=self._before_commit,
            )
            try:
                yield transaction
            finally:
                transaction.close()

    def inspect_state(self, room_id: str) -> GameState:
        """Return an isolated snapshot for B-owned tests and offline tooling."""

        return self._record(room_id).data.game_state.model_copy(deep=True)

    def inspect_events(self, room_id: str) -> tuple[StateModifiedEvent, ...]:
        return tuple(
            event.model_copy(deep=True) for event in self._record(room_id).data.events
        )

    def inspect_completed_action(
        self,
        room_id: str,
        request_id: str,
    ) -> CompletedAction:
        try:
            completed = self._record(room_id).data.completed_actions[request_id]
        except KeyError as error:
            raise ContractError(f"动作尚未执行: {request_id}") from error
        return completed.model_copy(deep=True)

    def inspect_domain_events(self, room_id: str) -> tuple[DomainEvent, ...]:
        return tuple(
            event.model_copy(deep=True)
            for event in self._record(room_id).data.domain_events
        )

    def inspect_pending_check(
        self,
        room_id: str,
        decision_id: str,
    ) -> PendingCheckDecision:
        try:
            decision = self._record(room_id).data.pending_checks[decision_id]
        except KeyError as error:
            raise ContractError(f"待处理检定不存在: {decision_id}") from error
        return decision.model_copy(deep=True)

    def inspect_check_run(self, room_id: str, check_id: str) -> CheckRun:
        try:
            check_run = self._record(room_id).data.check_runs[check_id]
        except KeyError as error:
            raise ContractError(f"检定运行不存在: {check_id}") from error
        return check_run.model_copy(deep=True)

    async def claim_rule_agenda(
        self,
        *,
        room_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RuleAgenda | None:
        """Atomically lease the next runnable persisted Agenda."""

        if not worker_id or lease_expires_at <= now:
            raise ContractError("RuleAgenda lease 的 worker 与截止时间必须有效")
        record = self._record(room_id)
        async with record.lock:
            state = record.data.game_state.model_copy(deep=True)
            candidates = sorted(
                (
                    agenda
                    for agenda in state.rule_agendas.values()
                    if agenda_is_claimable(agenda, now=now)
                ),
                key=agenda_claim_key,
            )
            if not candidates:
                return None
            current = candidates[0]
            claimed = current.model_copy(
                update={
                    "lease_owner": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "lease_version": current.lease_version + 1,
                },
                deep=True,
            )
            agendas = dict(state.rule_agendas)
            agendas[claimed.agenda_id] = claimed
            state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
            record.data = replace(record.data, game_state=state)
            return claimed.model_copy(deep=True)

    async def checkpoint_rule_agenda(
        self,
        *,
        agenda: RuleAgenda,
        worker_id: str,
        expected_lease_version: int,
        now: datetime,
    ) -> RuleAgenda:
        """Persist one leased cursor update without advancing Event revision."""

        record = self._record(agenda.room_id)
        async with record.lock:
            state = record.data.game_state.model_copy(deep=True)
            current = state.rule_agendas.get(agenda.agenda_id)
            _validate_agenda_checkpoint(
                current=current,
                proposed=agenda,
                worker_id=worker_id,
                expected_lease_version=expected_lease_version,
                now=now,
            )
            terminal = agenda.status != "running"
            saved = agenda.model_copy(
                update={
                    "lease_owner": None if terminal else worker_id,
                    "lease_expires_at": None if terminal else agenda.lease_expires_at,
                    "lease_version": expected_lease_version + 1,
                },
                deep=True,
            )
            agendas = dict(state.rule_agendas)
            agendas[saved.agenda_id] = saved
            state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
            record.data = replace(record.data, game_state=state)
            return saved.model_copy(deep=True)

    def _record(self, room_id: str) -> _RoomRecord:
        try:
            return self._rooms[room_id]
        except KeyError as error:
            raise ContractError(f"房间运行时不存在: {room_id}") from error


def _validate_agenda_checkpoint(
    *,
    current: RuleAgenda | None,
    proposed: RuleAgenda,
    worker_id: str,
    expected_lease_version: int,
    now: datetime,
) -> None:
    if current is None:
        raise ContractError(f"RuleAgenda 不存在: {proposed.agenda_id}")
    if (
        current.lease_owner != worker_id
        or current.lease_version != expected_lease_version
        or current.lease_expires_at is None
        or current.lease_expires_at <= now
    ):
        raise RevisionConflictError("RuleAgenda lease 已失效或由其他 worker 持有")
    immutable = (
        "agenda_id",
        "room_id",
        "module_id",
        "module_version",
        "correlation_id",
        "root_source",
    )
    if any(getattr(current, name) != getattr(proposed, name) for name in immutable):
        raise ContractError("RuleAgenda checkpoint 不能改写不可变身份")
    if proposed.lease_owner != worker_id:
        raise ContractError("RuleAgenda checkpoint 的 worker 不匹配")
    if proposed.status == "running" and (
        proposed.lease_expires_at is None or proposed.lease_expires_at <= now
    ):
        raise ContractError("运行中的 RuleAgenda 必须保留有效 lease")


class _InMemoryEngineTransaction(EngineTransaction):
    def __init__(
        self,
        *,
        room_id: str,
        record: _RoomRecord,
        before_commit: Callable[[str], None] | None,
    ) -> None:
        self._room_id = room_id
        self._record = record
        self._before_commit = before_commit
        self._closed = False
        self._committed = False

    async def load_runtime(self) -> EngineRuntimeSnapshot:
        self._ensure_active()
        data = self._record.data
        module = data.module_content
        return EngineRuntimeSnapshot(
            module_id=module.module_id,
            module_version=module.version,
            module_content=module.model_copy(deep=True),
            game_state=data.game_state.model_copy(deep=True),
            revision=data.revision,
        )

    async def find_completed_action(
        self,
        request_id: str,
    ) -> CompletedAction | None:
        self._ensure_active()
        completed = self._record.data.completed_actions.get(request_id)
        return completed.model_copy(deep=True) if completed is not None else None

    async def find_adjudication_command(
        self,
        request_id: str,
    ) -> CompletedAdjudicationCommand | None:
        self._ensure_active()
        command = self._record.data.adjudication_commands.get(request_id)
        return command.model_copy(deep=True) if command is not None else None

    async def find_latest_adjudication_command_by_action(
        self,
        action_request_id: str,
    ) -> CompletedAdjudicationCommand | None:
        self._ensure_active()
        candidates = (
            command
            for command in self._record.data.adjudication_commands.values()
            if command.execution.action_request_id == action_request_id
        )
        command = max(
            candidates,
            key=lambda item: int(item.execution.view_revision),
            default=None,
        )
        return command.model_copy(deep=True) if command is not None else None

    async def find_pending_check_by_action(
        self,
        action_request_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        decision = next(
            (
                item
                for item in self._record.data.pending_checks.values()
                if item.action_request_id == action_request_id
            ),
            None,
        )
        return decision.model_copy(deep=True) if decision is not None else None

    async def load_pending_check(
        self,
        decision_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        decision = self._record.data.pending_checks.get(decision_id)
        return decision.model_copy(deep=True) if decision is not None else None

    async def load_check_run(self, check_id: str) -> CheckRun | None:
        self._ensure_active()
        check_run = self._record.data.check_runs.get(check_id)
        return check_run.model_copy(deep=True) if check_run is not None else None

    async def find_active_action_for_player(
        self,
        player_id: str,
    ) -> str | None:
        self._ensure_active()
        for check_run in self._record.data.check_runs.values():
            if (
                check_run.player_id == player_id
                and check_run.status == "awaiting_post_roll_decision"
            ):
                return check_run.action_request_id
        for decision in self._record.data.pending_checks.values():
            if (
                decision.player_id == player_id
                and decision.status == "awaiting_skill_choice"
            ):
                return decision.action_request_id
        return None

    async def commit(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None:
        self._ensure_active()
        if self._committed:
            raise ContractError("同一引擎事务只能提交一次")

        current = self._record.data
        if current.revision != expected_revision:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 "
                f"{expected_revision} 更新为 {current.revision}"
            )
        if new_state.room_id != self._room_id:
            raise ContractError("提交的 GameState 与事务房间不一致")

        request = completed_action.request
        request_id = request.request_id
        if request.room_id != self._room_id:
            raise ContractError("CompletedAction 与事务房间不一致")
        if request_id in current.completed_actions:
            raise ContractError(f"request_id 已经提交: {request_id}")
        if completed_action.execution.events != events:
            raise ContractError("CompletedAction 的 Event 与提交 Event 不一致")
        if completed_action.execution.state_version != new_state.event_sequence:
            raise ContractError("EngineExecutionResult 与 GameState 版本不一致")
        if completed_action.execution.action_result.request_id != request_id:
            raise ContractError("ActionResult 与 CompletedAction request_id 不一致")
        if completed_action.execution.action_result.event_refs != tuple(
            event.event_id for event in events
        ):
            raise ContractError("ActionResult 的 Event 引用与提交 Event 不一致")

        self._validate_events(
            current_state=current.game_state,
            new_state=new_state,
            events=events,
            request_id=request_id,
            actor_id=request.actor_id,
        )

        staged_completed = {
            key: value.model_copy(deep=True)
            for key, value in current.completed_actions.items()
        }
        staged_completed[request_id] = completed_action.model_copy(deep=True)
        staged = _RoomData(
            module_content=current.module_content.model_copy(deep=True),
            game_state=new_state.model_copy(deep=True),
            revision=str(new_state.event_sequence),
            events=current.events
            + tuple(event.model_copy(deep=True) for event in events),
            completed_actions=staged_completed,
            domain_events=current.domain_events,
            adjudication_commands=current.adjudication_commands,
            pending_checks=current.pending_checks,
            check_runs=current.check_runs,
        )

        if self._before_commit is not None:
            self._before_commit(self._room_id)

        # All validation and potentially failing copies happen before this one
        # assignment, so an exception cannot expose a partial logical commit.
        self._record.data = staged
        self._committed = True

    async def commit_adjudication(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        decision: PendingCheckDecision | None,
        check_run: CheckRun | None,
        completed_command: CompletedAdjudicationCommand,
    ) -> None:
        self._ensure_active()
        if self._committed:
            raise ContractError("同一引擎事务只能提交一次")
        current = self._record.data
        if current.revision != expected_revision:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 {expected_revision} "
                f"更新为 {current.revision}"
            )
        if completed_command.request_id in current.adjudication_commands:
            raise ContractError(
                f"裁决 request_id 已经提交: {completed_command.request_id}"
            )
        self._validate_domain_events(
            current_state=current.game_state,
            new_state=new_state,
            events=events,
            request_id=completed_command.request_id,
        )

        decisions = {
            key: value.model_copy(deep=True)
            for key, value in current.pending_checks.items()
        }
        if decision is not None:
            decisions[decision.decision_id] = decision.model_copy(deep=True)
        runs = {
            key: value.model_copy(deep=True)
            for key, value in current.check_runs.items()
        }
        if check_run is not None:
            runs[check_run.check_id] = check_run.model_copy(deep=True)
        commands = {
            key: value.model_copy(deep=True)
            for key, value in current.adjudication_commands.items()
        }
        commands[completed_command.request_id] = completed_command.model_copy(deep=True)

        staged = _RoomData(
            module_content=current.module_content.model_copy(deep=True),
            game_state=new_state.model_copy(deep=True),
            revision=str(new_state.event_sequence),
            events=current.events,
            completed_actions=current.completed_actions,
            domain_events=current.domain_events
            + tuple(event.model_copy(deep=True) for event in events),
            adjudication_commands=commands,
            pending_checks=decisions,
            check_runs=runs,
        )
        if self._before_commit is not None:
            self._before_commit(self._room_id)
        self._record.data = staged
        self._committed = True

    def close(self) -> None:
        self._closed = True

    def _ensure_active(self) -> None:
        if self._closed:
            raise ContractError("引擎事务已经关闭")

    def _validate_events(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        request_id: str,
        actor_id: str,
    ) -> None:
        first_sequence = current_state.event_sequence + 1
        expected_sequences = tuple(range(first_sequence, first_sequence + len(events)))
        if tuple(event.sequence for event in events) != expected_sequences:
            raise ContractError("提交的 Event sequence 必须在房间内连续递增")
        if new_state.event_sequence != current_state.event_sequence + len(events):
            raise ContractError("GameState event_sequence 与提交 Event 数量不一致")
        if not events and new_state != current_state:
            raise ContractError("无 Event 的提交不得修改 GameState")
        event_ids = tuple(event.event_id for event in events)
        if len(event_ids) != len(set(event_ids)):
            raise ContractError("同一次提交的 Event id 必须唯一")
        existing_event_ids = {event.event_id for event in self._record.data.events}
        if existing_event_ids.intersection(event_ids):
            raise ContractError("Event id 已在房间中存在")
        for event in events:
            if event.room_id != self._room_id:
                raise ContractError("Event 与事务房间不一致")
            if event.client_action_id != request_id:
                raise ContractError("Event 与 CompletedAction request_id 不一致")
            if event.actor_id != actor_id:
                raise ContractError("Event 与 CompletedAction actor_id 不一致")

    def _validate_domain_events(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        request_id: str,
    ) -> None:
        first_sequence = current_state.event_sequence + 1
        expected_sequences = tuple(range(first_sequence, first_sequence + len(events)))
        if tuple(event.sequence for event in events) != expected_sequences:
            raise ContractError("提交的领域 Event sequence 必须连续递增")
        if new_state.event_sequence != current_state.event_sequence + len(events):
            raise ContractError("GameState event_sequence 与领域 Event 数量不一致")
        if not events:
            raise ContractError("裁决提交必须至少产生一个领域 Event")
        if any(event.room_id != self._room_id for event in events):
            raise ContractError("领域 Event 与事务房间不一致")
        if any(event.client_action_id != request_id for event in events):
            raise ContractError("领域 Event 与裁决命令 request_id 不一致")
        existing_ids = {
            *(event.event_id for event in self._record.data.events),
            *(event.event_id for event in self._record.data.domain_events),
        }
        event_ids = [event.event_id for event in events]
        if len(event_ids) != len(set(event_ids)) or existing_ids.intersection(
            event_ids
        ):
            raise ContractError("领域 Event id 必须唯一")
