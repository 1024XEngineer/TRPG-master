"""Deterministic player-safe navigation for ModuleContent v3 (#212 section 7)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from collaboration_framework.contracts import (
    AccessBoundary,
    LocationKnowledge,
    ModuleContentV3,
    TargetResolution,
)

from .models import GameState
from .rules_v3 import entity_state, evaluate_condition

_PLAYER_VISIBLE = {"public", "party", "actor"}


@dataclass(frozen=True)
class RouteEdge:
    id: str
    from_location_id: str
    to_location_id: str
    traversal: str
    access_point_id: str | None
    conditions: tuple[object, ...]


def runtime_location_edges(state: GameState) -> tuple[RouteEdge, ...]:
    """Registering a Runtime Location *is* laying its path (#212 §7.3).

    A Runtime Location owns no authored `location_edges`, so its
    `connected_location_id` anchor is the only statement of how the world
    reaches it — and that statement is symmetric: an inn you can walk into from
    the street is an inn you can walk out of onto the street. Deriving both
    directions here, once, is what keeps the knowledge graph, the route graph
    and the projected exits telling the same story. When only the two forward
    halves existed, standing inside the inn left the party on an island: the map
    collapsed to that single node and every canon destination answered
    "当前没有可确认的目标路线".

    Containment stays out of this: `parent_location_id` is a fallback anchor
    only when nothing declared the connection, never a second edge.
    """

    edges: list[RouteEdge] = []
    for location_id, payload in sorted(state.runtime_locations.items()):
        anchor = _text(payload.get("connected_location_id")) or _text(
            payload.get("parent_location_id")
        )
        if anchor is None or anchor == location_id:
            continue
        edges.extend(
            (
                RouteEdge(
                    id=f"runtime:{location_id}",
                    from_location_id=anchor,
                    to_location_id=location_id,
                    traversal="automatic",
                    access_point_id=None,
                    conditions=(),
                ),
                RouteEdge(
                    id=f"runtime:{location_id}:back",
                    from_location_id=location_id,
                    to_location_id=anchor,
                    traversal="automatic",
                    access_point_id=None,
                    conditions=(),
                ),
            )
        )
    return tuple(edges)


def effective_location_knowledge(
    module: ModuleContentV3,
    state: GameState,
    *,
    actor_id: str,
) -> dict[str, LocationKnowledge]:
    """Build the current player graph without exposing unreachable hidden nodes.

    Public locations are discovered transitively from the actor's current location,
    so opening the map in a meeting room still shows the public library beyond the
    street connector. Hidden edges only join that graph after a registered reveal,
    an authored discovery flag, or their authored conditions become true.
    """

    knowledge: dict[str, LocationKnowledge] = {}
    explicit = dict(state.party_location_knowledge)
    explicit.update(state.actor_location_knowledge.get(actor_id, {}))
    known_connections = {
        connection_id
        for item in explicit.values()
        if item.existence != "unknown"
        for connection_id in item.known_connection_ids
    }

    def mark(
        location_id: str,
        *,
        access: str = "reachable",
        visited: bool = False,
        connection_id: str | None = None,
    ) -> None:
        current = knowledge.get(location_id)
        connections = set(current.known_connection_ids if current else ())
        if connection_id is not None:
            connections.add(connection_id)
        current_access = current.access if current else "unknown"
        if access == "reachable" or current_access == "unknown":
            current_access = access
        knowledge[location_id] = LocationKnowledge(
            location_id=location_id,
            scope="party",
            existence="known",
            localization="located",
            access=current_access,
            visited=visited or bool(current and current.visited),
            known_connection_ids=tuple(sorted(connections)),
        )

    runtime_edges = runtime_location_edges(state)
    mark(state.scene_id, visited=True)
    queue = deque([state.scene_id])
    traversed: set[str] = set()
    while queue:
        source_id = queue.popleft()
        if source_id in traversed:
            continue
        traversed.add(source_id)
        for edge in module.location_edges:
            if edge.from_location_id != source_id:
                continue
            if not _location_visible(state, actor_id, edge.to_location_id):
                continue
            if not _edge_is_known(
                module,
                state,
                actor_id=actor_id,
                edge=edge,
                known_connection_ids=known_connections,
            ):
                continue
            traversable = _edge_is_traversable(state, actor_id, edge)
            mark(source_id, connection_id=edge.id)
            mark(
                edge.to_location_id,
                access="reachable" if traversable else "blocked",
                connection_id=edge.id,
            )
            if traversable:
                queue.append(edge.to_location_id)
        # Runtime locations are ordinary public leaves, and their registered
        # path is walked in the same sweep as the authored ones — including
        # outwards, so standing in an Agent-created inn still discovers the
        # street it was hung off and everything the street leads to.
        for edge in runtime_edges:
            if edge.from_location_id != source_id:
                continue
            if not _location_visible(state, actor_id, edge.to_location_id):
                continue
            mark(source_id, connection_id=edge.id)
            mark(edge.to_location_id, connection_id=edge.id)
            queue.append(edge.to_location_id)

    # Containment is presentation, not reachability. Add ancestors only after a
    # child is known; doing this in the other direction would reveal secret rooms.
    locations = {item.id: item for item in module.locations}
    for location_id in tuple(knowledge):
        cursor = locations.get(location_id)
        seen: set[str] = set()
        while cursor is not None and cursor.parent_location_id is not None:
            parent_id = cursor.parent_location_id
            if parent_id in seen:
                break
            seen.add(parent_id)
            if parent_id not in knowledge:
                knowledge[parent_id] = LocationKnowledge(
                    location_id=parent_id,
                    scope="party",
                    existence="known",
                    localization="located",
                )
            cursor = locations.get(parent_id)

    # Explicit state is authoritative and actor scope wins over party scope.
    for location_id, item in state.party_location_knowledge.items():
        knowledge[location_id] = _overlay_knowledge(knowledge.get(location_id), item)
    for location_id, item in state.actor_location_knowledge.get(actor_id, {}).items():
        knowledge[location_id] = _overlay_knowledge(knowledge.get(location_id), item)
    return knowledge


def resolve_location_target(
    module: ModuleContentV3,
    state: GameState,
    *,
    actor_id: str,
    target_id: str,
    ambient_allowed: bool = False,
) -> TargetResolution:
    """Resolve a stable target id without natural-language or hidden-identity matching."""

    canon_ids = {item.id for item in module.locations}
    runtime_ids = set(state.runtime_locations)
    if target_id not in canon_ids | runtime_ids:
        return TargetResolution(
            status="ambient_creatable" if ambient_allowed else "unsupported",
            target_id=target_id,
            safe_reason="该普通地点可以先登记"
            if ambient_allowed
            else "当前没有可用地点",
        )

    knowledge = effective_location_knowledge(module, state, actor_id=actor_id)
    target = knowledge.get(target_id)
    if target is None or target.existence == "unknown":
        return TargetResolution(
            status="hidden_canon_collision"
            if target_id in canon_ids
            else "unsupported",
            target_id=target_id,
            safe_reason="当前没有可确认的目标路线",
        )
    if target.localization != "located":
        return TargetResolution(
            status="known_unlocated",
            target_id=target_id,
            safe_reason="知道这个地点存在，但还不知道准确路线",
        )
    if target_id == state.scene_id:
        return TargetResolution(
            status="known_reachable",
            target_id=target_id,
            path=(state.scene_id,),
            reached_location_id=state.scene_id,
        )

    edges = _known_route_edges(module, state, actor_id=actor_id, knowledge=knowledge)
    path = _find_path(
        edges,
        state.scene_id,
        target_id,
        traversable_only=True,
        state=state,
        actor_id=actor_id,
    )
    if path is not None:
        return TargetResolution(
            status="known_reachable",
            target_id=target_id,
            path=path,
            reached_location_id=target_id,
        )

    structural_path = _find_path(
        edges,
        state.scene_id,
        target_id,
        traversable_only=False,
        state=state,
        actor_id=actor_id,
    )
    if structural_path is not None:
        for source_id, destination_id in zip(structural_path, structural_path[1:]):
            edge = next(
                item
                for item in edges
                if item.from_location_id == source_id
                and item.to_location_id == destination_id
            )
            if _route_edge_is_traversable(state, actor_id, edge):
                continue
            boundary = _boundary(module, state, edge)
            reached_path = structural_path[: structural_path.index(source_id) + 1]
            return TargetResolution(
                status="known_blocked",
                target_id=target_id,
                path=reached_path,
                reached_location_id=source_id,
                boundary=boundary,
                safe_reason="路线在可交互边界处中断",
            )

    return TargetResolution(
        status="known_blocked",
        target_id=target_id,
        path=(state.scene_id,),
        reached_location_id=state.scene_id,
        boundary=AccessBoundary(
            id=f"route:{target_id}",
            label="当前可达路线的前沿",
            state="blocked",
        ),
        safe_reason="当前没有完整可达路线",
    )


def _known_route_edges(
    module: ModuleContentV3,
    state: GameState,
    *,
    actor_id: str,
    knowledge: dict[str, LocationKnowledge],
) -> tuple[RouteEdge, ...]:
    known_connections = {
        connection_id
        for item in knowledge.values()
        for connection_id in item.known_connection_ids
    }
    edges = [
        RouteEdge(
            id=edge.id,
            from_location_id=edge.from_location_id,
            to_location_id=edge.to_location_id,
            traversal=edge.traversal,
            access_point_id=edge.access_point_id,
            conditions=tuple(edge.conditions),
        )
        for edge in module.location_edges
        if edge.from_location_id in knowledge
        and edge.to_location_id in knowledge
        and _edge_is_known(
            module,
            state,
            actor_id=actor_id,
            edge=edge,
            known_connection_ids=known_connections,
        )
    ]
    edges.extend(
        edge
        for edge in runtime_location_edges(state)
        if edge.from_location_id in knowledge and edge.to_location_id in knowledge
    )
    return tuple(edges)


def _find_path(
    edges: tuple[RouteEdge, ...],
    start: str,
    target: str,
    *,
    traversable_only: bool,
    state: GameState,
    actor_id: str,
) -> tuple[str, ...] | None:
    queue = deque([(start, (start,))])
    visited = {start}
    while queue:
        current, path = queue.popleft()
        for edge in sorted(edges, key=lambda item: item.id):
            if edge.from_location_id != current:
                continue
            if traversable_only and not _route_edge_is_traversable(
                state, actor_id, edge
            ):
                continue
            destination = edge.to_location_id
            if destination == target:
                return (*path, destination)
            if destination in visited:
                continue
            visited.add(destination)
            queue.append((destination, (*path, destination)))
    return None


def _edge_is_known(
    module: ModuleContentV3,
    state: GameState,
    *,
    actor_id: str,
    edge,
    known_connection_ids: set[str],
) -> bool:
    if edge.visibility in _PLAYER_VISIBLE:
        return True
    if edge.id in known_connection_ids:
        return True
    if _visibility_override(state, actor_id, "location", edge.to_location_id) is True:
        return True
    if edge.access_point_id is not None:
        access_state = entity_state(state, edge.access_point_id)
        if access_state.get("discovered") is True:
            return True
    return bool(edge.conditions) and all(
        evaluate_condition(condition, state=state, actor_id=actor_id)
        for condition in edge.conditions
    )


def _edge_is_traversable(state: GameState, actor_id: str, edge) -> bool:
    route = RouteEdge(
        id=edge.id,
        from_location_id=edge.from_location_id,
        to_location_id=edge.to_location_id,
        traversal=edge.traversal,
        access_point_id=edge.access_point_id,
        conditions=tuple(edge.conditions),
    )
    return _route_edge_is_traversable(state, actor_id, route)


def _route_edge_is_traversable(
    state: GameState,
    actor_id: str,
    edge: RouteEdge,
) -> bool:
    if not all(
        evaluate_condition(condition, state=state, actor_id=actor_id)
        for condition in edge.conditions
    ):
        return False
    if edge.traversal == "guided":
        return False
    if edge.traversal != "gated" or edge.conditions:
        return True
    if edge.access_point_id is None:
        return False
    access_state = entity_state(state, edge.access_point_id)
    return access_state.get("unlocked") is True or access_state.get("open") is True


def _boundary(
    module: ModuleContentV3,
    state: GameState,
    edge: RouteEdge,
) -> AccessBoundary:
    entity = next(
        (item for item in module.entities if item.id == edge.access_point_id),
        None,
    )
    label = (
        (entity.player_visible_name or entity.name) if entity is not None else "通路前"
    )
    access_state = entity_state(state, edge.access_point_id or "")
    if edge.traversal == "guided":
        boundary_state = "interaction_required"
    elif access_state.get("locked") is True or edge.conditions:
        boundary_state = "locked"
    else:
        boundary_state = "blocked"
    return AccessBoundary(
        id=edge.access_point_id or edge.id,
        label=label,
        state=boundary_state,
    )


def _location_visible(state: GameState, actor_id: str, location_id: str) -> bool:
    return _visibility_override(state, actor_id, "location", location_id) is not False


def _visibility_override(
    state: GameState,
    actor_id: str,
    target_kind: str,
    target_id: str,
) -> bool | None:
    actor_key = f"actor:{actor_id}:{target_kind}:{target_id}"
    if actor_key in state.visibility_overrides:
        return state.visibility_overrides[actor_key]
    return state.visibility_overrides.get(f"party:{target_kind}:{target_id}")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _overlay_knowledge(
    inferred: LocationKnowledge | None,
    explicit: LocationKnowledge,
) -> LocationKnowledge:
    if explicit.existence == "unknown" or inferred is None:
        return explicit
    return LocationKnowledge(
        location_id=explicit.location_id,
        scope=explicit.scope,
        existence=explicit.existence,
        localization=(
            explicit.localization
            if explicit.localization != "unknown"
            else inferred.localization
        ),
        access=explicit.access if explicit.access != "unknown" else inferred.access,
        visited=explicit.visited or inferred.visited,
        known_connection_ids=tuple(
            sorted(
                set(inferred.known_connection_ids) | set(explicit.known_connection_ids)
            )
        ),
    )


__all__ = ["effective_location_knowledge", "resolve_location_target"]
