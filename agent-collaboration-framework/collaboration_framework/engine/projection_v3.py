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
    EntitySpecV3,
    KeeperCapabilityView,
    KeeperEndingCapability,
    KeeperEntityCapability,
    KeeperInformationCapability,
    KeeperLocationCapability,
    KeeperRuleCandidate,
    KeeperRuleOption,
    KeeperTimeCapability,
    InventoryItemView,
    ItemInstance,
    LocationKnowledge,
    LocationSpecV3,
    ModuleContentV3,
    ProjectionActorResource,
    ProjectionActorValue,
    ProjectionAvailableExit,
    ProjectionEntity,
    ProjectionExitDestination,
    ProjectionKnownInformation,
    ProjectionKnownLocation,
    ProjectionLocationBreadcrumb,
    ProjectionLocationContext,
    ProjectionObservableState,
    ProjectionPositionContext,
    ProjectionScene,
    ProjectionSelfActor,
    ProjectionSnapshot,
    ProjectionVisibleActor,
    ProjectionWorldState,
)

from .models import EngineRuntimeSnapshot, GameState
from .navigation import effective_location_knowledge, runtime_location_edges
from .persistent_results import PUBLIC_STATE_KEYS
from .timeline import next_point_after, ordered_points, time_advance_block_reason
from .rules_v3 import agent_match_scope_admits, evaluate_condition, pending_check_for

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
    location_knowledge = effective_location_knowledge(
        module,
        state,
        actor_id=actor_id,
    )
    inventory, loose_items = project_inventory_items(
        state,
        actor_id=actor_id,
        location_id=location.id,
        module=module,
    )

    visible_entities = _visible_entities(module, state, location.id, actor_id)
    return ProjectionSnapshot(
        room_id=state.room_id,
        player_id=player_id,
        actor_id=actor_id,
        background=module.background,
        scene_id=location.id,
        phase=state.phase,
        revision=runtime.revision,
        self_actor=_self_actor(actor_id, actor, inventory),
        scene=ProjectionScene(
            id=location.id,
            name=location.player_visible_name or location.name,
            description=location.player_visible_description,
            time=state.world_time.time_of_day,
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
            available_exits=_available_exits(
                module,
                state,
                location.id,
                actor_id,
                location_knowledge,
            ),
            loose_items=loose_items,
        ),
        location_context=_location_context(module, state, actor_id),
        known_locations=_known_locations(module, state, location_knowledge),
        inventory=inventory,
        world=ProjectionWorldState(
            day_index=state.world_time.current.day_index,
            hour_of_day=state.world_time.current.hour_of_day,
            time_of_day=state.world_time.time_of_day,
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


def _runtime_containment_parent(
    module: ModuleContentV3,
    payload: dict,
) -> str | None:
    """Where a Runtime Location *sits*, which is not where it *connects*.

    Containment and reachability are separate graphs (#212 §7.3). Falling back
    to `connected_location_id` conflates them: an inn reached from the study
    door would be drawn inside 金博尔宅. The anchor still tells us the right
    answer indirectly — the inn belongs to the anchor's region, so resolve that
    instead and leave it at the region root when there is none.
    """

    explicit = _optional_text(payload.get("parent_location_id"))
    if explicit is not None:
        return explicit
    anchor_id = _optional_text(payload.get("connected_location_id"))
    if anchor_id is None:
        return None
    by_id = {location.id: location for location in module.locations}
    anchor = by_id.get(anchor_id)
    if anchor is None:
        return None
    if anchor.kind == "region":
        return anchor.id
    if anchor.region_id is not None and anchor.region_id in by_id:
        return anchor.region_id
    # No declared region: walk containment up to the outermost known ancestor.
    cursor = anchor
    seen: set[str] = {cursor.id}
    while cursor.parent_location_id is not None:
        parent = by_id.get(cursor.parent_location_id)
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        cursor = parent
    return cursor.id if cursor.id != anchor.id else None


def _location_context(
    module: ModuleContentV3,
    state: GameState,
    actor_id: str,
) -> ProjectionLocationContext:
    trail = location_breadcrumbs(module, state.scene_id)
    if not trail and state.scene_id in state.runtime_locations:
        runtime = state.runtime_locations[state.scene_id]
        parent_id = _runtime_containment_parent(module, runtime)
        parent_trail = location_breadcrumbs(module, parent_id) if parent_id else ()
        trail = (
            *parent_trail,
            (
                state.scene_id,
                _optional_text(runtime.get("name")) or state.scene_id,
            ),
        )
    interrupted = state.actor_position_contexts.get(actor_id)
    return ProjectionLocationContext(
        current_location_id=state.scene_id,
        breadcrumbs=tuple(
            ProjectionLocationBreadcrumb(id=location_id, name=name)
            for location_id, name in trail
        ),
        position_context=(
            ProjectionPositionContext(
                id=interrupted.reached_boundary.id,
                label=interrupted.reached_boundary.label,
                state=interrupted.reached_boundary.state,
                destination_id=interrupted.destination_id,
            )
            if interrupted is not None
            else None
        ),
    )


def _known_locations(
    module: ModuleContentV3,
    state: GameState,
    knowledge: dict[str, LocationKnowledge],
) -> tuple[ProjectionKnownLocation, ...]:
    projected: list[ProjectionKnownLocation] = []
    for location in module.locations:
        known = knowledge.get(location.id)
        if known is None or known.existence == "unknown":
            continue
        projected.append(
            ProjectionKnownLocation(
                id=location.id,
                kind=location.kind,
                name=location.player_visible_name or location.name,
                description=location.player_visible_description,
                parent_location_id=location.parent_location_id,
                region_id=location.region_id,
                existence=known.existence,
                localization=known.localization,
                access=known.access,
                visited=known.visited,
            )
        )
    for location_id, payload in sorted(state.runtime_locations.items()):
        known = knowledge.get(location_id)
        if known is None or known.existence == "unknown":
            continue
        projected.append(
            ProjectionKnownLocation(
                id=location_id,
                kind="room",
                name=_optional_text(payload.get("name")) or location_id,
                parent_location_id=_runtime_containment_parent(module, payload),
                existence=known.existence,
                localization=known.localization,
                access=known.access,
                visited=known.visited,
            )
        )
    return tuple(projected)


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
        if not all(
            evaluate_condition(condition, state=state, actor_id=actor_id)
            for condition in entity.visibility_conditions
        ):
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
                observable_state=_public_entity_state(state, entity.id, overrides),
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
                observable_state=_public_entity_state(state, entity_id, payload),
            )
        )
    projected.sort(key=lambda item: item.id)
    return tuple(projected)


