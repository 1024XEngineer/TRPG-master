"""Compatibility adapter for the former single-room fake engine."""

from __future__ import annotations

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ModuleContent,
    PlayerInput,
    ProjectionSnapshot,
)

from .adapters import InMemoryEngineStore
from .models import EngineExecutionResult, GameState
from .service import RuleEngineService


class FakeAtomicEngine:
    """Keep the old offline API while delegating to the storage-backed shell."""

    def __init__(self, module_content: ModuleContent, initial_state: GameState) -> None:
        self._room_id = initial_state.room_id
        self._store = InMemoryEngineStore()
        self._store.register_room(
            module_content=module_content,
            initial_state=initial_state,
        )
        self._service = RuleEngineService(self._store)

    async def read(self, player_input: PlayerInput) -> ProjectionSnapshot:
        return await self._service.read(player_input)

    async def execute(self, request: ActionRequest) -> ActionResult:
        return await self._service.execute(request)

    def snapshot(self) -> GameState:
        """B-owned test inspection; host code must not call this method."""

        return self._store.inspect_state(self._room_id)

    def execution_for(self, request_id: str) -> EngineExecutionResult:
        """B/integration-test inspection; not part of the ActionExecutor port."""

        return self._store.inspect_completed_action(
            self._room_id,
            request_id,
        ).execution
