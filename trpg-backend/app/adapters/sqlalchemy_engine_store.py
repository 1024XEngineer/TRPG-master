"""SQLAlchemy implementation of the rule-engine persistence port (issue #121)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime

from collaboration_framework.contracts import ActionRequest, ContractError, ModuleContent
from collaboration_framework.engine import (
    CompletedAction,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    EngineStore,
    EngineTransaction,
    GameState,
    RevisionConflictError,
    StateModifiedEvent,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.engine import ActionExecution, GameEvent, GameSession, ModuleVersion
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
        async with self._session_factory() as session, session.begin():
            transaction = _SqlAlchemyEngineTransaction(
                room_id=room_id,
                session=session,
                before_commit=self._before_commit,
            )
            try:
                yield transaction
            finally:
                transaction.close()


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
        if module_version.content_schema_version != 1:
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
        self._committed = True

    def close(self) -> None:
        self._closed = True

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
