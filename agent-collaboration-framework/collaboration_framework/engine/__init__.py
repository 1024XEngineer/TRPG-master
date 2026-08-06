"""Deterministic game-rule execution boundary."""

# ruff: noqa: F401 -- this module intentionally re-exports the public engine API.

from .adapters import InMemoryEngineStore
from .adjudication import AdjudicationEngineService
from .atomic import FakeAtomicEngine
from .capabilities import (
    RuntimeCapabilityIssue,
    audit_runtime_capabilities,
    require_runtime_capabilities,
)
from .dice import DiceRoller, SequenceDiceSource, SystemDiceSource
from .initialization import create_initial_game_state
from .kernel import RuleKernel
from .models import (
    ActorResources,
    ActorState,
    CheckRun,
    ClockState,
    CompletedAction,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    GameState,
    PendingCheckDecision,
    StateModifiedEvent,
)
from .ports import EngineStore, EngineTransaction, RevisionConflictError
from .service import RuleEngineService

__all__ = [
    "CompletedAction",
    "CompletedAdjudicationCommand",
    "ActorResources",
    "ActorState",
    "AdjudicationEngineService",
    "ClockState",
    "CheckRun",
    "DiceRoller",
    "DomainEvent",
    "EngineExecutionResult",
    "EngineRuntimeSnapshot",
    "EngineStore",
    "EngineTransaction",
    "FakeAtomicEngine",
    "GameState",
    "InMemoryEngineStore",
    "PendingCheckDecision",
    "RevisionConflictError",
    "RuntimeCapabilityIssue",
    "RuleEngineService",
    "RuleKernel",
    "SequenceDiceSource",
    "StateModifiedEvent",
    "SystemDiceSource",
    "audit_runtime_capabilities",
    "create_initial_game_state",
    "require_runtime_capabilities",
]
