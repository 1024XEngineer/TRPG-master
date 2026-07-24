"""Pure assembly of model-visible contexts from already safe contracts."""

from collaboration_framework.contracts import ActionResult, Intent, PlayerInput, PlayerView
from collaboration_framework.host.schemas import IntentContext, NarrationContext


class ContextAssembler:
    def __init__(self, background: str) -> None:
        self._background = background

    def for_intent(
        self,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> IntentContext:
        return IntentContext(player_input=player_input, player_view=player_view)

    def for_narration(
        self,
        player_input: PlayerInput,
        intent: Intent,
        action_result: ActionResult,
        player_view: PlayerView,
    ) -> NarrationContext:
        return NarrationContext(
            background=self._background,
            player_input=player_input,
            intent=intent,
            action_result=action_result,
            player_view=player_view,
        )
