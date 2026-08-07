"""Player-safe projection over ModuleContent v3 (#212 §7, §4, §8).

The v2 projection walked `Scene.entity_ids` and `Scene.exits`, which is why it
could only ever answer "what is in this room" and "what other rooms exist". v3
splits those apart:

* **hierarchy** — `parent_location_id`, projected as a breadcrumb, so the UI can
  say 阿诺兹堡 - 金博尔宅 - 书房 without that implying reachability;
* **navigation** — `location_edges`, which is what actually decides where the
  actor may go, and which can stop at an `access_point_id` boundary instead of
  either succeeding or failing outright;
* **placement** — an Entity declares `located_in`, so an entity moved by
  `move_entity` is projected wherever it now is rather than wherever the module
  originally listed it.

`GameState.scene_id` keeps its name during the migration but holds a v3 location
id; renaming the field is a storage change and belongs with the loader switch.
"""

from __future__ import annotations

from collaboration_framework.contracts import (
    AgentMatchTriggerSpec,
    ContractError,
    KeeperCapabilityView,
    KeeperEndingCapability,
    KeeperEntityCapability,
    KeeperInformationCapability,
    KeeperLocationCapability,
    KeeperRuleCandidate,
    KeeperRuleOption,
    LocationSpecV3,
    ModuleContentV3,
    ProjectionActorResource,
    ProjectionActorValue,
    ProjectionAvailableExit,
    ProjectionEntity,
    ProjectionExitDestination,
    ProjectionKnownInformation,
    ProjectionScene,
    ProjectionSelfActor,
    ProjectionSnapshot,
    ProjectionVisibleActor,
    ProjectionWorldState,
)

from .models import EngineRuntimeSnapshot, GameState

# Visibility levels an authored node may carry, ordered from most to least open.
_PLAYER_VISIBLE = {"public", "party"}


def project_v3(
    runtime: EngineRuntimeSnapshot,
    *,
    player_id: str,
    actor_id: str,
) -> ProjectionSnapshot:
    module = runtime.v3
    state = runtime.game_state
    location = _current_location(module, state)
    actor = state.actors[actor_id]

    visible_entities = _visible_entities(module, state, location.id, actor_id)
    return ProjectionSnapshot(
        room_id=state.room_id,
        player_id=player_id,
        actor_id=actor_id,
        background=module.background,
        scene_id=location.id,
        phase=state.phase,
        revision=runtime.revision,
        self_actor=_self_actor(actor_id, actor),
        scene=ProjectionScene(
            id=location.id,
            name=location.player_visible_name or location.name,
            description=location.player_visible_description,
            time=state.clock.time_of_day,
            visible_entities=visible_entities,
            visible_actors=tuple(
                ProjectionVisibleActor(
                    id=other_id,
                    name=other.name,
                    occupation=_optional_text(other.state.get("occupation")),
                    status_summary=_public_status_summary(other.state),
                )
                for other_id, other in state.actors.items()
                if other_id != actor_id
            ),
            available_exits=_available_exits(module, state, location.id, actor_id),
        ),
        world=ProjectionWorldState(
            elapsed_minutes=state.clock.elapsed_minutes,
            time_of_day=state.clock.time_of_day,
            core_resolved=state.core_resolved,
            ending_available=state.ending_available,
            ending_id=state.ending_id,
        ),
        known_information=_known_information(module, state, actor_id),
        # v3 has no Checkpoints: the candidate menu is produced per-action by an
        # `agent_match` Rule, not published with the scene (#226 §2).
        checkpoint_options=(),
    )


def _current_location(module: ModuleContentV3, state: GameState) -> LocationSpecV3:
    for location in module.locations:
        if location.id == state.scene_id:
            return location
    runtime_location = state.runtime_locations.get(state.scene_id)
    if runtime_location is None:
        raise ContractError(f"当前 Location 不存在: {state.scene_id}")
    name = _optional_text(runtime_location.get("name")) or state.scene_id
    return LocationSpecV3(
        id=state.scene_id,
        kind="room",
        origin="canon",
        name=name,
        player_visible_name=name,
        parent_location_id=_optional_text(runtime_location.get("parent_location_id")),
        lifecycle="session",
    )


