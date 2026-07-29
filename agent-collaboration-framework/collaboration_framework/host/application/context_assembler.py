"""Pure assembly of model-visible contexts from already safe contracts."""

from collaboration_framework.contracts import (
    ActionResult,
    Intent,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.host.schemas import (
    IntentContext,
    NarrationContext,
    RecentTurnContext,
)


class ContextAssembler:
    def for_intent(
        self,
        player_input: PlayerInput,
        player_view: PlayerView,
        recent_history: RecentTurnContext,
    ) -> IntentContext:
        return IntentContext(
            player_input=player_input,
            player_view=player_view,
            recent_history=recent_history,
        )

    def for_narration(
        self,
        player_input: PlayerInput,
        intent: Intent,
        action_result: ActionResult,
        player_view: PlayerView,
        recent_history: RecentTurnContext,
    ) -> NarrationContext:
        return NarrationContext(
            background=player_view.background,
            player_input=player_input,
            intent=intent,
            action_result=action_result,
            player_view=player_view,
            recent_history=recent_history,
        )
