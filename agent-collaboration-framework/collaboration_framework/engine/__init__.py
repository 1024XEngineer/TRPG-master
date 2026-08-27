"""Deterministic game-rule execution boundary."""



from .adapters import InMemoryEngineStore
from .adjudication import AdjudicationEngineService
from .capabilities import (
    RuntimeCapabilityIssue,
    audit_runtime_capabilities,
    require_runtime_capabilities,
)
from .conditions import (
    ConditionMutation,
    active_conditions,
    apply_condition,
    consume_condition,
    has_active_condition,
    remove_condition,
)
from .dice import DiceRoller, SequenceDiceSource, SystemDiceSource
from .initialization import create_initial_game_state
from .models import (
    ActorCondition,
    ActorResources,
    ActorState,
    AgendaItem,
    AgendaSource,
    CheckRun,
    CompletedAction,
    CompletedAdjudicationCommand,
    ConditionExpiry,
    DomainEvent,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    GameState,
    LocationKnowledge,
    PendingCheckDecision,
    RuleAgenda,
    RuntimeTimeTask,
    StateModifiedEvent,
    TimePointOccurrence,
    WorldTimePoint,
    WorldTimeState,
)
from .navigation import effective_location_knowledge, resolve_location_target
from .persistent_results import (
    CHARACTER_STATE_VALUES,
    OBJECT_STATE_VALUES,
    PUBLIC_STATE_KEYS,
    committed_results_from_events,
    validate_persistent_effects,
)
from .ports import EngineStore, EngineTransaction, RevisionConflictError
from .service import RuleEngineService

__all__ = [
    "CHARACTER_STATE_VALUES",
    "OBJECT_STATE_VALUES",
    "PUBLIC_STATE_KEYS",
    "ActorCondition",
    "ActorResources",
    "ActorState",
    "AdjudicationEngineService",
    "AgendaItem",
    "AgendaSource",
    "CheckRun",
    "CompletedAction",
    "CompletedAdjudicationCommand",
    "ConditionExpiry",
    "ConditionMutation",
    "DiceRoller",
    "DomainEvent",
    "EngineExecutionResult",
    "EngineRuntimeSnapshot",
    "EngineStore",
    "EngineTransaction",
    "GameState",
    "InMemoryEngineStore",
    "LocationKnowledge",
    "PendingCheckDecision",
    "RevisionConflictError",
    "RuleAgenda",
    "RuleEngineService",
    "RuntimeCapabilityIssue",
    "RuntimeTimeTask",
    "SequenceDiceSource",
    "StateModifiedEvent",
    "SystemDiceSource",
    "TimePointOccurrence",
    "WorldTimePoint",
    "WorldTimeState",
    "active_conditions",
    "apply_condition",
    "audit_runtime_capabilities",
    "committed_results_from_events",
    "consume_condition",
    "create_initial_game_state",
    "effective_location_knowledge",
    "has_active_condition",
    "remove_condition",
    "require_runtime_capabilities",
    "resolve_location_target",
    "validate_persistent_effects",
]
