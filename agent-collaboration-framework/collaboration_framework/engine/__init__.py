"""Deterministic game-rule execution boundary."""

from .atomic import FakeAtomicEngine
from .adapters import InMemoryEngineStore
from .kernel import RuleKernel
from .models import (
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
    "EngineExecutionResult",
    "EngineRuntimeSnapshot",
    "EngineStore",
    "EngineTransaction",
    "FakeAtomicEngine",
    "GameState",
    "InMemoryEngineStore",
    "RevisionConflictError",
    "RuleEngineService",
    "RuleKernel",
    "StateModifiedEvent",
]
