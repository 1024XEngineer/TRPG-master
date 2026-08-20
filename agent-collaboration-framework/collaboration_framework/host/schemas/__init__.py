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
    SingleActionClarificationResult,
    SingleActionTurnResult,
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
    "SingleActionTurnResult",
    "SingleActionClarificationResult",
    "RecentHistoryBudget",
    "RecentSafeResult",
    "RecentTurn",
    "RecentTurnContext",
    "VisibleHistoryText",
    "RESERVATION_TTL",
    "RESERVING_PLAN_STATUSES",
    "TERMINAL_PLAN_STATUSES",
    "reservation_is_expired",
]
