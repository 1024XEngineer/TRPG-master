"""Persistence semantics required by the storage-backed engine service."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from collaboration_framework.contracts import ContractError

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


class RevisionConflictError(ContractError):
    """Raised when a commit would overwrite a newer room revision."""


class EngineTransaction(Protocol):
    """One room-scoped unit of work with a single atomic commit point."""

    async def load_runtime(self) -> EngineRuntimeSnapshot: ...

    async def find_completed_action(
        self,
        request_id: str,
    ) -> CompletedAction | None: ...

    async def find_adjudication_command(
        self,
        request_id: str,
    ) -> CompletedAdjudicationCommand | None: ...

    async def find_latest_adjudication_command_by_action(
        self,
        action_request_id: str,
    ) -> CompletedAdjudicationCommand | None: ...

    async def find_pending_check_by_action(
        self,
        action_request_id: str,
    ) -> PendingCheckDecision | None: ...

    async def load_pending_check(
        self,
        decision_id: str,
    ) -> PendingCheckDecision | None: ...

    async def load_check_run(self, check_id: str) -> CheckRun | None: ...

    async def find_active_action_for_player(
        self,
        player_id: str,
    ) -> str | None:
        """Return the action_request_id of this player's one open check, if any.

        Covers both an unresolved skill choice (`awaiting_skill_choice`) and an
        already-rolled check still waiting on a post-roll decision
        (`awaiting_post_roll_decision`) — the two states a reconnecting client
        cannot otherwise discover without already knowing the action_request_id.
        """
        ...

    async def commit(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None: ...

    async def commit_adjudication(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        decision: PendingCheckDecision | None,
        check_run: CheckRun | None,
        completed_command: CompletedAdjudicationCommand,
    ) -> None: ...


class EngineStore(Protocol):
    """Open a transaction over one room's authoritative runtime."""

    def transaction(
        self,
        room_id: str,
    ) -> AbstractAsyncContextManager[EngineTransaction]: ...

    async def claim_rule_agenda(
        self,
        *,
        room_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RuleAgenda | None:
        """Lease the next runnable Agenda using its stable queue ordering."""
        ...

    async def checkpoint_rule_agenda(
        self,
        *,
        agenda: RuleAgenda,
        worker_id: str,
        expected_lease_version: int,
        now: datetime,
    ) -> RuleAgenda:
        """Persist a cursor/status update owned by a live lease."""
        ...
