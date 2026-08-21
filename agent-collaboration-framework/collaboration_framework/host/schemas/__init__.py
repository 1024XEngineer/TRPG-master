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
from .output import (
    NarrationOutput,
)
from .planner_context import HostAgentContext
from .memory import ConversationSummary, MemoryContext, MemoryEntry

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
    "HostAgentContext",
    "ConversationSummary",
    "MemoryContext",
    "MemoryEntry",
    "HistoryVisibility",
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
    "VisibleHistoryText",
    "reservation_is_expired",
]
