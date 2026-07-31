"""Public Host application services and validation boundaries."""

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
    is_scene_query_utterance,
    intent_action_contract,
    recover_travel_intent,
)
from .intent_parser import IntentParser, validate_intent_against_view
from .narrator import NarrationValidationError, Narrator, normalize_narration_text
from .opening_narrator import (
    OpeningNarrationValidationError,
    OpeningNarrator,
    deterministic_opening_narration,
)
from .orchestrator import Orchestrator
from .player_view_projector import PlayerViewProjector
from .tool_registry import (
    BoundToolRegistry,
    ToolAccess,
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
)

__all__ = [
    "BoundToolRegistry",
    "ContextAssembler",
    "CORE_ENGINE_ACTIONS",
    "HostAgentEventObserver",
    "HostAgentIntentResolver",
    "IntentResolution",
    "IntentParser",
    "NarrationValidationError",
    "Narrator",
    "OpeningNarrationValidationError",
    "OpeningNarrator",
    "Orchestrator",
    "PlayerViewProjector",
    "REFERENCE_MODULE_ACTIONS",
    "RULE_ENGINE_ACTION_VOCABULARY",
    "ToolAccess",
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "TurnExecutionError",
    "align_intent_for_engine",
    "is_scene_query_utterance",
    "intent_action_contract",
    "normalize_narration_text",
    "deterministic_opening_narration",
    "recover_travel_intent",
    "validate_intent_against_view",
]
