"""Deterministic game-rule execution boundary."""

# ruff: noqa: F401 -- this module intentionally re-exports the public engine API.

from .adapters import InMemoryEngineStore
from .adjudication import AdjudicationEngineService
from .capabilities import (
    RuntimeCapabilityIssue,
    audit_runtime_capabilities,
    require_runtime_capabilities,
)
from .dice import DiceRoller, SequenceDiceSource, SystemDiceSource
from .initialization import create_initial_game_state
from .models import (
    ActorResources,
    ActorState,
    CheckRun,
    WorldTimePoint,
    WorldTimeState,
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
    "WorldTimePoint",
    "WorldTimeState",
    "CheckRun",
    "DiceRoller",
    "DomainEvent",
    "EngineExecutionResult",
    "EngineRuntimeSnapshot",
    "EngineStore",
    "EngineTransaction",
    "GameState",
    "InMemoryEngineStore",
    "PendingCheckDecision",
    "RevisionConflictError",
    "RuntimeCapabilityIssue",
    "RuleEngineService",
    "SequenceDiceSource",
    "StateModifiedEvent",
    "SystemDiceSource",
    "audit_runtime_capabilities",
    "create_initial_game_state",
    "require_runtime_capabilities",
]
