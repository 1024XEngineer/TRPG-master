"""Persistence semantics required by the storage-backed engine service."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from collaboration_framework.contracts import ContractError

from ..models import (
    CompletedAction,
    EngineRuntimeSnapshot,
    GameState,
    StateModifiedEvent,
)


class RevisionConflictError(ContractError):
    """Raised when a commit would overwrite a newer room revision."""


class EngineTransaction(Protocol):
    """One room-scoped unit of work with a single atomic commit point."""

    async def load_runtime(self) -> EngineRuntimeSnapshot: ...

    async def find_completed_action(
        self,
        request_id: str,
    ) -> CompletedAction | None: ...

    async def commit(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None: ...


class EngineStore(Protocol):
    """Open a transaction over one room's authoritative runtime."""

    def transaction(
        self,
        room_id: str,
    ) -> AbstractAsyncContextManager[EngineTransaction]: ...