def location_breadcrumbs(
    module: ModuleContentV3,
    location_id: str,
) -> tuple[tuple[str, str], ...]:
    """Ancestors first, ending with the location itself (#212 §7.3).

    Containment only — never the navigation graph. A player standing in the
    study is "阿诺兹堡 - 金博尔宅 - 书房" regardless of how they got there.
    """

    by_id = {location.id: location for location in module.locations}
    trail: list[tuple[str, str]] = []
    seen: set[str] = set()
    cursor: str | None = location_id
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        location = by_id.get(cursor)
        if location is None:
            break
        trail.append((location.id, location.player_visible_name or location.name))
        cursor = location.parent_location_id
    return tuple(reversed(trail))


def _visible_entities(
    module: ModuleContentV3,
    state: GameState,
    location_id: str,
    actor_id: str,
) -> tuple[ProjectionEntity, ...]:
    """Everything currently here, Canon or Agent-created, minus what is hidden."""

    projected: list[ProjectionEntity] = []
    for entity in module.entities:
        overrides = state.entities.get(entity.id, {})
        placed = _optional_text(overrides.get("location_id")) or entity.located_in
        carried = _optional_text(overrides.get("holder_actor_id"))
        if overrides.get("consumed") is True:
            continue
        if placed != location_id and carried != actor_id:
            continue
        if entity.visibility not in _PLAYER_VISIBLE:
            continue
        if not _override_allows(state, actor_id, "entity", entity.id):
            continue
        projected.append(
            ProjectionEntity(
                id=entity.id,
                kind=entity.kind,
                name=entity.player_visible_name or entity.name,
                aliases=entity.player_visible_aliases,
                description=entity.description,
            )
        )
    for entity_id, payload in sorted(state.runtime_entities.items()):
        if payload.get("consumed") is True:
            continue
        placed = _optional_text(payload.get("location_id"))
        carried = _optional_text(payload.get("holder_actor_id"))
        if placed != location_id and carried != actor_id:
            continue
        if not _override_allows(state, actor_id, "entity", entity_id):
            continue
        kind = payload.get("kind")
        projected.append(
            ProjectionEntity(
                id=entity_id,
                kind=kind if kind in {"npc", "object", "location"} else "object",
                name=_optional_text(payload.get("name")) or entity_id,
                description="",
            )
        )
    projected.sort(key=lambda item: item.id)
    return tuple(projected)


def _available_exits(
    module: ModuleContentV3,
    state: GameState,
    location_id: str,
    actor_id: str,
) -> tuple[ProjectionAvailableExit, ...]:
    """Outgoing edges the player may both see and use.

    A hidden edge stays out of the view until something reveals it; a gated edge
    is shown with its `access_point_id` so the player knows there is a door,
    which is the whole point of modelling the boundary.
    """

    by_id = {location.id: location for location in module.locations}
    exits: list[ProjectionAvailableExit] = []
    for edge in module.location_edges:
        if edge.from_location_id != location_id:
            continue
        if edge.visibility not in _PLAYER_VISIBLE and not _override_allows(
            state, actor_id, "location", edge.to_location_id, default=False
        ):
            continue
        if not _override_allows(state, actor_id, "location", edge.to_location_id):
            continue
        destination = by_id.get(edge.to_location_id)
        runtime_destination = state.runtime_locations.get(edge.to_location_id)
        if destination is not None:
            name = destination.player_visible_name or destination.name
        elif runtime_destination is not None:
            name = _optional_text(runtime_destination.get("name")) or edge.to_location_id
        else:
            continue
        exits.append(
            ProjectionAvailableExit(
                id=edge.id,
                name=name,
                target_id=edge.access_point_id,
                description="",
                destination=ProjectionExitDestination(
                    scene_id=edge.to_location_id,
                    name=name,
                ),
            )
        )
    # Standing inside an Agent-created location, the way back has to be projected
    # explicitly: it is not an authored edge, and the loop below only walks from a
    # location to the runtime locations attached to it — never the other way. Without
    # this a runtime location is a one-way trip.
    here = state.runtime_locations.get(location_id)
    if here is not None:
        back_id = _optional_text(here.get("connected_location_id")) or _optional_text(
            here.get("parent_location_id")
        )
        if back_id is not None and back_id != location_id:
            back_canon = by_id.get(back_id)
            back_runtime = state.runtime_locations.get(back_id)
            back_name: str | None = None
            if back_canon is not None:
                back_name = back_canon.player_visible_name or back_canon.name
            elif back_runtime is not None:
                back_name = _optional_text(back_runtime.get("name")) or back_id
            if back_name is not None and _override_allows(
                state, actor_id, "location", back_id
            ):
                exits.append(
                    ProjectionAvailableExit(
                        id=f"runtime:{location_id}:back",
                        name=back_name,
                        description="",
                        destination=ProjectionExitDestination(
                            scene_id=back_id,
                            name=back_name,
                        ),
                    )
                )

    # Agent-created locations attach to whatever they were connected to.
    for runtime_id, payload in sorted(state.runtime_locations.items()):
        if runtime_id == location_id:
            continue
        if location_id not in {
            payload.get("connected_location_id"),
            payload.get("parent_location_id"),
        }:
            continue
        if any(item.destination and item.destination.scene_id == runtime_id for item in exits):
            continue
        name = _optional_text(payload.get("name")) or runtime_id
        exits.append(
            ProjectionAvailableExit(
                id=f"runtime:{runtime_id}",
                name=name,
                description="",
                destination=ProjectionExitDestination(scene_id=runtime_id, name=name),
            )
        )
    return tuple(exits)


