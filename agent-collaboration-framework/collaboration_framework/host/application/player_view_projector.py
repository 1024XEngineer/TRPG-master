"""Member-A deterministic projection over a GameState-free read snapshot."""

from collaboration_framework.contracts import (
    ActionResult,
    ActorResourceView,
    ActorValueView,
    AvailableExitView,
    CheckpointOption,
    ContractError,
    ExitDestinationView,
    KnownInformationView,
    NarrativeDetailView,
    ObservableStateView,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleActorView,
    VisibleEntity,
)
from collaboration_framework.ports import PlayerViewSource


class PlayerViewProjector:
    def __init__(self, source: PlayerViewSource) -> None:
        self._source = source

    async def project(self, player_input: PlayerInput) -> PlayerView:
        return await self._read(player_input)

    async def refresh(
        self,
        player_input: PlayerInput,
        action_result: ActionResult,
    ) -> PlayerView:
        view = await self._read(player_input)
        if view.revision != action_result.view_revision:
            raise ContractError("动作后 PlayerView revision 与 ActionResult 不一致")
        return view

    async def _read(self, player_input: PlayerInput) -> PlayerView:
        snapshot = await self._source.read(player_input)
        if snapshot.room_id != player_input.room_id:
            raise ContractError("ProjectionSnapshot 与 PlayerInput 房间不一致")
        if (
            snapshot.player_id != player_input.player_id
            or snapshot.actor_id != player_input.actor_id
        ):
            raise ContractError("ProjectionSnapshot 与 PlayerInput 身份作用域不一致")
        return PlayerView(
            room_id=player_input.room_id,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            background=snapshot.background,
            scene_id=snapshot.scene_id,
            phase=snapshot.phase,
            revision=snapshot.revision,
            self_actor=SelfActorView(
                id=snapshot.self_actor.id,
                name=snapshot.self_actor.name,
                occupation=snapshot.self_actor.occupation,
                attributes=tuple(
                    ActorValueView(id=item.id, name=item.name, value=item.value)
                    for item in snapshot.self_actor.attributes
                ),
                skills=tuple(
                    ActorValueView(id=item.id, name=item.name, value=item.value)
                    for item in snapshot.self_actor.skills
                ),
                resources=tuple(
                    ActorResourceView(id=item.id, name=item.name, value=item.value)
                    for item in snapshot.self_actor.resources
                ),
                conditions=snapshot.self_actor.conditions,
                equipment=snapshot.self_actor.equipment,
                background_summary=snapshot.self_actor.background_summary,
            ),
            scene=SceneView(
                id=snapshot.scene.id,
                name=snapshot.scene.name,
                description=snapshot.scene.description,
                time=snapshot.scene.time,
                narrative_details=tuple(
                    NarrativeDetailView(
                        id=item.id,
                        kind=item.kind,
                        text=item.text,
                    )
                    for item in snapshot.scene.narrative_details
                ),
                visible_entities=tuple(
                    VisibleEntity(
                        id=item.id,
                        kind=item.kind,
                        name=item.name,
                        aliases=item.aliases,
                        description=item.description,
                        narrative_details=tuple(
                            NarrativeDetailView(
                                id=detail.id,
                                kind=detail.kind,
                                text=detail.text,
                            )
                            for detail in item.narrative_details
                        ),
                        observable_state=tuple(
                            ObservableStateView(
                                key=field.key,
                                label=field.label,
                                value=field.value,
                            )
                            for field in item.observable_state
                        ),
                    )
                    for item in snapshot.scene.visible_entities
                ),
                visible_actors=tuple(
                    VisibleActorView(
                        id=item.id,
                        name=item.name,
                        status_summary=item.status_summary,
                    )
                    for item in snapshot.scene.visible_actors
                ),
                available_exits=tuple(
                    AvailableExitView(
                        id=item.id,
                        name=item.name,
                        aliases=item.aliases,
                        description=item.description,
                        destination=(
                            ExitDestinationView(
                                scene_id=item.destination.scene_id,
                                name=item.destination.name,
                            )
                            if item.destination is not None
                            else None
                        ),
                    )
                    for item in snapshot.scene.available_exits
                ),
            ),
            known_information=tuple(
                KnownInformationView(
                    id=item.id,
                    title=item.title,
                    summary=item.summary,
                    content=item.content,
                    related_entities=item.related_entities,
                    related_scenes=item.related_scenes,
                    scope=item.scope,
                )
                for item in snapshot.known_information
            ),
            checkpoint_options=tuple(
                CheckpointOption(
                    id=item.id,
                    target_id=item.target_id,
                    action_hint=item.action_hint,
                    skills=item.skills,
                    difficulty=item.difficulty,
                )
                for item in snapshot.checkpoint_options
            ),
        )
