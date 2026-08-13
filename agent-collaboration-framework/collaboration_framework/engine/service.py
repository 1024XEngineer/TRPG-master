"""Storage-backed command and read service exposed to the host ports."""

from __future__ import annotations

from collaboration_framework.contracts import (
    ActionRequest,
    ActorBindingError,
    CheckpointSpec,
    ContractError,
    KeeperCapabilityView,
    KeeperEndingCapability,
    KeeperEntityCapability,
    KeeperInformationCapability,
    KeeperLocationCapability,
    NarrativeDetailSpec,
    PlayerViewScope,
    ProjectionActionDeclarationOption,
    ProjectionActorResource,
    ProjectionActorValue,
    ProjectionAvailableExit,
    ProjectionCheckpointOption,
    ProjectionEntity,
    ProjectionExitDestination,
    ProjectionKnownInformation,
    ProjectionNarrativeDetail,
    ProjectionObservableState,
    ProjectionScene,
    ProjectionSelfActor,
    ProjectionSnapshot,
    ProjectionVisibleActor,
    ProjectionWorldState,
    SceneSpec,
    VisibilityPolicy,
)
from pydantic import JsonValue

from .expression import ExpressionEvaluator, expression_context
from .projection_v3 import keeper_capabilities_v3, project_v3
from .models import EngineRuntimeSnapshot
from .ports import EngineStore