def _known_information(
    module: ModuleContentV3,
    state: GameState,
    actor_id: str,
) -> tuple[ProjectionKnownInformation, ...]:
    """Only released facts, and only the player-facing half of them."""

    party = set(state.discovered_facts)
    mine = set(state.actor_discovered_facts.get(actor_id, ()))
    projected: list[ProjectionKnownInformation] = []
    for item in module.information:
        if not _override_allows(state, actor_id, "information", item.id):
            continue
        if item.discovery.initial == "known":
            scope = item.discovery.scope
        elif item.id in party:
            scope = "party"
        elif item.id in mine:
            scope = "actor"
        else:
            continue
        if not item.audience.player_when_discovered:
            continue
        projected.append(
            ProjectionKnownInformation(
                id=item.id,
                title=item.title,
                # keeper_content deliberately never reaches this side.
                summary=item.player_content,
                content=item.player_content,
                related_entities=(),
                related_scenes=(),
                scope=scope,
            )
        )
    return tuple(projected)


def _override_allows(
    state: GameState,
    actor_id: str,
    target_kind: str,
    target_id: str,
    *,
    default: bool = True,
) -> bool:
    actor_key = f"actor:{actor_id}:{target_kind}:{target_id}"
    if actor_key in state.visibility_overrides:
        return state.visibility_overrides[actor_key]
    return state.visibility_overrides.get(f"party:{target_kind}:{target_id}", default)


