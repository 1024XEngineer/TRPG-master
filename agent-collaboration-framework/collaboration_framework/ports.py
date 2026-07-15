"""Framework-independent collaboration ports.

Only Pydantic contracts appear in these signatures. Plain Python workflow steps
are thin adapters around the runtime ports, so changing orchestration does not
require changes in component implementations.
"""

from __future__ import annotations

from typing import Protocol

from .contracts import (
    ActionResult,
    EngineRequest,
    Intent,
    InterpretRequest,
    NarrationOutput,
    NarrationRequest,
    PlayerInput,
    SummaryOperation,
    TurnContext,
)


class ContextAssembler(Protocol):
    async def assemble_context(self, player_input: PlayerInput) -> TurnContext: ...


class IntentInterpreter(Protocol):
    async def interpret(self, request: InterpretRequest) -> Intent: ...


class AtomicActionEngine(Protocol):
    # Production implementation owns validation, check resolution, Event append,
    # materialized-view update, idempotency and transaction commit in this call.
    async def execute_action(self, request: EngineRequest) -> ActionResult: ...


class Narrator(Protocol):
    async def narrate(self, request: NarrationRequest) -> NarrationOutput: ...


class SummaryOutbox(Protocol):
    """Host-consumed boundary; intentionally not a turn-workflow dependency."""

    async def enqueue(self, operation: SummaryOperation) -> None: ...
