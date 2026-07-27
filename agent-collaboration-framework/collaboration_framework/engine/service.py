"""Storage-backed command and read service exposed to the host ports."""

from __future__ import annotations

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    CheckpointSpec,
    ConditionSpec,
    ContractError,
    PlayerInput,
    ProjectionActorResource,
    ProjectionActorValue,
    ProjectionAvailableExit,
    ProjectionCheckpointOption,
    ProjectionEntity,
    ProjectionExitDestination,
    ProjectionKnownInformation,
    ProjectionObservableState,
    ProjectionScene,
    ProjectionSelfActor,
    ProjectionSnapshot,
    ProjectionVisibleActor,
    SceneSpec,
    VisibilityPolicy,
)

from .capabilities import require_runtime_capabilities
from .kernel import RuleKernel
from .models import CompletedAction, EngineRuntimeSnapshot
from .ports import EngineStore


class RuleEngineService:
    """Stateless-over-rooms façade implementing both stable host ports."""

    def __init__(
        self,
        store: EngineStore,
        kernel: RuleKernel | None = None,
    ) -> None:
        self._store = store
        self._kernel = kernel or RuleKernel()

    async def read(self, player_input: PlayerInput) -> ProjectionSnapshot:
        async with self._store.transaction(player_input.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
            )
            return self._project(
                runtime,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
            )

    async def execute(self, request: ActionRequest) -> ActionResult:
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=request.player_id,
                actor_id=request.actor_id,
            )

            completed = await transaction.find_completed_action(request.request_id)
            if completed is not None:
                return self._replay_result(
                    request=request,
                    completed=completed,
                    current_revision=runtime.revision,
                )
            if request.source_view_revision != runtime.revision:
                raise ContractError("ActionRequest 基于过期 PlayerView")
            require_runtime_capabilities(runtime.module_content)

            execution, new_state = self._kernel.execute(
                request=request,
                module_content=runtime.module_content,
                game_state=runtime.game_state,
            )
            completed = CompletedAction(
                request=request.model_copy(deep=True),
                execution=execution.model_copy(deep=True),
            )
            await transaction.commit(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=execution.events,
                completed_action=completed,
            )
            return execution.action_result.model_copy(deep=True)

    @staticmethod
    def _validate_identity(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> None:
        actor = runtime.game_state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            raise ContractError("player_id/actor_id 未绑定到当前房间")

    @staticmethod
    def _replay_result(
        *,
        request: ActionRequest,
        completed: CompletedAction,
        current_revision: str,
    ) -> ActionResult:
        original = completed.request
        if (
            request.room_id,
            request.player_id,
            request.actor_id,
            request.intent,
            request.roll_value,
        ) != (
            original.room_id,
            original.player_id,
            original.actor_id,
            original.intent,
            original.roll_value,
        ):
            raise ContractError("request_id 已用于不同的动作请求")

        return completed.execution.action_result.model_copy(
            update={"view_revision": current_revision},
            deep=True,
        )

    @staticmethod
    def _project(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> ProjectionSnapshot:
        module = runtime.module_content
        state = runtime.game_state
        scene = next(
            (item for item in module.scenes if item.id == state.scene_id),
            None,
        )
        if scene is None:
            raise ContractError(f"当前 Scene 不存在: {state.scene_id}")
        actor = state.actors[actor_id]
        entities = {item.id: item for item in module.entities}
        scenes = {item.id: item for item in module.scenes}
        visible_entities = tuple(
            ProjectionEntity(
                id=entity.id,
                kind=entity.kind,
                name=entity.name,
                aliases=entity.aliases,
                description=entity.content,
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
            scene_id=scene.id,
            phase=state.phase,
            revision=runtime.revision,
            self_actor=RuleEngineService._project_self_actor(actor_id, actor),
            scene=ProjectionScene(
                id=scene.id,
                name=scene.player_visible_name,
                description=scene.player_visible_description,
                time=state.clock.time_of_day,
                visible_entities=visible_entities,
                visible_actors=tuple(
                    ProjectionVisibleActor(
                        id=other_actor_id,
                        name=other_actor.name,
                        status_summary=RuleEngineService._public_status_summary(
                            other_actor.state
                        ),
                    )
                    for other_actor_id, other_actor in state.actors.items()
                    if other_actor_id != actor_id
                ),
                available_exits=available_exits,
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
                    aliases=available_exit.aliases,
                    description=available_exit.description,
                    destination=(
                        ProjectionExitDestination(
                            scene_id=destination.id,
                            name=(
                                destination.player_visible_name
                                or available_exit.name
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
        for destination_scene_id in reachable_scene_ids:
            if destination_scene_id in described_destinations:
                continue
            destination = scenes[destination_scene_id]
            destination_name = destination.player_visible_name or destination.name
            projected.append(
                ProjectionAvailableExit(
                    id=destination.id,
                    name=destination_name,
                    description="",
                    destination=ProjectionExitDestination(
                        scene_id=destination.id,
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
            if not RuleEngineService._is_visible_to_actor(policy):
                continue
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
            return RuleKernel.condition_matches(
                ConditionSpec(expr=policy.discovery_rule),
                runtime.game_state,
                request=synthetic_request,
                target_id=target_id,
            )
        except ContractError:
            # Projection policies fail closed when optional runtime data is absent.
            return False

    @staticmethod
    def _is_visible_to_actor(policy: VisibilityPolicy) -> bool:
        return policy.audience not in {"keeper", "ho"}
