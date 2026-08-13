"""Public Host application services and validation boundaries."""

from .action_plan_narrator import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
)
from .action_plan_orchestrator import ActionPlanOrchestrator, HostTurnDecisionExecutor
from .action_plan_parser import HostTurnDecisionParser
from .context_assembler import ContextAssembler
from .host_agent_intent_resolver import (
    HostAgentEventObserver,
    HostAgentIntentResolver,
    IntentResolution,
    TurnExecutionError,
)
from .intent_aligner import (
    CORE_ENGINE_ACTIONS,
    REFERENCE_MODULE_ACTIONS,
    RULE_ENGINE_ACTION_VOCABULARY,
    align_intent_for_engine,
    intent_action_contract,
    is_scene_query_utterance,
    recover_travel_intent,
)
from .intent_parser import IntentParser, validate_intent_against_view
from .narrator import (
    NarrationValidationError,
    Narrator,
    normalize_narration_text,
    split_narration_chunks,
)
from .opening_narrator import (
    OpeningNarrationValidationError,
    OpeningNarrator,
    deterministic_opening_narration,
)
from .player_view_projector import PlayerViewProjector
from .semantic_preservation import (
    SemanticPreservationResult,
    compare_repair_semantics,
)
from .tool_registry import (
    BoundToolRegistry,
    ToolAccess,
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
)

__all__ = [
    "CORE_ENGINE_ACTIONS",
    "REFERENCE_MODULE_ACTIONS",
    "RULE_ENGINE_ACTION_VOCABULARY",
    "ActionPlanNarrationValidationError",
    "ActionPlanNarrator",
    "ActionPlanOrchestrator",
    "BoundToolRegistry",
    "ContextAssembler",
    "HostAgentEventObserver",
    "HostAgentIntentResolver",
    "HostTurnDecisionExecutor",
    "HostTurnDecisionParser",
    "IntentParser",
    "IntentResolution",
    "NarrationValidationError",
    "Narrator",
    "OpeningNarrationValidationError",
    "OpeningNarrator",
    "PlayerViewProjector",
    "SemanticPreservationResult",
    "ToolAccess",
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "TurnExecutionError",
    "align_intent_for_engine",
    "compare_repair_semantics",
    "deterministic_opening_narration",
    "intent_action_contract",
    "is_scene_query_utterance",
    "normalize_narration_text",
    "recover_travel_intent",
    "split_narration_chunks",
    "validate_intent_against_view",
]
