"""Deterministic game-rule execution boundary."""

from .atomic import FakeAtomicEngine
from .adapters import InMemoryEngineStore
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
    ClockState,
    CompletedAction,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    GameState,
    StateModifiedEvent,
)
from .ports import EngineStore, EngineTransaction, RevisionConflictError
from .service import RuleEngineService

__all__ = [
    "CompletedAction",
    "ActorResources",
    "ActorState",
    "ClockState",
    "DiceRoller",
    "EngineExecutionResult",
    "EngineRuntimeSnapshot",
    "EngineStore",
    "EngineTransaction",
    "FakeAtomicEngine",
    "GameState",
    "InMemoryEngineStore",
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
