"""SQLAlchemy implementation of the rule-engine persistence port (issue #121)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime

from collaboration_framework.contracts import ActionRequest, ContractError, ModuleContent
from collaboration_framework.engine import (
    CheckRun,
    CompletedAction,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    EngineStore,
    EngineTransaction,
    GameState,
    PendingCheckDecision,
    RevisionConflictError,
    StateModifiedEvent,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.runtime_state import hydrate_actor_state_from_ruleset
from app.core.turn_observability import log_state_changes
from app.models.content import GameSystem
from app.models.engine import (
    ActionExecution,
    AdjudicationCommandExecution,
    CheckRunRecord,
    GameEvent,
    GameSession,
    ModuleVersion,
    PendingCheckDecisionRecord,
)
from app.models.room import Room


class SqlAlchemyEngineStore(EngineStore):
    """为每个规则引擎事务创建独立数据库 Session 和原子事务。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._before_commit = before_commit

    @asynccontextmanager
    async def transaction(self, room_id: str) -> AsyncIterator[EngineTransaction]:
        async with self._session_factory() as session:
            transaction = _SqlAlchemyEngineTransaction(
                room_id=room_id,
                session=session,
                before_commit=self._before_commit,
            )
            try:
                async with session.begin():
                    yield transaction
            finally:
                transaction.close()
            transaction.log_committed_state_changes()


