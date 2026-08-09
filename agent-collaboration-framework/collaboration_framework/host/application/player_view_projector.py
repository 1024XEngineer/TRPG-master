"""Member-A deterministic projection over a GameState-free read snapshot."""

from collaboration_framework.contracts import (
    ActionDeclarationOption,
    ActionResult,
    AdjudicationExecution,
    ActorResourceView,
    ActorValueView,
    AvailableExitView,
    CheckpointOption,
    ContractError,
    ExitDestinationView,
    KeeperCapabilityView,
    KnownInformationView,
    KnownLocationView,
    LocationBreadcrumbView,
    LocationContextView,
    NarrativeDetailView,
    ObservableStateView,
    PlayerInput,
    PlayerView,
    PlayerViewScope,
    PositionContextView,
    SceneView,
    SelfActorView,
    VisibleActorView,
    VisibleEntity,
    WorldStateView,
)
from collaboration_framework.ports import PlayerViewSource


class PlayerViewProjector:
    def __init__(self, source: PlayerViewSource) -> None:
        self._source = source

    async def project(self, player_input: PlayerInput) -> PlayerView:
        return await self.project_scope(
            PlayerViewScope(
                room_id=player_input.room_id,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
            )
        )

    async def project_scope(self, scope: PlayerViewScope) -> PlayerView:
        """Project a view for a read-only scope without fabricating a PlayerInput."""

        return await self._read(scope)

    async def keeper_capabilities(
        self,
        player_input: PlayerInput,
        *,
        expected_revision: str | None = None,
    ) -> KeeperCapabilityView:
        """Read the Keeper capability list that accompanies one adjudication.

        `expected_revision` is the revision of the PlayerView it will be paired
        with: the two must describe the same snapshot, or the Agent could name a
        target from one world and a scene from another.
        """

        capabilities = await self._source.read_keeper_capabilities(
            PlayerViewScope(
                room_id=player_input.room_id,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
            )
        )
        if capabilities.actor_id != player_input.actor_id:
            raise ContractError("KeeperCapabilityView 与 PlayerInput 身份作用域不一致")
        if expected_revision is not None and capabilities.revision != expected_revision:
            raise ContractError("KeeperCapabilityView 与 PlayerView revision 不一致")
        return capabilities

    async def refresh(
        self,
        player_input: PlayerInput,
        action_result: ActionResult,
    ) -> PlayerView:
        view = await self.project(player_input)
        if view.revision != action_result.view_revision:
            raise ContractError("动作后 PlayerView revision 与 ActionResult 不一致")
        return view

    async def refresh_adjudication(
        self,
        player_input: PlayerInput,
        execution: AdjudicationExecution,
    ) -> PlayerView:
        view = await self.project(player_input)
        if view.revision != execution.view_revision:
            raise ContractError(
                "裁决后 PlayerView revision 与 AdjudicationExecution 不一致"
            )
        return view

    async def _read(self, scope: PlayerViewScope) -> PlayerView:
        snapshot = await self._source.read(scope)
        if snapshot.room_id != scope.room_id:
            raise ContractError("ProjectionSnapshot 与 PlayerViewScope 房间不一致")
        if snapshot.player_id != scope.player_id or snapshot.actor_id != scope.actor_id:
            raise ContractError(
                "ProjectionSnapshot 与 PlayerViewScope 身份作用域不一致"
            )
        return PlayerView(
            room_id=scope.room_id,
            player_id=scope.player_id,
            actor_id=scope.actor_id,
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
                public_status_summary=snapshot.self_actor.public_status_summary,
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
                        occupation=item.occupation,
                        status_summary=item.status_summary,
                    )
                    for item in snapshot.scene.visible_actors
                ),
                available_exits=tuple(
                    AvailableExitView(
                        id=item.id,
                        name=item.name,
                        target_id=item.target_id,
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
                loose_items=snapshot.scene.loose_items,
            ),
            location_context=(
                LocationContextView(
                    current_location_id=snapshot.location_context.current_location_id,
                    breadcrumbs=tuple(
                        LocationBreadcrumbView(id=item.id, name=item.name)
                        for item in snapshot.location_context.breadcrumbs
                    ),
                    position_context=(
                        PositionContextView(
                            id=snapshot.location_context.position_context.id,
                            label=snapshot.location_context.position_context.label,
                            state=snapshot.location_context.position_context.state,
                            destination_id=(
                                snapshot.location_context.position_context.destination_id
                            ),
                        )
                        if snapshot.location_context.position_context is not None
                        else None
                    ),
                )
                if snapshot.location_context is not None
                else None
            ),
            known_locations=tuple(
                KnownLocationView(
                    id=item.id,
                    kind=item.kind,
                    name=item.name,
                    description=item.description,
                    parent_location_id=item.parent_location_id,
                    region_id=item.region_id,
                    existence=item.existence,
                    localization=item.localization,
                    access=item.access,
                    visited=item.visited,
                )
                for item in snapshot.known_locations
            ),
            inventory=snapshot.inventory,
            world=WorldStateView(
                day_index=snapshot.world.day_index,
                hour_of_day=snapshot.world.hour_of_day,
                time_of_day=snapshot.world.time_of_day,
                core_resolved=snapshot.world.core_resolved,
                ending_available=snapshot.world.ending_available,
                ending_id=snapshot.world.ending_id,
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
                    declaration_options=tuple(
                        ActionDeclarationOption(
                            id=declaration.id,
                            semantic_hints=declaration.semantic_hints,
                        )
                        for declaration in item.declaration_options
                    ),
                )
                for item in snapshot.checkpoint_options
            ),
        )
