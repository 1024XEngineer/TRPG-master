"""玩家输入到权威执行再到玩家安全叙事的固定回合编排。"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.keeper import FakeKeeper, KeeperAgentPort
from app.models.event import Event
from app.runtime.contracts import (
    ActionRequest,
    Intent,
    PlayerInput,
    PlayerView,
    TurnResult,
)
from app.runtime.engine import ActionExecutor
from app.runtime.projector import PlayerViewProjector
from app.runtime.state import GameState
from app.runtime.store import SQLAlchemyGameStateStore

logger = structlog.get_logger()


class TurnOrchestrator:
    def __init__(
        self,
        *,
        store: SQLAlchemyGameStateStore | None = None,
        executor: ActionExecutor | None = None,
        projector: PlayerViewProjector | None = None,
        keeper: KeeperAgentPort | None = None,
    ) -> None:
        self.store = store or SQLAlchemyGameStateStore()
        self.executor = executor or ActionExecutor(store=self.store)
        self.projector = projector or PlayerViewProjector()
        self.keeper = keeper or FakeKeeper()

    async def run(self, db: AsyncSession, player_input: PlayerInput) -> TurnResult:
        session = await self.store.active_session(db, player_input.room_id)
        if session is None or session.id != player_input.room_session_id:
            raise ValueError("游戏会话不存在")
        state = await self.store.load(db, session.id)
        runtime_module = await self.store.module_for_session(db, session)
        view = self.projector.project(state, runtime_module, actor_id=player_input.actor_id)

        async def execute_action(intent: Intent):
            request = ActionRequest(
                **player_input.model_dump(),
                intent=intent,
            )
            return await self.executor.execute(db, request)

        action = await self.keeper.run_action(player_input, view, execute_action)
        updated_state = await self.store.load(db, session.id)
        updated_view = self.projector.project(
            updated_state, runtime_module, actor_id=player_input.actor_id
        )
        try:
            narration = await self.keeper.narrate(player_input, updated_view, action)
        except Exception as exc:
            logger.warning(
                "keeper_narration_fallback",
                room_session_id=player_input.room_session_id,
                request_id=player_input.request_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            narration = await FakeKeeper().narrate(player_input, updated_view, action)
        updated_view = await self._record_narration(
            db,
            updated_state,
            runtime_module,
            player_input,
            narration.text,
        )
        return TurnResult(action=action, narration=narration, view=updated_view)

    async def resolve_pending(
        self,
        db: AsyncSession,
        *,
        player_input: PlayerInput,
        check_request_id: str,
    ) -> TurnResult:
        action = await self.executor.resolve_pending(
            db,
            room_id=player_input.room_id,
            room_session_id=player_input.room_session_id,
            player_id=player_input.player_id,
            request_id=player_input.request_id,
            check_request_id=check_request_id,
            source_revision=player_input.source_revision,
        )
        session = await self.store.active_session(db, player_input.room_id)
        if session is None:
            # Ending 会把 session 标记 completed；仍按 ID 读取固定 revision。
            from app.models.replay import RoomSession

            session = await db.get(RoomSession, player_input.room_session_id)
        if session is None:
            raise ValueError("游戏会话不存在")
        state = await self.store.load(db, session.id)
        runtime_module = await self.store.module_for_session(db, session)
        view = self.projector.project(state, runtime_module, actor_id=player_input.actor_id)
        try:
            narration = await self.keeper.narrate(player_input, view, action)
        except Exception as exc:
            logger.warning(
                "keeper_narration_fallback",
                room_session_id=player_input.room_session_id,
                request_id=player_input.request_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            narration = await FakeKeeper().narrate(player_input, view, action)
        view = await self._record_narration(db, state, runtime_module, player_input, narration.text)
        return TurnResult(action=action, narration=narration, view=view)

    async def current_view(self, db: AsyncSession, *, room_id: str, actor_id: str) -> PlayerView:
        session = await self.store.active_session(db, room_id)
        if session is None:
            raise ValueError("房间没有进行中的游戏")
        state = await self.store.load(db, session.id)
        runtime_module = await self.store.module_for_session(db, session)
        return self.projector.project(state, runtime_module, actor_id=actor_id)

    async def _record_narration(
        self,
        db: AsyncSession,
        state: GameState,
        runtime_module,
        player_input: PlayerInput,
        text: str,
    ) -> PlayerView:
        snapshot = await self.store.snapshot(db, state.room_session_id)
        state = GameState.model_validate(snapshot.state)
        state.revision = snapshot.revision
        state.event_sequence += 1
        snapshot.state = state.model_dump(mode="json")
        db.add(
            Event(
                room_id=state.room_id,
                room_session_id=state.room_session_id,
                player_id=player_input.player_id,
                sequence=state.event_sequence,
                request_id=player_input.request_id,
                event_type="narration.push",
                payload={"text": text},
                visibility="room",
                state_revision=state.revision,
            )
        )
        await db.commit()
        return self.projector.project(state, runtime_module, actor_id=player_input.actor_id)