class _SqlAlchemyEngineTransaction(EngineTransaction):
    def __init__(
        self,
        *,
        room_id: str,
        session: AsyncSession,
        before_commit: Callable[[str], None] | None,
    ) -> None:
        self._room_id = room_id
        self._session = session
        self._before_commit = before_commit
        self._closed = False
        self._committed = False
        self._committed_events: tuple[StateModifiedEvent, ...] = ()
        self._committed_request_id: str | None = None

    async def load_runtime(self) -> EngineRuntimeSnapshot:
        self._ensure_active()
        game_session = await self._session.get(GameSession, self._room_id)
        if game_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        if game_session.state_schema_version != 1:
            raise ContractError(
                f"不支持的 GameState schema version: {game_session.state_schema_version}"
            )

        module_version = await self._session.get(
            ModuleVersion,
            (game_session.module_id, game_session.module_version),
        )
        if module_version is None:
            raise ContractError("GameSession 引用的 ModuleVersion 不存在")
        if module_version.content_schema_version not in {1, 2}:
            raise ContractError(
                f"不支持的 ModuleContent schema version: {module_version.content_schema_version}"
            )

        module_content = ModuleContent.model_validate(deepcopy(module_version.content_json))
        if (
            module_content.module_id != module_version.module_id
            or module_content.version != module_version.version
            or module_content.world_ref != module_version.world_ref
        ):
            raise ContractError("ModuleVersion 列值与 content_json 不一致")

        game_state = GameState.model_validate(deepcopy(game_session.state_json))
        if game_state.room_id != game_session.room_id:
            raise ContractError("GameSession 与 state_json 的 room_id 不一致")
        if game_state.event_sequence != game_session.state_version:
            raise ContractError("GameSession state_version 与 GameState event_sequence 不一致")

        system = await self._session.scalar(
            select(GameSystem).where(GameSystem.world_ref == module_version.world_ref)
        )
        game_state, hydrated = _hydrate_game_state_actor_skills(
            game_state,
            ruleset=system.ruleset if system is not None else None,
        )
        if hydrated:
            state_update = await self._session.execute(
                update(GameSession)
                .where(
                    GameSession.room_id == self._room_id,
                    GameSession.state_version == game_session.state_version,
                )
                .values(
                    state_json=game_state.to_json_dict(),
                    updated_at=datetime.now(UTC),
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(state_update, "rowcount", None) != 1:
                raise RevisionConflictError(
                    f"房间 {self._room_id} 在运行时技能回填期间发生了并发更新"
                )
            await self._session.refresh(game_session)

        return EngineRuntimeSnapshot(
            module_id=module_version.module_id,
            module_version=module_version.version,
            module_content=module_content,
            game_state=game_state,
            revision=str(game_session.state_version),
        )

    async def find_completed_action(
        self,
        request_id: str,
    ) -> CompletedAction | None:
        self._ensure_active()
        execution = await self._session.get(
            ActionExecution,
            (self._room_id, request_id),
        )
        if execution is None:
            return None
        if execution.request_schema_version != 1:
            raise ContractError(
                f"不支持的 ActionRequest schema version: {execution.request_schema_version}"
            )
        if execution.result_schema_version != 1:
            raise ContractError(
                f"不支持的 EngineExecutionResult schema version: {execution.result_schema_version}"
            )

        request = ActionRequest.model_validate(deepcopy(execution.request_json))
        result = EngineExecutionResult.model_validate(deepcopy(execution.result_json))
        if request.room_id != execution.room_id or request.request_id != execution.request_id:
            raise ContractError("ActionExecution 列值与 request_json 不一致")
        if result.action_result.request_id != execution.request_id:
            raise ContractError("ActionExecution request_id 与结果不一致")
        if result.state_version != execution.committed_state_version:
            raise ContractError("ActionExecution committed_state_version 与结果不一致")
        return CompletedAction(request=request, execution=result)

    async def find_adjudication_command(
        self,
        request_id: str,
    ) -> CompletedAdjudicationCommand | None:
        self._ensure_active()
        record = await self._session.get(
            AdjudicationCommandExecution,
            (self._room_id, request_id),
        )
        if record is None:
            return None
        if record.request_schema_version != 1 or record.result_schema_version != 1:
            raise ContractError("不支持的裁决命令 schema version")
        command = CompletedAdjudicationCommand.model_validate(
            {
                "request_id": record.request_id,
                "request": deepcopy(record.request_json),
                "execution": deepcopy(record.result_json),
            }
        )
        if command.execution.view_revision != str(record.committed_state_version):
            raise ContractError("裁决命令 committed_state_version 与结果不一致")
        return command

    async def find_pending_check_by_action(
        self,
        action_request_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        record = await self._session.scalar(
            select(PendingCheckDecisionRecord).where(
                PendingCheckDecisionRecord.room_id == self._room_id,
                PendingCheckDecisionRecord.action_request_id == action_request_id,
            )
        )
        return self._decision_from_record(record)

    async def load_pending_check(
        self,
        decision_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        record = await self._session.get(
            PendingCheckDecisionRecord,
            (self._room_id, decision_id),
        )
        return self._decision_from_record(record)

    async def load_check_run(self, check_id: str) -> CheckRun | None:
        self._ensure_active()
        record = await self._session.get(CheckRunRecord, (self._room_id, check_id))
        if record is None:
            return None
        if record.check_schema_version != 1:
            raise ContractError("不支持的 CheckRun schema version")
        check_run = CheckRun.model_validate(deepcopy(record.check_json))
        if (
            check_run.room_id != record.room_id
            or check_run.check_id != record.check_id
            or check_run.status != record.status
            or check_run.version != record.version
            or check_run.roll_count != record.roll_count
        ):
            raise ContractError("CheckRun 列值与 check_json 不一致")
        return check_run

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

        expected_version = self._parse_revision(expected_revision)
        current_session = await self._session.get(GameSession, self._room_id)
        if current_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        current_state = GameState.model_validate(deepcopy(current_session.state_json))
        if current_session.state_version != expected_version:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 "
                f"{expected_revision} 更新为 {current_session.state_version}"
            )

        self._validate_commit(
            current_state=current_state,
            new_state=new_state,
            events=events,
            completed_action=completed_action,
        )

        request = completed_action.request
        existing_action = await self._session.get(
            ActionExecution,
            (self._room_id, request.request_id),
        )
        if existing_action is not None:
            raise ContractError(f"request_id 已经提交: {request.request_id}")

        event_ids = tuple(event.event_id for event in events)
        if event_ids:
            existing_event_id = await self._session.scalar(
                select(GameEvent.event_id).where(
                    GameEvent.room_id == self._room_id,
                    GameEvent.event_id.in_(event_ids),
                )
            )
            if existing_event_id is not None:
                raise ContractError(f"Event id 已在房间中存在: {existing_event_id}")

        now = datetime.now(UTC)
        room_values: dict[str, object]
        if new_state.phase == "ended":
            room_values = {
                "phase": "Completed",
                "ended_at": now,
                "updated_at": now,
            }
        else:
            room_values = {
                "phase": "InGame",
                "updated_at": now,
            }
        room_update = await self._session.execute(
            update(Room)
            .where(Room.id == self._room_id, Room.phase == "InGame")
            .values(**room_values)
        )
        if getattr(room_update, "rowcount", None) != 1:
            raise ContractError("房间当前不是可提交动作的 InGame 阶段")

        state_update = await self._session.execute(
            update(GameSession)
            .where(
                GameSession.room_id == self._room_id,
                GameSession.state_version == expected_version,
            )
            .values(
                state_json=new_state.to_json_dict(),
                state_version=new_state.event_sequence,
                updated_at=now,
            )
        )
        if getattr(state_update, "rowcount", None) != 1:
            raise RevisionConflictError(f"房间 {self._room_id} revision 已不是 {expected_revision}")

        self._session.add_all(
            [
                GameEvent(
                    room_id=self._room_id,
                    sequence=event.sequence,
                    event_id=event.event_id,
                    client_action_id=event.client_action_id,
                    type=event.type,
                    actor_id=event.actor_id,
                    visibility=event.visibility,
                    cause=event.cause,
                    event_schema_version=1,
                    payload=event.payload.to_json_dict(),
                    created_at=now,
                )
                for event in events
            ]
        )
        self._session.add(
            ActionExecution(
                room_id=self._room_id,
                request_id=request.request_id,
                request_schema_version=1,
                request_json=request.to_json_dict(),
                result_schema_version=1,
                result_json=completed_action.execution.to_json_dict(),
                committed_state_version=new_state.event_sequence,
                created_at=now,
            )
        )

        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ContractError("规则引擎提交与已持久化记录冲突") from exc

        if self._before_commit is not None:
            self._before_commit(self._room_id)
        self._committed_events = events
        self._committed_request_id = request.request_id
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
        expected_version = self._parse_revision(expected_revision)
        current_session = await self._session.get(GameSession, self._room_id)
        if current_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        current_state = GameState.model_validate(deepcopy(current_session.state_json))
        if current_session.state_version != expected_version:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 {expected_revision} "
                f"更新为 {current_session.state_version}"
            )
        self._validate_adjudication_commit(
            current_state=current_state,
            new_state=new_state,
            events=events,
            completed_command=completed_command,
        )
        existing_command = await self._session.get(
            AdjudicationCommandExecution,
            (self._room_id, completed_command.request_id),
        )
        if existing_command is not None:
            raise ContractError(f"裁决 request_id 已经提交: {completed_command.request_id}")
        event_ids = tuple(event.event_id for event in events)
        existing_event_id = await self._session.scalar(
            select(GameEvent.event_id).where(
                GameEvent.room_id == self._room_id,
                GameEvent.event_id.in_(event_ids),
            )
        )
        if existing_event_id is not None:
            raise ContractError(f"Event id 已在房间中存在: {existing_event_id}")

        now = datetime.now(UTC)
        room_values: dict[str, object] = {
            "phase": "Completed" if new_state.phase == "ended" else "InGame",
            "updated_at": now,
        }
        if new_state.phase == "ended":
            room_values["ended_at"] = now
        room_update = await self._session.execute(
            update(Room)
            .where(Room.id == self._room_id, Room.phase == "InGame")
            .values(**room_values)
        )
        if getattr(room_update, "rowcount", None) != 1:
            raise ContractError("房间当前不是可提交裁决的 InGame 阶段")
        state_update = await self._session.execute(
            update(GameSession)
            .where(
                GameSession.room_id == self._room_id,
                GameSession.state_version == expected_version,
            )
            .values(
                state_json=new_state.to_json_dict(),
                state_version=new_state.event_sequence,
                updated_at=now,
            )
        )
        if getattr(state_update, "rowcount", None) != 1:
            raise RevisionConflictError(f"房间 {self._room_id} revision 已不是 {expected_revision}")
        self._session.add_all(
            [
                GameEvent(
                    room_id=self._room_id,
                    sequence=event.sequence,
                    event_id=event.event_id,
                    client_action_id=event.client_action_id,
                    type=event.type,
                    actor_id=event.actor_id,
                    visibility=event.visibility,
                    cause=event.cause,
                    event_schema_version=1,
                    payload=deepcopy(event.payload),
                    created_at=now,
                )
                for event in events
            ]
        )
        if decision is not None:
            await self._save_decision(decision, now)
        if check_run is not None:
            await self._save_check_run(check_run, now)
        self._session.add(
            AdjudicationCommandExecution(
                room_id=self._room_id,
                request_id=completed_command.request_id,
                request_schema_version=1,
                request_json=completed_command.request.to_json_dict(),
                result_schema_version=1,
                result_json=completed_command.execution.to_json_dict(),
                committed_state_version=new_state.event_sequence,
                created_at=now,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ContractError("规则引擎裁决提交与已持久化记录冲突") from exc
        if self._before_commit is not None:
            self._before_commit(self._room_id)
        self._committed = True

    def close(self) -> None:
        self._closed = True

    def log_committed_state_changes(self) -> None:
        """仅在 SQLAlchemy 事务真正提交成功后输出状态修改。"""

        if not self._committed or self._committed_request_id is None:
            return
        log_state_changes(
            room_id=self._room_id,
            correlation_id=self._committed_request_id,
            events=self._committed_events,
        )

    def _ensure_active(self) -> None:
        if self._closed:
            raise ContractError("引擎事务已经关闭")

    @staticmethod
    def _parse_revision(revision: str) -> int:
        try:
            value = int(revision)
        except ValueError as exc:
            raise ContractError(f"非法 revision: {revision}") from exc
        if value < 0 or str(value) != revision:
            raise ContractError(f"非法 revision: {revision}")
        return value

    def _validate_commit(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None:
        if current_state.room_id != self._room_id or new_state.room_id != self._room_id:
            raise ContractError("提交的 GameState 与事务房间不一致")

        request = completed_action.request
        request_id = request.request_id
        if request.room_id != self._room_id:
            raise ContractError("CompletedAction 与事务房间不一致")
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
        for event in events:
            if event.room_id != self._room_id:
                raise ContractError("Event 与事务房间不一致")
            if event.client_action_id != request_id:
                raise ContractError("Event 与 CompletedAction request_id 不一致")
            if event.actor_id != request.actor_id:
                raise ContractError("Event 与 CompletedAction actor_id 不一致")

    def _validate_adjudication_commit(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        completed_command: CompletedAdjudicationCommand,
    ) -> None:
        if current_state.room_id != self._room_id or new_state.room_id != self._room_id:
            raise ContractError("提交的 GameState 与裁决事务房间不一致")
        if not events:
            raise ContractError("裁决提交必须至少产生一个领域 Event")
        first_sequence = current_state.event_sequence + 1
        expected_sequences = tuple(range(first_sequence, first_sequence + len(events)))
        if tuple(event.sequence for event in events) != expected_sequences:
            raise ContractError("领域 Event sequence 必须连续递增")
        if new_state.event_sequence != current_state.event_sequence + len(events):
            raise ContractError("GameState event_sequence 与领域 Event 数量不一致")
        event_ids = tuple(event.event_id for event in events)
        if len(event_ids) != len(set(event_ids)):
            raise ContractError("同一次裁决的 Event id 必须唯一")
        for event in events:
            if event.room_id != self._room_id:
                raise ContractError("领域 Event 与事务房间不一致")
            if event.client_action_id != completed_command.request_id:
                raise ContractError("领域 Event 与裁决命令 request_id 不一致")
        if completed_command.execution.view_revision != str(new_state.event_sequence):
            raise ContractError("裁决结果 revision 与 GameState 不一致")

    @staticmethod
    def _decision_from_record(
        record: PendingCheckDecisionRecord | None,
    ) -> PendingCheckDecision | None:
        if record is None:
            return None
        if record.decision_schema_version != 1:
            raise ContractError("不支持的 PendingCheckDecision schema version")
        decision = PendingCheckDecision.model_validate(deepcopy(record.decision_json))
        if (
            decision.room_id != record.room_id
            or decision.decision_id != record.decision_id
            or decision.action_request_id != record.action_request_id
            or decision.status != record.status
            or decision.decision_version != record.decision_version
        ):
            raise ContractError("PendingCheckDecision 列值与 decision_json 不一致")
        return decision

    async def _save_decision(
        self,
        decision: PendingCheckDecision,
        now: datetime,
    ) -> None:
        record = await self._session.get(
            PendingCheckDecisionRecord,
            (self._room_id, decision.decision_id),
        )
        if record is None:
            self._session.add(
                PendingCheckDecisionRecord(
                    room_id=self._room_id,
                    decision_id=decision.decision_id,
                    action_request_id=decision.action_request_id,
                    player_id=decision.player_id,
                    actor_id=decision.actor_id,
                    status=decision.status,
                    decision_version=decision.decision_version,
                    decision_schema_version=1,
                    decision_json=decision.to_json_dict(),
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        record.status = decision.status
        record.decision_version = decision.decision_version
        record.decision_json = decision.to_json_dict()
        record.updated_at = now

    async def _save_check_run(self, check_run: CheckRun, now: datetime) -> None:
        record = await self._session.get(
            CheckRunRecord,
            (self._room_id, check_run.check_id),
        )
        if record is None:
            self._session.add(
                CheckRunRecord(
                    room_id=self._room_id,
                    check_id=check_run.check_id,
                    decision_id=check_run.decision_id,
                    action_request_id=check_run.action_request_id,
                    player_id=check_run.player_id,
                    actor_id=check_run.actor_id,
                    status=check_run.status,
                    version=check_run.version,
                    roll_count=check_run.roll_count,
                    check_schema_version=1,
                    check_json=check_run.to_json_dict(),
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        record.status = check_run.status
        record.version = check_run.version
        record.roll_count = check_run.roll_count
        record.check_json = check_run.to_json_dict()
        record.updated_at = now


def _hydrate_game_state_actor_skills(
    game_state: GameState,
    *,
    ruleset: dict | None,
) -> tuple[GameState, bool]:
    actors = dict(game_state.actors)
    changed = False
    for actor_id, actor in game_state.actors.items():
        actor_state, actor_changed = hydrate_actor_state_from_ruleset(
            actor.state,
            ruleset,
        )
        if not actor_changed:
            continue
        actors[actor_id] = actor.model_copy(update={"state": actor_state})
        changed = True
    if not changed:
        return game_state, False
    return game_state.model_copy(update={"actors": actors}), True
