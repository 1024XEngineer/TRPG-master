from host_orchestrator.schemas.action import ActionResult
from host_orchestrator.schemas.context import IntentContext, NarrationContext
from host_orchestrator.schemas.intent import Intent
from host_orchestrator.schemas.player_input import PlayerInput
from host_orchestrator.schemas.player_view import PlayerView


class ContextAssembler:
    """TODO: assemble only player-visible parser and narrator contexts."""

    def assemble_intent_context(
        self,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> IntentContext:
        raise NotImplementedError("TODO: assemble IntentContext")

    def assemble_narration_context(
        self,
        player_input: PlayerInput,
        intent: Intent,
        action_result: ActionResult,
        player_view: PlayerView,
    ) -> NarrationContext:
        raise NotImplementedError("TODO: assemble NarrationContext")
