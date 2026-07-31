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
    OpeningNarrationContext,
    OpeningParticipant,
    OpeningSceneContext,
    RecentTurnContext,
)


class ContextAssembler:
    """Build minimal model inputs from player-safe views and completed results."""

    def for_opening(self, player_view: PlayerView) -> OpeningNarrationContext:
        """Expose public scene/participant data, plus solo-only self background."""

        participants = (
            OpeningParticipant(
                actor_id=player_view.self_actor.id,
                name=player_view.self_actor.name,
                occupation=player_view.self_actor.occupation,
                status_summary=player_view.self_actor.public_status_summary,
            ),
            *(
                OpeningParticipant(
                    actor_id=actor.id,
                    name=actor.name,
                    occupation=actor.occupation,
                    status_summary=actor.status_summary,
                )
                for actor in player_view.scene.visible_actors
            ),
        )
        return OpeningNarrationContext(
            background=player_view.background,
            scene=OpeningSceneContext(
                id=player_view.scene.id,
                name=player_view.scene.name,
                description=player_view.scene.description,
                time=player_view.scene.time,
                narrative_details=player_view.scene.narrative_details,
            ),
            participants=participants,
            solo_background_summary=(
                player_view.self_actor.background_summary
                if len(participants) == 1
                else ""
            ),
        )

    def for_intent(
        self,
        player_input: PlayerInput,
        player_view: PlayerView,
        recent_history: RecentTurnContext,
    ) -> IntentContext:
        """Bind the real player action to its safe view and bounded history."""

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
        """Build post-action narration input from already-authoritative results."""

        return NarrationContext(
            background=player_view.background,
            player_input=player_input,
            intent=intent,
            action_result=action_result,
            player_view=player_view,
            recent_history=recent_history,
        )