def _self_actor(actor_id: str, actor) -> ProjectionSelfActor:
    actor_state = actor.state
    return ProjectionSelfActor(
        id=actor_id,
        name=actor.name,
        occupation=_optional_text(actor_state.get("occupation")),
        attributes=_actor_values(actor_state.get("attributes"), actor_state.get("attribute_labels")),
        skills=_actor_values(actor_state.get("skills"), actor_state.get("skill_labels")),
        resources=tuple(
            ProjectionActorResource(id=key, name=key.upper(), value=value)
            for key, value in actor.resources.model_dump(mode="python").items()
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        conditions=tuple(item for item in actor.conditions if isinstance(item, str) and item.strip()),
        equipment=_equipment(actor_state.get("equipment")),
        background_summary=_optional_text(actor_state.get("background")) or "",
        public_status_summary=_public_status_summary(actor_state),
    )


def _actor_values(values, labels) -> tuple[ProjectionActorValue, ...]:
    if not isinstance(values, dict):
        return ()
    label_map = labels if isinstance(labels, dict) else {}
    projected = []
    for key, value in values.items():
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        label = label_map.get(key)
        projected.append(
            ProjectionActorValue(
                id=key,
                name=label if isinstance(label, str) and label.strip() else key,
                value=value,
            )
        )
    return tuple(projected)


def _equipment(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
    return tuple(names)


def _public_status_summary(actor_state) -> str:
    summary = actor_state.get("public_status_summary") if isinstance(actor_state, dict) else None
    return summary if isinstance(summary, str) else ""


def _optional_text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _rule_candidates(module, location_id: str) -> tuple[KeeperRuleCandidate, ...]:
    """agent_match Rules whose scope covers where the actor is standing.

    Scope filtering is the Engine's job so the Agent never sees rules for places
    it is not in; picking among the remaining options is the Agent's job. An
    empty `location_ids` means the rule is not location-bound.
    """

    candidates = []
    for rule in module.rules:
        trigger = rule.trigger
        if not isinstance(trigger, AgentMatchTriggerSpec):
            continue
        scope = trigger.scope
        if scope.location_ids and location_id not in scope.location_ids:
            continue
        candidates.append(
            KeeperRuleCandidate(
                rule_id=rule.id,
                question_kind=trigger.question.kind,
                semantic_hints=trigger.question.semantic_hints,
                action_families=scope.action_families,
                target_kinds=scope.target_kinds,
                target_ids=scope.target_ids,
                options=tuple(
                    KeeperRuleOption(id=option.id, semantic_hints=option.semantic_hints)
                    for option in trigger.options
                ),
            )
        )
    candidates.sort(key=lambda item: item.rule_id)
    return tuple(candidates)


def keeper_capabilities_v3(
    runtime: EngineRuntimeSnapshot,
    *,
    actor_id: str,
) -> KeeperCapabilityView:
    """The controlled Canon vocabulary, read off v3 collections (#212 §3.2).

    Same boundary as the v2 arm: this is what lets the Agent name an Information
    the player has not discovered yet, and the Engine still re-validates every id
    at submit time.
    """

    module = runtime.v3
    state = runtime.game_state
    party_known = set(state.discovered_facts)
    actor_known = set(state.actor_discovered_facts.get(actor_id, ()))
    return KeeperCapabilityView(
        room_id=state.room_id,
        actor_id=actor_id,
        revision=runtime.revision,
        information=tuple(
            KeeperInformationCapability(
                id=item.id,
                title=item.title,
                summary=item.player_content,
                content=item.keeper_content,
                known_by_party=item.id in party_known,
                known_by_actor=item.id in actor_known,
            )
            for item in module.information
        ),
        locations=tuple(
            KeeperLocationCapability(
                id=location.id,
                name=location.player_visible_name or location.name,
                origin="canon",
                is_current=location.id == state.scene_id,
            )
            for location in module.locations
        )
        + tuple(
            KeeperLocationCapability(
                id=location_id,
                name=_optional_text(payload.get("name")) or location_id,
                origin="runtime",
                is_current=location_id == state.scene_id,
            )
            for location_id, payload in sorted(state.runtime_locations.items())
        ),
        entities=tuple(
            KeeperEntityCapability(
                id=entity.id,
                name=entity.player_visible_name or entity.name,
                kind=entity.kind,
                origin="canon",
                location_id=_optional_text(
                    state.entities.get(entity.id, {}).get("location_id")
                )
                or entity.located_in,
                holder_actor_id=_optional_text(
                    state.entities.get(entity.id, {}).get("holder_actor_id")
                ),
                consumed=state.entities.get(entity.id, {}).get("consumed") is True,
            )
            for entity in module.entities
        )
        + tuple(
            KeeperEntityCapability(
                id=entity_id,
                name=_optional_text(payload.get("name")) or entity_id,
                kind=(
                    payload["kind"]
                    if payload.get("kind") in {"npc", "object", "location"}
                    else "object"
                ),
                origin="runtime",
                location_id=_optional_text(payload.get("location_id")),
                holder_actor_id=_optional_text(payload.get("holder_actor_id")),
                consumed=payload.get("consumed") is True,
            )
            for entity_id, payload in sorted(state.runtime_entities.items())
        ),
        endings=tuple(
            KeeperEndingCapability(
                id=anchor.id,
                summary=anchor.tone or anchor.id,
            )
            for anchor in module.ending_anchors
        ),
        rule_candidates=_rule_candidates(module, state.scene_id),
        core_resolved=state.core_resolved,
        ending_available=state.ending_available,
    )


__all__ = ["keeper_capabilities_v3", "location_breadcrumbs", "project_v3"]
