"""Explicit async MVP workflow with one stable class entry point."""

from collaboration_framework.contracts import (
    ActionRequest,
    PlayerInput,
    player_input_fingerprint,
)
from collaboration_framework.host.schemas import HostAgentContext, TurnOutput
from collaboration_framework.ports import ActionExecutor

from .context_assembler import ContextAssembler
from .host_agent_intent_resolver import HostAgentIntentResolver
from .narrator import Narrator
from .player_view_projector import PlayerViewProjector


class Orchestrator:
    def __init__(
        self,
        *,
        context_assembler: ContextAssembler,
        host_intent_resolver: HostAgentIntentResolver,
        action_executor: ActionExecutor,
        player_view_projector: PlayerViewProjector,
        narrator: Narrator,
    ) -> None:
        self._context_assembler = context_assembler
        self._host_intent_resolver = host_intent_resolver
        self._action_executor = action_executor
        self._player_view_projector = player_view_projector
        self._narrator = narrator

    async def run(self, player_input: PlayerInput) -> TurnOutput:
        view_before = await self._player_view_projector.project(player_input)
        intent = await self._host_intent_resolver.resolve(
            HostAgentContext(
                player_input=player_input,
                player_view=view_before,
            )
        )

        # Every schema-valid Intent, including unknown/dialogue/no-check, crosses
        # the same authoritative command boundary exactly once.
        action_result = await self._action_executor.execute(
            ActionRequest(
                request_id=player_input.client_action_id,
                room_id=player_input.room_id,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
                source_view_revision=view_before.revision,
                input_fingerprint=player_input_fingerprint(player_input),
                intent=intent,
            )
        )
        view_after = await self._player_view_projector.refresh(
            player_input,
            action_result,
        )
        narration_context = self._context_assembler.for_narration(
            player_input,
            intent,
            action_result,
            view_after,
        )
        narration = await self._narrator.narrate(narration_context)
        status = "clarification" if narration.kind == "clarification" else "completed"
        return TurnOutput(
            status=status,
            player_input=player_input,
            intent=intent,
            action_result=action_result,
            narration=narration,
            player_view=view_after,
        )
