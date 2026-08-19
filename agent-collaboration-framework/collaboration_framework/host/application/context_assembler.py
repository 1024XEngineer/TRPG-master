"""Pure assembly of model-visible contexts from already safe contracts."""

from collaboration_framework.contracts import PlayerView
from collaboration_framework.host.schemas import (
    OpeningNarrationContext,
    OpeningParticipant,
    OpeningSceneContext,
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