class RuleEngineService:
    """Stateless-over-rooms read façade for the player view (#226: read-only).

    The authoritative write path used to sit here as `execute`, driving the
    Checkpoint kernel. Writes now belong to the adjudication engine and the
    ActionPlan runtime; this class only projects.
    """

    def __init__(self, store: EngineStore) -> None:
        self._store = store

    async def read(self, scope: PlayerViewScope) -> ProjectionSnapshot:
        async with self._store.transaction(scope.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )
            return self._project(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )

    @staticmethod
    def _validate_identity(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> None:
        actor = runtime.game_state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            raise ActorBindingError("player_id/actor_id 未绑定到当前房间")

    @staticmethod
    def _project(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> ProjectionSnapshot:
        if runtime.is_v3:
            return project_v3(runtime, player_id=player_id, actor_id=actor_id)
        module = runtime.v2
        state = runtime.game_state
        scene = next(
            (item for item in module.scenes if item.id == state.scene_id),
            None,
        )
        runtime_location = state.runtime_locations.get(state.scene_id)
        if scene is None and runtime_location is None:
            raise ContractError(f"当前 Scene 不存在: {state.scene_id}")
        if scene is None:
            # Standing inside a location the Agent created via
            # `ensure_runtime_location`. It has no SceneSpec, so everything that
            # is authored per-Scene (checkpoints, narrative details, authored
            # exits) is simply absent rather than fabricated.
            scene = RuleEngineService._runtime_scene_spec(
                state.scene_id,
                runtime_location,
            )
        actor = state.actors[actor_id]
        entities = {item.id: item for item in module.entities}
        scenes = {item.id: item for item in module.scenes}
        canon_entities = tuple(
            ProjectionEntity(
                id=entity.id,
                kind=entity.kind,
                name=entity.player_visible_name,
                aliases=entity.player_visible_aliases,
                description=entity.content,
                narrative_details=RuleEngineService._project_narrative_details(
                    entity.narrative_details,
                    runtime=runtime,
                    player_id=player_id,
                    actor_id=actor_id,
                    target_id=entity.id,
                ),
                observable_state=tuple(
                    ProjectionObservableState(
                        key=field.key,
                        label=field.label,
                        value=state.entities[entity.id][field.key],
                    )
                    for field in entity.observable_state
                    if field.key in state.entities.get(entity.id, {})
                    and RuleEngineService._policy_is_visible(
                        field.visibility,
                        runtime=runtime,
                        player_id=player_id,
                        actor_id=actor_id,
                        target_id=entity.id,
                    )
                ),
            )
            for entity_id in scene.entity_ids
            if (entity := entities[entity_id])
            and RuleEngineService._policy_is_visible(
                entity.visibility,
                runtime=runtime,
                player_id=player_id,
                actor_id=actor_id,
                target_id=entity.id,
            )
            and RuleEngineService._override_allows(
                state.visibility_overrides,
                actor_id=actor_id,
                target_kind="entity",
                target_id=entity.id,
            )
        )
        # Canon entities are placed by the module; runtime ones the Agent
        # created or moved carry their own location_id, and a Canon entity that
        # was moved out of its authored Scene has an override recorded the same
        # way. Both are projected here so `ensure_runtime_entity` / `move_entity`
        # are observable instead of silently committed.
        visible_entities = canon_entities + RuleEngineService._project_placed_entities(
            runtime,
            scene_id=scene.id,
            actor_id=actor_id,
            already_projected={entity.id for entity in canon_entities},
            canon_entities=entities,
        )
        visible_entity_ids = {entity.id for entity in visible_entities}
        available_exits = RuleEngineService._project_available_exits(
            runtime,
            scene=scene,
            scenes=scenes,
            player_id=player_id,
            actor_id=actor_id,
        )
        return ProjectionSnapshot(
            room_id=state.room_id,
            player_id=player_id,
            actor_id=actor_id,
            background=module.background,
            scene_id=scene.id,
            phase=state.phase,
            revision=runtime.revision,
            self_actor=RuleEngineService._project_self_actor(actor_id, actor),
            scene=ProjectionScene(
                id=scene.id,
                name=scene.player_visible_name,
                description=scene.player_visible_description,
                time=state.world_time.time_of_day,
                narrative_details=RuleEngineService._project_narrative_details(
                    scene.narrative_details,
                    runtime=runtime,
                    player_id=player_id,
                    actor_id=actor_id,
                    target_id=scene.id,
                ),
                visible_entities=visible_entities,
                visible_actors=tuple(
                    ProjectionVisibleActor(
                        id=other_actor_id,
                        name=other_actor.name,
                        occupation=RuleEngineService._optional_text(
                            other_actor.state.get("occupation")
                        ),
                        status_summary=RuleEngineService._public_status_summary(
                            other_actor.state
                        ),
                    )
                    for other_actor_id, other_actor in state.actors.items()
                    if other_actor_id != actor_id
                ),
                available_exits=available_exits,
            ),
            world=ProjectionWorldState(
                day_index=state.world_time.current.day_index,
                hour_of_day=state.world_time.current.hour_of_day,
                time_of_day=state.world_time.time_of_day,
                core_resolved=state.core_resolved,
                ending_available=state.ending_available,
                ending_id=state.ending_id,
            ),
            known_information=RuleEngineService._project_known_information(
                runtime,
                actor_id=actor_id,
            ),
            checkpoint_options=tuple(
                ProjectionCheckpointOption(
                    id=checkpoint.id,
                    target_id=checkpoint.target_id,
                    action_hint=checkpoint.action,
                    skills=checkpoint.skills,
                    difficulty=checkpoint.difficulty,
                    declaration_options=tuple(
                        ProjectionActionDeclarationOption(
                            id=declaration.id,
                            semantic_hints=declaration.semantic_hints,
                        )
                        for declaration in checkpoint.declaration_options
                    ),
                )
                for checkpoint in module.checkpoints
                if checkpoint.id in scene.checkpoint_ids
                and checkpoint.target_id in visible_entity_ids
                and RuleEngineService._checkpoint_is_visible(
                    checkpoint,
                    runtime=runtime,
                    player_id=player_id,
                    actor_id=actor_id,
                )
            ),
        )

    async def read_keeper_capabilities(
        self,
        scope: PlayerViewScope,
    ) -> KeeperCapabilityView:
        """Project the controlled Keeper-side capability list for one Agent run.

        Same runtime snapshot and revision as :meth:`read`, so an adjudication
        written against this list is refused on submit once the world moves.
        This never reaches the client or the Narrator — see
        :mod:`collaboration_framework.contracts.keeper_view`.
        """

        async with self._store.transaction(scope.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )
            return self._project_keeper_capabilities(runtime, actor_id=scope.actor_id)

    @staticmethod
    def _project_keeper_capabilities(
        runtime: EngineRuntimeSnapshot,
        *,
        actor_id: str,
    ) -> KeeperCapabilityView:
        if runtime.is_v3:
            return keeper_capabilities_v3(runtime, actor_id=actor_id)
        module = runtime.v2
        state = runtime.game_state
        party_known = set(state.discovered_facts)
        actor_known = set(state.actor_discovered_facts.get(actor_id, ()))
        information = tuple(
            KeeperInformationCapability(
                id=item.id,
                title=item.title or item.id,
                summary=item.summary or item.content,
                content=item.content,
                related_entities=item.related_entities,
                related_scenes=item.related_scenes,
                known_by_party=item.id in party_known,
                known_by_actor=item.id in actor_known,
            )
            for item in module.information_items
        )
        locations = tuple(
            KeeperLocationCapability(
                id=scene.id,
                name=scene.player_visible_name or scene.name,
                origin="canon",
                is_current=scene.id == state.scene_id,
            )
            for scene in module.scenes
        ) + tuple(
            KeeperLocationCapability(
                id=location_id,
                name=(
                    RuleEngineService._optional_text(payload.get("name")) or location_id
                ),
                origin="runtime",
                is_current=location_id == state.scene_id,
            )
            for location_id, payload in sorted(state.runtime_locations.items())
        )
        canon_scene_of = {
            entity_id: scene.id
            for scene in module.scenes
            for entity_id in scene.entity_ids
        }
        entities = tuple(
            KeeperEntityCapability(
                id=entity.id,
                name=entity.player_visible_name or entity.id,
                kind=entity.kind,
                origin="canon",
                location_id=RuleEngineService._optional_text(
                    state.entities.get(entity.id, {}).get("location_id")
                )
                or canon_scene_of.get(entity.id),
                holder_actor_id=RuleEngineService._optional_text(
                    state.entities.get(entity.id, {}).get("holder_actor_id")
                ),
                consumed=state.entities.get(entity.id, {}).get("consumed") is True,
            )
            for entity in module.entities
        ) + tuple(
            KeeperEntityCapability(
                id=entity_id,
                name=RuleEngineService._optional_text(payload.get("name")) or entity_id,
                kind=(
                    payload["kind"]
                    if payload.get("kind") in {"npc", "object", "location"}
                    else "object"
                ),
                origin="runtime",
                location_id=RuleEngineService._optional_text(payload.get("location_id")),
                holder_actor_id=RuleEngineService._optional_text(
                    payload.get("holder_actor_id")
                ),
                consumed=payload.get("consumed") is True,
            )
            for entity_id, payload in sorted(state.runtime_entities.items())
        )
        return KeeperCapabilityView(
            room_id=state.room_id,
            actor_id=actor_id,
            revision=runtime.revision,
            information=information,
            locations=locations,
            entities=entities,
            endings=tuple(
                KeeperEndingCapability(
                    id=condition.id,
                    summary=condition.player_visible_information or condition.fact,
                )
                for condition in module.win_conditions
                if condition.is_ending
            ),
            core_resolved=state.core_resolved,
            ending_available=state.ending_available,
        )

    @staticmethod
    def _runtime_scene_spec(
        location_id: str,
        runtime_location: dict[str, JsonValue],
    ) -> SceneSpec:
        """Adapt an Agent-created runtime location to the Scene shape.

        `exits` is left restricted to the location it was connected to, so a
        runtime location never silently opens travel to every Canon Scene.
        """

        name = RuleEngineService._optional_text(runtime_location.get("name")) or location_id
        connected = RuleEngineService._optional_text(
            runtime_location.get("connected_location_id")
        )
        parent = RuleEngineService._optional_text(runtime_location.get("parent_location_id"))
        neighbours = tuple(dict.fromkeys(item for item in (connected, parent) if item))
        return SceneSpec(
            id=location_id,
            name=name,
            content=name,
            player_visible_name=name,
            player_visible_description="",
            entity_ids=(),
            checkpoint_ids=(),
            exits=neighbours,
        )

    @staticmethod
    def _project_placed_entities(
        runtime: EngineRuntimeSnapshot,
        *,
        scene_id: str,
        actor_id: str,
        already_projected: set[str],
        canon_entities: dict[str, object],
    ) -> tuple[ProjectionEntity, ...]:
        """Project entities whose current placement — not the module — puts them here.

        Covers `ensure_runtime_entity` (a brand-new npc/object) and `move_entity`
        (a Canon or runtime entity relocated into this scene or carried by the
        acting actor). Consumed entities drop out, which is what
        `consume_entity` is for.
        """

        state = runtime.game_state
        placed: list[ProjectionEntity] = []
        sources: list[tuple[str, dict[str, JsonValue], str]] = [
            (entity_id, payload, "runtime")
            for entity_id, payload in state.runtime_entities.items()
        ]
        sources += [
            (entity_id, payload, "canon")
            for entity_id, payload in state.entities.items()
            if entity_id not in state.runtime_entities
        ]
        for entity_id, payload, origin in sources:
            if entity_id in already_projected or payload.get("consumed") is True:
                continue
            location_id = RuleEngineService._optional_text(payload.get("location_id"))
            holder_actor_id = RuleEngineService._optional_text(payload.get("holder_actor_id"))
            here = location_id == scene_id or holder_actor_id == actor_id
            if not here:
                continue
            if not RuleEngineService._override_allows(
                state.visibility_overrides,
                actor_id=actor_id,
                target_kind="entity",
                target_id=entity_id,
            ):
                continue
            canon = canon_entities.get(entity_id) if origin == "canon" else None
            name = RuleEngineService._optional_text(payload.get("name"))
            kind = payload.get("kind")
            placed.append(
                ProjectionEntity(
                    id=entity_id,
                    kind=(
                        kind
                        if kind in {"npc", "object", "location"}
                        else getattr(canon, "kind", "object")
                    ),
                    name=(name or getattr(canon, "player_visible_name", "") or entity_id),
                    aliases=getattr(canon, "player_visible_aliases", ()),
                    description=getattr(canon, "content", ""),
                )
            )
        placed.sort(key=lambda entity: entity.id)
        return tuple(placed)

    @staticmethod
    def _override_allows(
        overrides: dict[str, bool],
        *,
        actor_id: str,
        target_kind: str,
        target_id: str,
    ) -> bool:
        """Apply a `set_visibility` effect, actor scope winning over party scope."""

        actor_key = f"actor:{actor_id}:{target_kind}:{target_id}"
        if actor_key in overrides:
            return overrides[actor_key]
        return overrides.get(f"party:{target_kind}:{target_id}", True)

    @staticmethod
    def _project_available_exits(
        runtime: EngineRuntimeSnapshot,
        *,
        scene: SceneSpec,
        scenes: dict[str, SceneSpec],
        player_id: str,
        actor_id: str,
    ) -> tuple[ProjectionAvailableExit, ...]:
        """Project routes without requiring extra metadata in ModuleContent.

        ``SceneSpec.exits`` is an optional restriction list: an empty list means
        every other Scene is reachable, while a non-empty list limits travel to
        the listed Scene ids.  Explicit ``available_exits`` remain supported as
        presentation/visibility overrides, but are not required for movement.
        """

        projected: list[ProjectionAvailableExit] = []
        described_destinations = {
            available_exit.destination_scene_id
            for available_exit in scene.available_exits
        }
        for available_exit in scene.available_exits:
            if not RuleEngineService._policy_is_visible(
                available_exit.visibility,
                runtime=runtime,
                player_id=player_id,
                actor_id=actor_id,
                target_id=available_exit.destination_scene_id,
            ):
                continue
            destination = scenes[available_exit.destination_scene_id]
            projected.append(
                ProjectionAvailableExit(
                    id=available_exit.id,
                    name=available_exit.name,
                    target_id=available_exit.target_id,
                    aliases=available_exit.aliases,
                    description=available_exit.description,
                    destination=(
                        ProjectionExitDestination(
                            scene_id=destination.id,
                            name=(
                                destination.player_visible_name or available_exit.name
                            ),
                        )
                        if available_exit.reveal_destination
                        else None
                    ),
                )
            )

        reachable_scene_ids = (
            scene.exits
            if scene.exits
            else tuple(
                destination.id
                for destination in scenes.values()
                if destination.id != scene.id
            )
        )
        # Runtime locations are reachable from whatever they were attached to,
        # and never from everywhere: `ensure_runtime_location` requires a
        # `connected_location_id`, and that connection is the only route in.
        runtime_locations = runtime.game_state.runtime_locations
        reachable_scene_ids += tuple(
            location_id
            for location_id, payload in runtime_locations.items()
            if location_id != scene.id
            and scene.id
            in {
                payload.get("connected_location_id"),
                payload.get("parent_location_id"),
            }
            and location_id not in reachable_scene_ids
        )
        for destination_scene_id in reachable_scene_ids:
            if destination_scene_id in described_destinations:
                continue
            runtime_destination = runtime_locations.get(destination_scene_id)
            if runtime_destination is not None and destination_scene_id not in scenes:
                destination_name = (
                    RuleEngineService._optional_text(runtime_destination.get("name"))
                    or destination_scene_id
                )
            else:
                destination = scenes[destination_scene_id]
                destination_name = destination.player_visible_name or destination.name
            if not RuleEngineService._override_allows(
                runtime.game_state.visibility_overrides,
                actor_id=actor_id,
                target_kind="location",
                target_id=destination_scene_id,
            ):
                continue
            projected.append(
                ProjectionAvailableExit(
                    id=destination_scene_id,
                    name=destination_name,
                    description="",
                    destination=ProjectionExitDestination(
                        scene_id=destination_scene_id,
                        name=destination_name,
                    ),
                )
            )
        return tuple(projected)

    @staticmethod
    def _project_self_actor(actor_id: str, actor) -> ProjectionSelfActor:
        actor_state = actor.state
        attributes = actor_state.get("attributes")
        skills = actor_state.get("skills")
        attribute_labels = actor_state.get("attribute_labels")
        skill_labels = actor_state.get("skill_labels")
        resources = actor.resources.model_dump(mode="python")

        return ProjectionSelfActor(
            id=actor_id,
            name=actor.name,
            occupation=RuleEngineService._optional_text(actor_state.get("occupation")),
            attributes=RuleEngineService._project_actor_values(
                attributes,
                attribute_labels,
            ),
            skills=RuleEngineService._project_actor_values(skills, skill_labels),
            resources=tuple(
                ProjectionActorResource(
                    id=resource_id,
                    name=resource_id.upper(),
                    value=value,
                )
                for resource_id, value in resources.items()
                if isinstance(value, int) and not isinstance(value, bool)
            ),
            conditions=tuple(
                item
                for item in actor.conditions
                if isinstance(item, str) and item.strip()
            ),
            equipment=RuleEngineService._project_equipment(
                actor_state.get("equipment")
            ),
            background_summary=(
                RuleEngineService._optional_text(actor_state.get("background")) or ""
            ),
            public_status_summary=RuleEngineService._public_status_summary(actor_state),
        )

    @staticmethod
    def _project_actor_values(values, labels) -> tuple[ProjectionActorValue, ...]:
        if not isinstance(values, dict):
            return ()
        label_map = labels if isinstance(labels, dict) else {}
        projected: list[ProjectionActorValue] = []
        for value_id, value in values.items():
            if (
                not isinstance(value_id, str)
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
            ):
                continue
            label = label_map.get(value_id)
            projected.append(
                ProjectionActorValue(
                    id=value_id,
                    name=label
                    if isinstance(label, str) and label.strip()
                    else value_id,
                    value=value,
                )
            )
        return tuple(projected)

    @staticmethod
    def _project_equipment(value) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        equipment: list[str] = []
        for item in value:
            name = item if isinstance(item, str) else None
            if isinstance(item, dict):
                name = item.get("name")
            if isinstance(name, str) and name.strip():
                equipment.append(name)
        return tuple(equipment)

    @staticmethod
    def _optional_text(value) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _public_status_summary(actor_state) -> str:
        if not isinstance(actor_state, dict):
            return ""
        value = actor_state.get("public_status")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _project_known_information(
        runtime: EngineRuntimeSnapshot,
        *,
        actor_id: str,
    ) -> tuple[ProjectionKnownInformation, ...]:
        state = runtime.game_state
        party_ids = set(state.discovered_facts)
        actor_ids = set(state.actor_discovered_facts.get(actor_id, ()))
        projected: list[ProjectionKnownInformation] = []
        for information in runtime.module_content.information_items:
            if not RuleEngineService._override_allows(
                state.visibility_overrides,
                actor_id=actor_id,
                target_kind="information",
                target_id=information.id,
            ):
                continue
            policy = information.visibility
            actor_scoped = (
                policy.audience == "actor" or not policy.discovery_shares_to_party
            )
            if actor_scoped:
                if information.id not in actor_ids:
                    continue
                scope = "actor"
            elif information.id in party_ids:
                scope = "party"
            elif information.id in actor_ids:
                scope = "actor"
            else:
                continue
            # Discovery lists are written only by the authoritative engine
            # after an outcome releases a fact. Module authors may keep the
            # source information item keeper-only before discovery; once its id
            # is present here, the fact itself is player-safe by definition.
            projected.append(
                ProjectionKnownInformation(
                    id=information.id,
                    title=information.title or information.id,
                    summary=information.summary or information.content,
                    content=information.content,
                    related_entities=information.related_entities,
                    related_scenes=information.related_scenes,
                    scope=scope,
                )
            )
        return tuple(projected)

    @staticmethod
    def _checkpoint_is_visible(
        checkpoint: CheckpointSpec,
        *,
        runtime: EngineRuntimeSnapshot,
        player_id: str,
        actor_id: str,
    ) -> bool:
        """Evaluate discovery rules over a read-only snapshot."""

        policy = checkpoint.visibility
        if policy is None:
            return True
        return RuleEngineService._policy_is_visible(
            policy,
            runtime=runtime,
            player_id=player_id,
            actor_id=actor_id,
            target_id=checkpoint.target_id,
        )

    @staticmethod
    def _project_narrative_details(
        details: tuple[NarrativeDetailSpec, ...],
        *,
        runtime: EngineRuntimeSnapshot,
        player_id: str,
        actor_id: str,
        target_id: str,
    ) -> tuple[ProjectionNarrativeDetail, ...]:
        return tuple(
            ProjectionNarrativeDetail(
                id=detail.id,
                kind=detail.kind,
                text=detail.text,
            )
            for detail in details
            if RuleEngineService._policy_is_visible(
                detail.visibility,
                runtime=runtime,
                player_id=player_id,
                actor_id=actor_id,
                target_id=target_id,
            )
        )

    @staticmethod
    def _policy_is_visible(
        policy: VisibilityPolicy,
        *,
        runtime: EngineRuntimeSnapshot,
        player_id: str,
        actor_id: str,
        target_id: str,
    ) -> bool:
        if not RuleEngineService._is_visible_to_actor(policy):
            return False
        if not policy.requires_discovery:
            return True
        if policy.discovery_rule is None:
            return False
        synthetic_request = ActionRequest(
            request_id="projection",
            room_id=runtime.game_state.room_id,
            player_id=player_id,
            actor_id=actor_id,
            source_view_revision=runtime.revision,
            intent={
                "kind": "action",
                "verb": "project",
                "target": {"matched": True, "id": target_id},
                "check": {"route": "none"},
                "summary": "project player-visible data",
            },
        )
        try:
            # This used to route through RuleKernel.condition_matches, which also
            # understood path/equals conditions. A discovery rule is always an
            # expression, so the kernel's removal (#226) costs this call nothing.
            return ExpressionEvaluator().matches(
                policy.discovery_rule,
                expression_context(
                    runtime.game_state.model_dump(mode="python", by_alias=True),
                    request=synthetic_request,
                    target_id=target_id,
                ),
            )
        except ContractError:
            # Projection policies fail closed when optional runtime data is absent.
            return False

    @staticmethod
    def _is_visible_to_actor(policy: VisibilityPolicy) -> bool:
        return policy.audience not in {"keeper", "ho"}
