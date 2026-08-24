"""Structured Host inputs, outputs, progress events, and recent-history schemas."""

from .action_plan import (
    RESERVATION_TTL,
    RESERVING_PLAN_STATUSES,
    TERMINAL_PLAN_STATUSES,
    ActionPlanAdvanceResult,
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
    ActionPlanRun,
    ActionPlanStepContext,
    ActionPlanStepRun,
    CompletedPlanStepSummary,
    PlanRunStatus,
    PlanStepStatus,
    reservation_is_expired,
)
from .context import (
    OpeningNarrationContext,
    OpeningParticipant,
    OpeningSceneContext,
)
from .history import (
    HistoryVisibility,
    RecentHistoryBudget,
    RecentSafeResult,
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
)
from .memory import ConversationSummary, MemoryContext, MemoryEntry
from .output import (
    NarrationOutput,
)
from .planner_context import (
    HostAgentContext,
    TurnPlanningContext,
    TurnPlanningReference,
    TurnPlanningView,
)

__all__ = [
    "RESERVATION_TTL",
    "RESERVING_PLAN_STATUSES",
    "TERMINAL_PLAN_STATUSES",
    "ActionPlanAdvanceResult",
    "ActionPlanNarrationContext",
    "ActionPlanNarrationOutput",
    "ActionPlanRun",
    "ActionPlanStepContext",
    "ActionPlanStepRun",
    "CompletedPlanStepSummary",
    "ConversationSummary",
    "HistoryVisibility",
    "HostAgentContext",
    "MemoryContext",
    "MemoryEntry",
    "NarrationOutput",
    "OpeningNarrationContext",
    "OpeningParticipant",
    "OpeningSceneContext",
    "PlanRunStatus",
    "PlanStepStatus",
    "RecentHistoryBudget",
    "RecentSafeResult",
    "RecentTurn",
    "RecentTurnContext",
    "TurnPlanningContext",
    "TurnPlanningReference",
    "TurnPlanningView",
    "VisibleHistoryText",
    "reservation_is_expired",
]