def _public_entity_state(
    state: GameState,
    entity_id: str,
    values: dict[str, object],
) -> tuple[ProjectionObservableState, ...]:
    """只投影由公开标准效果登记过的状态键，避免把模组隐藏状态带给模型。"""

    keys = state.public_entity_state_keys.get(entity_id, ())
    return tuple(
        ProjectionObservableState(key=key, label=key, value=values[key])
        for key in keys
        if key in PUBLIC_STATE_KEYS and key in values
    )


def _available_exits(
    module: ModuleContentV3,
    state: GameState,
    location_id: str,
    actor_id: str,
    location_knowledge: dict[str, LocationKnowledge],
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
        known_destination = location_knowledge.get(edge.to_location_id)
        if known_destination is None or known_destination.existence == "unknown":
            continue
        destination = by_id.get(edge.to_location_id)
        runtime_destination = state.runtime_locations.get(edge.to_location_id)
        if destination is not None:
            name = destination.player_visible_name or destination.name
        elif runtime_destination is not None:
            name = (
                _optional_text(runtime_destination.get("name")) or edge.to_location_id
            )
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
    # A Runtime Location's registered path is a two-way street, and it is the
    # same pair of edges navigation resolves routes over — projecting them from
    # one source is what keeps a shown exit from being one the Engine refuses.
    for edge in runtime_location_edges(state):
        if edge.from_location_id != location_id:
            continue
        destination_id = edge.to_location_id
        canon = by_id.get(destination_id)
        runtime = state.runtime_locations.get(destination_id)
        if canon is not None:
            name = canon.player_visible_name or canon.name
        elif runtime is not None:
            name = _optional_text(runtime.get("name")) or destination_id
        else:
            continue
        if not _override_allows(state, actor_id, "location", destination_id):
            continue
        if any(
            item.destination and item.destination.scene_id == destination_id
            for item in exits
        ):
            continue
        exits.append(
            ProjectionAvailableExit(
                id=edge.id,
                name=name,
                description="",
                destination=ProjectionExitDestination(
                    scene_id=destination_id,
                    name=name,
                ),
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


def project_inventory_items(
    state: GameState,
    *,
    actor_id: str,
    location_id: str,
    module: ModuleContentV3 | None = None,
) -> tuple[tuple[InventoryItemView, ...], tuple[InventoryItemView, ...]]:
    """Project recognized active items without leaking keeper-only fields.

    A Canon item is still a Canon Entity, so it stays behind the same visibility
    gate `_visible_entities` applies. Without `module` the gate cannot be
    evaluated and only Runtime items are safe to project — seeded Canon items
    would otherwise appear in a scene before their `visibility_conditions`
    (say, a diary's `found` flag) ever became true.
    """

    canon_entities = (
        {entity.id: entity for entity in module.entities} if module is not None else {}
    )
    party = state.party_item_knowledge
    actor = state.actor_item_knowledge.get(actor_id, {})
    inventory: list[InventoryItemView] = []
    loose_items: list[InventoryItemView] = []
    for item_id, item in sorted(state.item_instances.items()):
        knowledge = actor.get(item_id) or party.get(item_id)
        if knowledge is None or knowledge.identity == "unknown":
            continue
        if item.state.status != "active":
            continue
        if item.origin == "canon" and not _canon_item_is_visible(
            canon_entities.get(item_id),
            state=state,
            actor_id=actor_id,
        ):
            continue
        view = InventoryItemView(
            id=item.id,
            name=item.display.name,
            source_label=(
                item.acquisition.player_safe_label
                if item.acquisition is not None
                else ""
            ),
            quantity=item.item_component.quantity,
            condition=item.state.condition,
            version=item.version,
        )
        if item.custody.kind == "actor_inventory" and item.custody.ref_id == actor_id:
            inventory.append(view)
        elif item.custody.kind == "location" and item.custody.ref_id == location_id:
            loose_items.append(view)
    return tuple(inventory), tuple(loose_items)


def _canon_item_is_visible(
    entity: EntitySpecV3 | None,
    *,
    state: GameState,
    actor_id: str,
) -> bool:
    """Mirror the Entity gate in `_visible_entities` for a Canon-origin item."""

    if entity is None:
        # A Canon-origin item with no Entity behind it cannot be gated, and an
        # ungatable plot object is exactly what must not reach the player.
        return False
    if entity.visibility not in _PLAYER_VISIBLE:
        return False
    if not all(
        evaluate_condition(condition, state=state, actor_id=actor_id)
        for condition in entity.visibility_conditions
    ):
        return False
    return _override_allows(state, actor_id, "entity", entity.id)


def _item_location_id(item: ItemInstance | None) -> str | None:
    if item is None or item.custody.kind != "location":
        return None
    return item.custody.ref_id


def _item_holder_actor_id(item: ItemInstance | None) -> str | None:
    if item is None or item.custody.kind != "actor_inventory":
        return None
    return item.custody.ref_id


def _self_actor(
    actor_id: str,
    actor,
    inventory: tuple[InventoryItemView, ...],
) -> ProjectionSelfActor:
    actor_state = actor.state
    return ProjectionSelfActor(
        id=actor_id,
        name=actor.name,
        occupation=_optional_text(actor_state.get("occupation")),
        attributes=_actor_values(
            actor_state.get("attributes"), actor_state.get("attribute_labels")
        ),
        skills=_actor_values(
            actor_state.get("skills"), actor_state.get("skill_labels")
        ),
        resources=tuple(
            ProjectionActorResource(id=key, name=key.upper(), value=value)
            for key, value in actor.resources.model_dump(mode="python").items()
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        conditions=tuple(
            item for item in actor.conditions if isinstance(item, str) and item.strip()
        ),
        # Once ItemInstances exist they are the only runtime inventory authority.
        # Legacy v2 character equipment remains a read fallback for old rooms.
        equipment=(
            tuple(item.name for item in inventory)
            if inventory
            else _equipment(actor_state.get("equipment"))
        ),
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
    summary = (
        actor_state.get("public_status_summary")
        if isinstance(actor_state, dict)
        else None
    )
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
        # 同一个谓词也用在提交侧，两边不会各自漂移。
        if not agent_match_scope_admits(rule, location_id=location_id):
            continue
        scope = trigger.scope
        candidates.append(
            KeeperRuleCandidate(
                rule_id=rule.id,
                question_kind=trigger.question.kind,
                semantic_hints=trigger.question.semantic_hints,
                action_families=scope.action_families,
                target_kinds=scope.target_kinds,
                target_ids=scope.target_ids,
                options=tuple(
                    KeeperRuleOption(
                        id=option.id,
                        semantic_hints=option.semantic_hints,
                        # 分支里有没有检定步，是 Agent 必须知道的；后果仍然不出服务端。
                        requires_check=pending_check_for(rule, option.id)[0] is not None,
                    )
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
    canon_entity_ids = {entity.id for entity in module.entities}
    party_known = set(state.discovered_facts)
    actor_known = set(state.actor_discovered_facts.get(actor_id, ()))
    return KeeperCapabilityView(
        room_id=state.room_id,
        actor_id=actor_id,
        revision=runtime.revision,
        world_id=module.world_ref,
        world_profile=module.world_profile,
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
                location_id=_item_location_id(state.item_instances.get(entity.id))
                or _optional_text(state.entities.get(entity.id, {}).get("location_id"))
                or entity.located_in,
                holder_actor_id=_item_holder_actor_id(
                    state.item_instances.get(entity.id)
                )
                or _optional_text(
                    state.entities.get(entity.id, {}).get("holder_actor_id")
                ),
                consumed=(
                    state.item_instances[entity.id].state.status == "retired"
                    if entity.id in state.item_instances
                    else state.entities.get(entity.id, {}).get("consumed") is True
                ),
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
        )
        + tuple(
            KeeperEntityCapability(
                id=item_id,
                name=item.display.name,
                kind="object",
                origin="runtime",
                location_id=_item_location_id(item),
                holder_actor_id=_item_holder_actor_id(item),
                consumed=item.state.status == "retired",
            )
            for item_id, item in sorted(state.item_instances.items())
            if item_id not in canon_entity_ids and item_id not in state.runtime_entities
        ),
        endings=tuple(
            KeeperEndingCapability(
                id=anchor.id,
                summary=anchor.tone or anchor.id,
            )
            for anchor in module.ending_anchors
        ),
        rule_candidates=_rule_candidates(module, state.scene_id),
        time=_time_capability(module, state),
        core_resolved=state.core_resolved,
        ending_available=state.ending_available,
    )


def _time_capability(
    module: ModuleContentV3,
    state: GameState,
) -> KeeperTimeCapability:
    blocked = time_advance_block_reason(tuple(state.actors))
    try:
        next_point, _ = next_point_after(module, state.world_time)
        next_point_id = next_point.id
    except ContractError:
        # The room is parked on a point this module version no longer declares.
        # Reporting "no next point" beats guessing one.
        next_point_id = None
        blocked = blocked or "time_next_point_not_found: 当前时间点不在模组时间线上"
    return KeeperTimeCapability(
        current_point_id=state.world_time.current_point_id,
        current_hour_of_day=state.world_time.current.hour_of_day,
        current_day_index=state.world_time.current.day_index,
        next_point_id=next_point_id,
        ordered_point_ids=tuple(point.id for point in ordered_points(module)),
        blocked_reason=blocked,
    )


__all__ = ["keeper_capabilities_v3", "location_breadcrumbs", "project_v3"]
