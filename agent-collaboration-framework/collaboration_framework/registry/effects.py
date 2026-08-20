"""Effect registry (#347 Phase 2): the closed set of `ActionEffect` types the
Engine understands, and everything it knows about each one.

Before this table existed, the four things the Engine knows about an effect
were four unrelated `isinstance` chains scattered across ~620 lines of
`engine/adjudication.py`: `_classify_effects` (what authority does proposing
this take), `_validate_effect` (is it well-formed against the current
vocabulary), `_apply_effect` (how does it change state), and — implicitly,
by omission — which of its fields name something that must already exist.
Adding an effect type meant editing all four and there was no mechanism that
noticed if you missed one.

Each entry here answers all four at once, so adding an effect type is one
registration and a missing piece is a structural gap rather than a silent
runtime no-op:

- `authority` — the AuthorityLevel proposing it takes (internal diagnostics
  only; see `contracts/validation.py`). Rule-owned effects deliberately never
  reach this: only Agent-proposed effects are classified.
- `reads` / `writes` / `must_not_exist` — the ECS-style access declaration
  from issue #347 §4.4: which fields name an instance that must already be in
  the vocabulary, which fields introduce a new one, and which must *not*
  already exist. `engine` walks a whole effect sequence against these in one
  linker-style two-pass resolution (#347 §4.3): every `writes` from an earlier
  effect is in the vocabulary a later effect `reads` from, which is what makes
  "create the room, then walk into it" legal inside one adjudication.
- `validate` — content validation. Refuses; runs before anything is written.
- `apply` — execution. Deliberately does **not** refuse (§3.2): it only ever
  sees input `validate` already accepted. Two entries keep a defensive
  rejection anyway, each marked at its call site with why.

## Why the engine helpers arrive as `EffectServices`

This package is a leaf (see `registry/__init__.py`): `module` reads these
tables at publish time and `docs/architecture.md` §6 forbids
`module -> engine`, so nothing here may import `engine` at runtime. A handful
of handlers genuinely need engine logic — pathfinding, the world clock — so
the engine passes those in as an explicit, frozen set of callables, the same
ports-and-adapters shape `engine/ports/` and `host/ports/` already use. State
*models* (`GameState`, `EngineRuntimeSnapshot`) are only ever read through
attribute access and constructed by their owners, so they are imported under
`TYPE_CHECKING` for annotations alone.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NoReturn
from uuid import uuid4

from pydantic import JsonValue

from collaboration_framework.contracts import (
    ActionEffect,
    AdvanceWorldTimeEffect,
    ChangeEntityStateEffect,
    CommitTerminalEndingEffect,
    ConsumeEntityEffect,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    HideInformationEffect,
    ItemAcquisition,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    LocationKnowledge,
    MarkCoreResolvedEffect,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    RevealInformationEffect,
    SetEndingAvailabilityEffect,
    SetVisibilityEffect,
    TravelInterrupted,
    TravelResolved,
)
from collaboration_framework.contracts.validation import (
    AdjudicationValidationError,
    AuthorityLevel,
    ClassificationCoverage,
    Repairability,
    ValidationResult,
)

if TYPE_CHECKING:  # annotations only — this package must not import engine.
    from collaboration_framework.engine.models import (
        EngineRuntimeSnapshot,
        GameState,
        WorldTimeState,
    )


# --------------------------------------------------------------------------- #
# rejection
# --------------------------------------------------------------------------- #
def reject(
    code: str,
    *,
    repairability: Repairability,
    fault: Literal["agent", "player", "engine"],
    player_safe_reason: str,
    internal_reason: str | None = None,
    classification_coverage: ClassificationCoverage = "partial_validation_failure",
) -> NoReturn:
    """Refuse an effect. Lives here because refusing is what this table does."""

    raise AdjudicationValidationError(
        ValidationResult(
            status="rejected",
            code=code,
            repairability=repairability,
            fault=fault,
            player_safe_reason=player_safe_reason,
            classification_coverage=classification_coverage,
            internal_reason=internal_reason,
        )
    )


def _reject_target_not_found() -> NoReturn:
    reject(
        "TARGET_NOT_FOUND",
        repairability="auto_repairable",
        fault="agent",
        player_safe_reason="当前目标不可用于这次行动",
    )


def _reject_canon_shadow() -> NoReturn:
    reject(
        "CANON_SHADOW",
        repairability="auto_repairable",
        fault="agent",
        player_safe_reason="当前目标不可用于这次行动",
    )


def _reject_not_portable() -> NoReturn:
    reject(
        "INVENTORY_TARGET_NOT_PORTABLE",
        repairability="auto_repairable",
        fault="agent",
        player_safe_reason="这个对象不是可携带物品，不能放入背包",
    )


# --------------------------------------------------------------------------- #
# ports: the engine logic a handler may need
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EffectServices:
    """Engine-owned pure functions the tables call, injected by the engine.

    Kept to the smallest possible surface: everything else a handler needs is
    either a contracts model or plain attribute reads off the state it was
    handed.
    """

    resolve_location_target: Callable[..., object]
    advanced_to_next: Callable[..., object]
    next_point_after: Callable[..., object]
    time_advance_block_reason: Callable[..., str | None]
    is_public_standard_state: Callable[..., bool]
    new_event_id: Callable[[], str] = lambda: f"evt_{uuid4().hex}"


# --------------------------------------------------------------------------- #
# access declarations (#347 §4.4)
# --------------------------------------------------------------------------- #
Vocabulary = Literal["information", "entities", "locations", "portable_items", "actors"]


@dataclass(frozen=True)
class FieldRef:
    """One field of an effect, and the vocabulary the id in it belongs to."""

    field: str
    vocabulary: Vocabulary
    optional: bool = False


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ClassificationContext:
    """The module-and-state lookups every authority rule shares.

    Built once per effect sequence rather than per effect — the originating
    `_classify_effects` hoisted exactly these out of its loop.
    """

    entity_specs: dict[str, object] = field(default_factory=dict)
    information_specs: dict[str, object] = field(default_factory=dict)
    core_goal_ids: frozenset[str] = frozenset()
    runtime_entity_ids: frozenset[str] = frozenset()
    runtime_location_ids: frozenset[str] = frozenset()

    def information_is_pivotal(self, information_id: str) -> bool:
        """Essential intel, or intel a core-resolution goal depends on."""

        info = self.information_specs.get(information_id)
        if info is None:
            return False
        return (
            getattr(info, "criticality", None) == "essential"
            or information_id in self.core_goal_ids
        )

    def entity_is_keeper_only(self, entity_id: str) -> bool:
        entity = self.entity_specs.get(entity_id)
        return entity is not None and getattr(entity, "visibility", None) == "keeper"


def classification_context(runtime: EngineRuntimeSnapshot) -> ClassificationContext:
    v3 = runtime.v3 if runtime.is_v3 else None
    return ClassificationContext(
        entity_specs={item.id: item for item in v3.entities} if v3 else {},
        information_specs={item.id: item for item in v3.information} if v3 else {},
        core_goal_ids=frozenset(
            info_id
            for goal in (v3.knowledge_goals if v3 else ())
            if goal.required_for_core_resolution
            for info_id in goal.target_information_ids
        ),
        runtime_entity_ids=frozenset(runtime.game_state.runtime_entities),
        runtime_location_ids=frozenset(runtime.game_state.runtime_locations),
    )


# --------------------------------------------------------------------------- #
# validation / application call shapes
# --------------------------------------------------------------------------- #
@dataclass
class ValidationVocabulary:
    """The ids legal to reference at this point in an effect sequence.

    Mutable on purpose: `engine` rolls it forward as it walks the sequence,
    folding in each effect's `writes` before validating the next one — the
    second pass of the linker-style resolution in #347 §4.3.
    """

    information_ids: set[str]
    entity_ids: set[str]
    location_ids: set[str]
    portable_item_ids: set[str]
    actor_ids: set[str]
    world_time: WorldTimeState | None = None
    # 仅由 Engine 的内部全员确认入口设置；普通 Agent 裁决不能绕过多人时间门禁。
    allow_party_time_advance: bool = False
    # 仅由 Engine 的内部全员确认入口设置；普通 Agent 裁决不能绕过多人场景门禁。
    allow_party_scene_transition: bool = False


@dataclass(frozen=True)
class ApplyContext:
    """Everything a handler needs to turn one effect into a state change."""

    runtime: EngineRuntimeSnapshot
    state: GameState
    services: EffectServices
    room_id: str
    request_id: str
    actor_id: str
    offset: int


@dataclass(frozen=True)
class ApplyResult:
    """A handler's output: the new state, plus what to record about it.

    `event_type` being None is only legal for a registration that declares
    `emits_event=False`; the engine treats any other None as a missing
    registration rather than letting it pass silently.
    """

    state: GameState
    event_type: str | None = None
    payload: dict[str, JsonValue] = field(default_factory=dict)
    event_id: str | None = None


EffectValidator = Callable[
    ["ActionEffect", "ValidationVocabulary", "EngineRuntimeSnapshot", "EffectServices"],
    None,
]


@dataclass(frozen=True)
class EffectRegistration:
    """Everything the Engine knows about one effect type."""

    authority: Callable[[ActionEffect, ClassificationContext], AuthorityLevel]
    apply: Callable[[ActionEffect, ApplyContext], ApplyResult]
    target_ref: Callable[[ActionEffect], str | None] = lambda effect: None
    # None means "nothing to check beyond the schema" — an explicit decision,
    # not a branch someone forgot to write.
    validate: EffectValidator | None = None
    reads: tuple[FieldRef, ...] = ()
    writes: tuple[FieldRef, ...] = ()
    must_not_exist: tuple[FieldRef, ...] = ()
    emits_event: bool = True


# --------------------------------------------------------------------------- #
# narrative_only
# --------------------------------------------------------------------------- #
def _apply_narrative_only(effect: NarrativeOnlyEffect, ctx: ApplyContext) -> ApplyResult:
    return ApplyResult(state=ctx.state)


# --------------------------------------------------------------------------- #
# reveal_information / hide_information
# --------------------------------------------------------------------------- #
def _validate_information(
    effect: RevealInformationEffect | HideInformationEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if effect.information_id not in vocab.information_ids:
        _reject_target_not_found()


def _apply_information(
    effect: RevealInformationEffect | HideInformationEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state
    reveal = isinstance(effect, RevealInformationEffect)
    if effect.scope == "party":
        facts = set(state.discovered_facts)
        (facts.add if reveal else facts.discard)(effect.information_id)
        state = state.model_copy(
            update={"discovered_facts": tuple(sorted(facts))},
            deep=True,
        )
    else:
        actor_facts = deepcopy(state.actor_discovered_facts)
        facts = set(actor_facts.get(ctx.actor_id, ()))
        (facts.add if reveal else facts.discard)(effect.information_id)
        actor_facts[ctx.actor_id] = tuple(sorted(facts))
        state = state.model_copy(
            update={"actor_discovered_facts": actor_facts},
            deep=True,
        )
    return ApplyResult(
        state=state,
        event_type="information.revealed" if reveal else "information.hidden",
        payload={"information_id": effect.information_id, "scope": effect.scope},
    )


# --------------------------------------------------------------------------- #
# set_visibility
# --------------------------------------------------------------------------- #
def _authority_set_visibility(
    effect: SetVisibilityEffect,
    ctx: ClassificationContext,
) -> AuthorityLevel:
    if effect.target_kind == "information":
        return "L4" if ctx.information_is_pivotal(effect.target_id) else "L2"
    if (
        effect.target_id in ctx.runtime_entity_ids
        or effect.target_id in ctx.runtime_location_ids
    ):
        return "L1"
    if effect.target_kind == "entity" and ctx.entity_is_keeper_only(effect.target_id):
        return "L4"
    return "L3"


def _validate_set_visibility(
    effect: SetVisibilityEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    valid = {
        "information": vocab.information_ids,
        "entity": vocab.entity_ids,
        "location": vocab.location_ids,
    }[effect.target_kind]
    if effect.target_id not in valid:
        _reject_target_not_found()


def _visibility_knowledge(
    location_id: str,
    *,
    scope: str,
    visible: bool,
    previous: LocationKnowledge | None,
) -> LocationKnowledge:
    return LocationKnowledge(
        location_id=location_id,
        scope="actor" if scope == "actor" else "party",
        existence="known" if visible else "unknown",
        localization="located" if visible else "unknown",
        access=(previous.access if visible and previous is not None else "unknown"),
        visited=bool(visible and previous and previous.visited),
        known_connection_ids=(
            previous.known_connection_ids if visible and previous is not None else ()
        ),
    )


def _apply_set_visibility(effect: SetVisibilityEffect, ctx: ApplyContext) -> ApplyResult:
    state = ctx.state
    overrides = dict(state.visibility_overrides)
    # Party scope must not be keyed by the acting actor, or no other
    # actor could ever find the override again. Actor scope keeps the
    # actor id and wins over the party entry when both exist
    # (see RuleEngineService._override_allows).
    key = (
        f"actor:{ctx.actor_id}:{effect.target_kind}:{effect.target_id}"
        if effect.scope == "actor"
        else f"party:{effect.target_kind}:{effect.target_id}"
    )
    overrides[key] = effect.visible
    updates: dict[str, object] = {"visibility_overrides": overrides}
    if effect.target_kind == "location":
        knowledge_by_scope = (
            deepcopy(state.actor_location_knowledge)
            if effect.scope == "actor"
            else deepcopy(state.party_location_knowledge)
        )
        if effect.scope == "actor":
            actor_knowledge = knowledge_by_scope.setdefault(ctx.actor_id, {})
            previous_knowledge = actor_knowledge.get(effect.target_id)
            actor_knowledge[effect.target_id] = _visibility_knowledge(
                effect.target_id,
                scope="actor",
                visible=effect.visible,
                previous=previous_knowledge,
            )
            updates["actor_location_knowledge"] = knowledge_by_scope
        else:
            previous_knowledge = knowledge_by_scope.get(effect.target_id)
            knowledge_by_scope[effect.target_id] = _visibility_knowledge(
                effect.target_id,
                scope="party",
                visible=effect.visible,
                previous=previous_knowledge,
            )
            updates["party_location_knowledge"] = knowledge_by_scope
    state = state.model_copy(update=updates, deep=True)
    return ApplyResult(
        state=state,
        event_type="visibility.changed",
        payload={
            "target_kind": effect.target_kind,
            "target_id": effect.target_id,
            "visible": effect.visible,
            "scope": effect.scope,
        },
    )


# --------------------------------------------------------------------------- #
# enter_location
# --------------------------------------------------------------------------- #
def _validate_enter_location(
    effect: EnterLocationEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if effect.location_id not in vocab.location_ids:
        _reject_target_not_found()
    if len(vocab.actor_ids) > 1 and not vocab.allow_party_scene_transition:
        reject(
            "SCENE_TRANSITION_BLOCKED",
            repairability="requires_player_choice",
            fault="player",
            player_safe_reason="多人房间切换场景需要全员确认",
            internal_reason="多人共享场景切换未经过全员确认",
        )


def _apply_enter_location(effect: EnterLocationEffect, ctx: ApplyContext) -> ApplyResult:
    state = ctx.state
    if not ctx.runtime.is_v3:
        previous = state.scene_id
        state = state.model_copy(update={"scene_id": effect.location_id}, deep=True)
        return ApplyResult(
            state=state,
            event_type="location.entered",
            payload={
                "location_id": effect.location_id,
                "from_location_id": previous,
            },
        )

    resolution = ctx.services.resolve_location_target(
        ctx.runtime.v3,
        state,
        actor_id=ctx.actor_id,
        target_id=effect.location_id,
    )
    contexts = dict(state.actor_position_contexts)
    knowledge = dict(state.party_location_knowledge)
    previous_knowledge = knowledge.get(effect.location_id)
    if resolution.status == "known_reachable":
        contexts.pop(ctx.actor_id, None)
        knowledge[effect.location_id] = LocationKnowledge(
            location_id=effect.location_id,
            scope="party",
            existence="known",
            localization="located",
            access="reachable",
            visited=True,
            known_connection_ids=(
                previous_knowledge.known_connection_ids
                if previous_knowledge is not None
                else ()
            ),
        )
        travel = TravelResolved(
            destination_id=effect.location_id,
            path=resolution.path,
        )
        state = state.model_copy(
            update={
                "scene_id": effect.location_id,
                "party_location_knowledge": knowledge,
                "actor_position_contexts": contexts,
            },
            deep=True,
        )
        return ApplyResult(
            state=state,
            event_type="travel.resolved",
            payload={
                "destination_id": travel.destination_id,
                "path": list(travel.path),
            },
        )
    if resolution.status == "known_blocked":
        assert resolution.boundary is not None
        assert resolution.reached_location_id is not None
        travel = TravelInterrupted(
            destination_id=effect.location_id,
            current_location_id=resolution.reached_location_id,
            path=resolution.path,
            reached_boundary=resolution.boundary,
        )
        contexts[ctx.actor_id] = travel
        knowledge[effect.location_id] = LocationKnowledge(
            location_id=effect.location_id,
            scope="party",
            existence="known",
            localization="located",
            access="blocked",
            visited=bool(previous_knowledge and previous_knowledge.visited),
            known_connection_ids=(
                previous_knowledge.known_connection_ids
                if previous_knowledge is not None
                else ()
            ),
        )
        state = state.model_copy(
            update={
                "scene_id": travel.current_location_id,
                "party_location_knowledge": knowledge,
                "actor_position_contexts": contexts,
            },
            deep=True,
        )
        return ApplyResult(
            state=state,
            event_type="travel.interrupted",
            payload={
                "destination_id": travel.destination_id,
                "current_location_id": travel.current_location_id,
                "path": list(travel.path),
                "reached_boundary": travel.reached_boundary.to_json_dict(),
            },
        )
    # Reachability is a live read of the location graph, so unlike every other
    # id check it cannot be settled by the vocabulary pass — this is the one
    # place application still has to refuse (#347 §3.3).
    reject(
        "TARGET_NOT_FOUND",
        repairability="auto_repairable",
        fault="agent",
        player_safe_reason="当前目标不可用于这次行动",
        internal_reason=(resolution.safe_reason or "当前没有可确认的目标路线"),
    )


# --------------------------------------------------------------------------- #
# ensure_runtime_location
# --------------------------------------------------------------------------- #
def _validate_ensure_runtime_location(
    effect: EnsureRuntimeLocationEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if (
        effect.location_id in vocab.location_ids
        or effect.connected_location_id not in vocab.location_ids
    ):
        _reject_canon_shadow()
    if (
        effect.parent_location_id is not None
        and effect.parent_location_id not in vocab.location_ids
    ):
        _reject_target_not_found()


def _apply_ensure_runtime_location(
    effect: EnsureRuntimeLocationEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state
    locations = deepcopy(state.runtime_locations)
    locations[effect.location_id] = {
        "name": effect.name,
        "parent_location_id": effect.parent_location_id,
        "connected_location_id": effect.connected_location_id,
        "provenance": "agent_adjudication",
    }
    knowledge = dict(state.party_location_knowledge)
    knowledge[effect.location_id] = LocationKnowledge(
        location_id=effect.location_id,
        existence="known",
        localization="located",
        access="reachable",
    )
    state = state.model_copy(
        update={
            "runtime_locations": locations,
            "party_location_knowledge": knowledge,
        },
        deep=True,
    )
    return ApplyResult(
        state=state,
        event_type="location.created",
        payload={"location_id": effect.location_id},
    )


# --------------------------------------------------------------------------- #
# ensure_runtime_entity
# --------------------------------------------------------------------------- #
def _validate_ensure_runtime_entity(
    effect: EnsureRuntimeEntityEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if effect.entity_id in vocab.entity_ids or effect.location_id not in vocab.location_ids:
        _reject_canon_shadow()
    if (
        runtime.is_v3
        and effect.entity_kind == "object"
        and (len(effect.entity_id) > 100 or len(effect.name) > 200)
    ):
        reject(
            "RUNTIME_ITEM_TOO_LARGE",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="临时物品描述超过当前系统限制",
        )


def _apply_ensure_runtime_entity(
    effect: EnsureRuntimeEntityEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state
    event_id: str | None = None
    if ctx.runtime.is_v3 and effect.entity_kind == "object":
        event_id = ctx.services.new_event_id()
        revision = str(state.event_sequence + ctx.offset)
        items = deepcopy(state.item_instances)
        items[effect.entity_id] = ItemInstance(
            id=effect.entity_id,
            room_id=ctx.room_id,
            origin="runtime",
            definition_id=effect.entity_id,
            display=ItemDisplay(name=effect.name),
            item_component=ItemComponent(),
            custody=ItemCustody(
                kind="location",
                ref_id=effect.location_id,
                form="loose",
            ),
            acquisition=ItemAcquisition(
                source_type="runtime",
                source_id=effect.location_id,
                player_safe_label="行动中发现",
                event_id=event_id,
                revision=revision,
            ),
            created_event_id=event_id,
            last_event_id=event_id,
            updated_revision=revision,
        )
        party_knowledge = deepcopy(state.party_item_knowledge)
        party_knowledge[effect.entity_id] = ItemKnowledge(
            item_id=effect.entity_id,
            identity="recognized",
        )
        state = state.model_copy(
            update={
                "item_instances": items,
                "party_item_knowledge": party_knowledge,
            },
            deep=True,
        )
    else:
        entities = deepcopy(state.runtime_entities)
        entities[effect.entity_id] = {
            "kind": effect.entity_kind,
            "name": effect.name,
            "location_id": effect.location_id,
            "provenance": "agent_adjudication",
        }
        state = state.model_copy(update={"runtime_entities": entities}, deep=True)
    return ApplyResult(
        state=state,
        event_type="entity.created",
        payload={"entity_id": effect.entity_id, "location_id": effect.location_id},
        event_id=event_id,
    )


# --------------------------------------------------------------------------- #
# entity storage routing (#347 §3.3 / P3)
# --------------------------------------------------------------------------- #
def resolve_entity_storage(
    state: GameState,
    entity_id: str,
) -> Literal["item_instance", "generic_entity"]:
    """Which record actually holds this entity's mutable state.

    An entity carrying an `item_component` is materialised into
    `item_instances` and is the versioned record; everything else lives in
    `runtime_entities`/`entities`. move/change_state/consume each used to
    inline this same `.get()` check, three copies of one rule.

    This is a *storage routing* question, deliberately distinct from the
    existence question `reads`/`writes` answers. It reads live state at
    application time on purpose: routing depends on what exists now, and the
    submit-time vocabulary pass runs in a different transaction from
    `decide`/`decide_post_roll`.
    """

    return "item_instance" if state.item_instances.get(entity_id) is not None else "generic_entity"


def _mutate_generic_entity(
    state: GameState,
    entity_id: str,
    mutate: Callable[[dict], None],
) -> dict[str, object]:
    """Apply a change to whichever generic record holds this entity."""

    runtime_entities = deepcopy(state.runtime_entities)
    entity_states = deepcopy(state.entities)
    target = runtime_entities.get(entity_id)
    if target is None:
        target = entity_states.setdefault(entity_id, {})
    mutate(target)
    return {"runtime_entities": runtime_entities, "entities": entity_states}


# --------------------------------------------------------------------------- #
# move_entity
# --------------------------------------------------------------------------- #
def _validate_move_entity(
    effect: MoveEntityEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if effect.entity_id not in vocab.entity_ids:
        _reject_target_not_found()
    if effect.location_id is not None and effect.location_id not in vocab.location_ids:
        _reject_target_not_found()
    if effect.holder_actor_id is not None and effect.holder_actor_id not in vocab.actor_ids:
        _reject_target_not_found()
    if effect.holder_actor_id is not None and effect.entity_id not in vocab.portable_item_ids:
        _reject_not_portable()


def _apply_move_entity(effect: MoveEntityEffect, ctx: ApplyContext) -> ApplyResult:
    state = ctx.state
    event_id: str | None = None
    if resolve_entity_storage(state, effect.entity_id) == "item_instance":
        item = state.item_instances[effect.entity_id]
        event_id = ctx.services.new_event_id()
        revision = str(state.event_sequence + ctx.offset)
        custody = (
            ItemCustody(
                kind="actor_inventory",
                ref_id=effect.holder_actor_id,
                form="carried",
            )
            if effect.holder_actor_id is not None
            else ItemCustody(
                kind="location",
                ref_id=effect.location_id,
                form="placed",
            )
        )
        items = deepcopy(state.item_instances)
        items[effect.entity_id] = item.model_copy(
            update={
                "custody": custody,
                "version": item.version + 1,
                "last_event_id": event_id,
                "updated_revision": revision,
            }
        )
        updates: dict[str, object] = {"item_instances": items}
        if effect.holder_actor_id is not None:
            actor_knowledge = deepcopy(state.actor_item_knowledge)
            actor_knowledge.setdefault(effect.holder_actor_id, {})[effect.entity_id] = (
                ItemKnowledge(
                    item_id=effect.entity_id,
                    scope="actor",
                    identity="known",
                )
            )
            updates["actor_item_knowledge"] = actor_knowledge
        else:
            party_knowledge = deepcopy(state.party_item_knowledge)
            party_knowledge[effect.entity_id] = ItemKnowledge(
                item_id=effect.entity_id,
                identity="recognized",
            )
            updates["party_item_knowledge"] = party_knowledge
        state = state.model_copy(update=updates, deep=True)
    else:
        if effect.holder_actor_id is not None:
            # Defense in depth for authored/rule-owned effects and any
            # future caller that reaches application without the
            # proposal validator.  Generic entities may move between
            # locations, but only ItemInstances have inventory custody.
            _reject_not_portable()

        def _place(target: dict) -> None:
            target["location_id"] = effect.location_id
            target["holder_actor_id"] = effect.holder_actor_id

        state = state.model_copy(
            update=_mutate_generic_entity(state, effect.entity_id, _place),
            deep=True,
        )
    return ApplyResult(
        state=state,
        event_type="entity.moved",
        payload={
            "entity_id": effect.entity_id,
            "location_id": effect.location_id,
            "holder_actor_id": effect.holder_actor_id,
        },
        event_id=event_id,
    )


# --------------------------------------------------------------------------- #
# change_entity_state
# --------------------------------------------------------------------------- #
def _validate_entity_target(
    effect: ChangeEntityStateEffect | ConsumeEntityEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if effect.entity_id not in vocab.entity_ids:
        _reject_target_not_found()


def _apply_change_entity_state(
    effect: ChangeEntityStateEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state
    event_id: str | None = None
    if resolve_entity_storage(state, effect.entity_id) == "item_instance":
        item = state.item_instances[effect.entity_id]
        event_id = ctx.services.new_event_id()
        revision = str(state.event_sequence + ctx.offset)
        values = deepcopy(item.state.values)
        values[effect.key] = effect.value
        items = deepcopy(state.item_instances)
        items[effect.entity_id] = item.model_copy(
            update={
                "state": item.state.model_copy(update={"values": values}),
                "version": item.version + 1,
                "last_event_id": event_id,
                "updated_revision": revision,
            }
        )
        updates: dict[str, object] = {"item_instances": items}
    else:

        def _set_key(target: dict) -> None:
            target[effect.key] = effect.value

        updates = _mutate_generic_entity(state, effect.entity_id, _set_key)
    if ctx.services.is_public_standard_state(effect):
        public_keys = deepcopy(state.public_entity_state_keys)
        keys = set(public_keys.get(effect.entity_id, ()))
        keys.add(effect.key)
        public_keys[effect.entity_id] = tuple(sorted(keys))
        updates["public_entity_state_keys"] = public_keys
    state = state.model_copy(update=updates, deep=True)
    return ApplyResult(
        state=state,
        event_type="entity.state_changed",
        payload={
            "entity_id": effect.entity_id,
            "key": effect.key,
            "value": effect.value,
        },
        event_id=event_id,
    )


# --------------------------------------------------------------------------- #
# consume_entity
# --------------------------------------------------------------------------- #
def _apply_consume_entity(effect: ConsumeEntityEffect, ctx: ApplyContext) -> ApplyResult:
    state = ctx.state
    event_id: str | None = None
    if resolve_entity_storage(state, effect.entity_id) == "item_instance":
        item = state.item_instances[effect.entity_id]
        event_id = ctx.services.new_event_id()
        revision = str(state.event_sequence + ctx.offset)
        items = deepcopy(state.item_instances)
        items[effect.entity_id] = item.model_copy(
            update={
                "state": item.state.model_copy(update={"status": "retired"}),
                "version": item.version + 1,
                "last_event_id": event_id,
                "updated_revision": revision,
            }
        )
        state = state.model_copy(update={"item_instances": items}, deep=True)
    else:

        def _consume(target: dict) -> None:
            target["consumed"] = True

        state = state.model_copy(
            update=_mutate_generic_entity(state, effect.entity_id, _consume),
            deep=True,
        )
    return ApplyResult(
        state=state,
        event_type="entity.consumed",
        payload={"entity_id": effect.entity_id},
        event_id=event_id,
    )


# --------------------------------------------------------------------------- #
# advance_world_time
# --------------------------------------------------------------------------- #
def _validate_advance_world_time(
    effect: AdvanceWorldTimeEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    if not runtime.is_v3:
        reject(
            "TIME_POINT_MISMATCH",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="当前时间目标与世界时间线不一致",
        )
    blocked = services.time_advance_block_reason(tuple(vocab.actor_ids))
    if blocked is not None and not vocab.allow_party_time_advance:
        reject(
            "TIME_ADVANCE_BLOCKED",
            repairability="requires_player_choice",
            fault="player",
            player_safe_reason="当前存在需要玩家先处理的事项，不能推进时间",
            internal_reason=blocked,
        )
    target, _ = services.next_point_after(
        runtime.v3,
        vocab.world_time if vocab.world_time is not None else runtime.game_state.world_time,
    )
    if effect.to_point_id is not None and effect.to_point_id != target.id:
        reject(
            "TIME_POINT_MISMATCH",
            repairability="auto_repairable",
            fault="agent",
            player_safe_reason="当前时间目标与世界时间线不一致",
            internal_reason=(
                "advance_world_time 声明的时间点不是时间线上的下一个点: "
                f"{effect.to_point_id} != {target.id}"
            ),
        )


def _apply_advance_world_time(
    effect: AdvanceWorldTimeEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    advanced = ctx.services.advanced_to_next(ctx.runtime.v3, ctx.state.world_time)
    state = ctx.state.model_copy(update={"world_time": advanced}, deep=True)
    return ApplyResult(
        state=state,
        event_type="time.point_entered",
        payload={
            "point_id": advanced.current_point_id,
            "day_index": advanced.current.day_index,
            "hour_of_day": advanced.current.hour_of_day,
            "time_of_day": advanced.time_of_day,
        },
    )


# --------------------------------------------------------------------------- #
# mark_core_resolved / set_ending_availability
# --------------------------------------------------------------------------- #
def _apply_mark_core_resolved(
    effect: MarkCoreResolvedEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state.model_copy(update={"core_resolved": True}, deep=True)
    return ApplyResult(state=state, event_type="core.resolved")


def _apply_set_ending_availability(
    effect: SetEndingAvailabilityEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    state = ctx.state.model_copy(update={"ending_available": effect.available}, deep=True)
    return ApplyResult(
        state=state,
        event_type="ending.availability_changed",
        payload={"available": effect.available},
    )


# --------------------------------------------------------------------------- #
# commit_terminal_ending
# --------------------------------------------------------------------------- #
def _reject_terminal_ending(*_args: object, **_kwargs: object) -> NoReturn:
    reject(
        "ENDING_REQUIRES_DRAFT",
        repairability="hard_reject",
        fault="agent",
        player_safe_reason="终局必须经过明确确认后才能提交",
        internal_reason="终局不能由行动效果直接提交，必须确认 EndingDraft",
    )


def _apply_commit_terminal_ending(
    effect: CommitTerminalEndingEffect,
    ctx: ApplyContext,
) -> ApplyResult:
    # Unreachable through the validated path — validation already refuses this
    # type outright. Kept as the same defence the original `_apply_effect`
    # carried, for rule-owned effects that bypass proposal validation.
    reject(
        "ENDING_REQUIRES_DRAFT",
        repairability="hard_reject",
        fault="agent",
        player_safe_reason="终局必须经过明确确认后才能提交",
        classification_coverage="rule_effects_excluded",
    )


# --------------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------------- #
EFFECTS: dict[str, EffectRegistration] = {
    "narrative_only": EffectRegistration(
        authority=lambda effect, ctx: "L0",
        apply=_apply_narrative_only,
        emits_event=False,
    ),
    "reveal_information": EffectRegistration(
        authority=lambda effect, ctx: (
            "L4" if ctx.information_is_pivotal(effect.information_id) else "L2"
        ),
        target_ref=lambda effect: effect.information_id,
        validate=_validate_information,
        apply=_apply_information,
        reads=(FieldRef("information_id", "information"),),
    ),
    "hide_information": EffectRegistration(
        authority=lambda effect, ctx: (
            "L4" if ctx.information_is_pivotal(effect.information_id) else "L2"
        ),
        target_ref=lambda effect: effect.information_id,
        validate=_validate_information,
        apply=_apply_information,
        reads=(FieldRef("information_id", "information"),),
    ),
    "set_visibility": EffectRegistration(
        authority=_authority_set_visibility,
        target_ref=lambda effect: effect.target_id,
        validate=_validate_set_visibility,
        apply=_apply_set_visibility,
        # target_id's vocabulary depends on target_kind, so the check lives in
        # `validate` rather than in a static FieldRef.
    ),
    "enter_location": EffectRegistration(
        authority=lambda effect, ctx: "L2",
        target_ref=lambda effect: effect.location_id,
        validate=_validate_enter_location,
        apply=_apply_enter_location,
        reads=(FieldRef("location_id", "locations"),),
    ),
    "ensure_runtime_location": EffectRegistration(
        authority=lambda effect, ctx: "L1",
        target_ref=lambda effect: effect.location_id,
        validate=_validate_ensure_runtime_location,
        apply=_apply_ensure_runtime_location,
        reads=(
            FieldRef("connected_location_id", "locations"),
            FieldRef("parent_location_id", "locations", optional=True),
        ),
        writes=(FieldRef("location_id", "locations"),),
        must_not_exist=(FieldRef("location_id", "locations"),),
    ),
    "ensure_runtime_entity": EffectRegistration(
        authority=lambda effect, ctx: "L1",
        target_ref=lambda effect: effect.entity_id,
        validate=_validate_ensure_runtime_entity,
        apply=_apply_ensure_runtime_entity,
        reads=(FieldRef("location_id", "locations"),),
        # A v3 object also joins the portable vocabulary; the engine folds that
        # in because it depends on `entity_kind`, not on the field alone.
        writes=(FieldRef("entity_id", "entities"),),
        must_not_exist=(FieldRef("entity_id", "entities"),),
    ),
    "move_entity": EffectRegistration(
        authority=lambda effect, ctx: (
            "L3" if effect.holder_actor_id is not None else "L2"
        ),
        target_ref=lambda effect: effect.entity_id,
        validate=_validate_move_entity,
        apply=_apply_move_entity,
        reads=(
            FieldRef("entity_id", "entities"),
            FieldRef("location_id", "locations", optional=True),
            FieldRef("holder_actor_id", "actors", optional=True),
        ),
    ),
    "change_entity_state": EffectRegistration(
        authority=lambda effect, ctx: (
            "L1" if effect.entity_id in ctx.runtime_entity_ids else "L3"
        ),
        target_ref=lambda effect: effect.entity_id,
        validate=_validate_entity_target,
        apply=_apply_change_entity_state,
        reads=(FieldRef("entity_id", "entities"),),
    ),
    "consume_entity": EffectRegistration(
        authority=lambda effect, ctx: (
            "L4" if ctx.entity_is_keeper_only(effect.entity_id) else "L3"
        ),
        target_ref=lambda effect: effect.entity_id,
        validate=_validate_entity_target,
        apply=_apply_consume_entity,
        reads=(FieldRef("entity_id", "entities"),),
    ),
    "advance_world_time": EffectRegistration(
        authority=lambda effect, ctx: "L2",
        validate=_validate_advance_world_time,
        apply=_apply_advance_world_time,
    ),
    "mark_core_resolved": EffectRegistration(
        authority=lambda effect, ctx: "L4",
        # No content to validate: the effect carries no id and no argument.
        validate=None,
        apply=_apply_mark_core_resolved,
    ),
    "set_ending_availability": EffectRegistration(
        authority=lambda effect, ctx: "L4",
        # No content to validate: `available` is a bool the schema already pins.
        validate=None,
        apply=_apply_set_ending_availability,
    ),
    "commit_terminal_ending": EffectRegistration(
        authority=lambda effect, ctx: "L5",
        target_ref=lambda effect: effect.ending_id,
        validate=_reject_terminal_ending,
        apply=_apply_commit_terminal_ending,
    ),
}


def registration_for(effect: ActionEffect) -> EffectRegistration:
    registration = EFFECTS.get(effect.type)
    if registration is None:
        reject(
            "EFFECT_NOT_REGISTERED",
            repairability="hard_reject",
            fault="engine",
            player_safe_reason="规则引擎无法处理当前效果",
        )
    return registration


def classify(
    effect: ActionEffect,
    ctx: ClassificationContext,
) -> tuple[AuthorityLevel, str | None]:
    """The authority proposing this effect takes, and what it points at."""

    registration = registration_for(effect)
    return registration.authority(effect, ctx), registration.target_ref(effect)


def validate(
    effect: ActionEffect,
    vocab: ValidationVocabulary,
    runtime: EngineRuntimeSnapshot,
    services: EffectServices,
) -> None:
    """Refuse an ill-formed effect. A registration with no `validate` has
    nothing to check beyond what its schema already guarantees."""

    registration = registration_for(effect)
    if registration.validate is not None:
        registration.validate(effect, vocab, runtime, services)


def apply(effect: ActionEffect, ctx: ApplyContext) -> ApplyResult:
    """Execute an effect that validation already accepted."""

    registration = registration_for(effect)
    result = registration.apply(effect, ctx)
    if registration.emits_event and result.event_type is None:
        reject(
            "EFFECT_NOT_REGISTERED",
            repairability="hard_reject",
            fault="engine",
            player_safe_reason="规则引擎无法处理当前效果",
        )
    return result


def absorb_writes(effect: ActionEffect, vocab: ValidationVocabulary, *, is_v3: bool) -> None:
    """Fold an accepted effect's `writes` into the vocabulary.

    The first pass of #347 §4.3's two-pass resolution: what an effect
    introduces is in scope for every effect after it in the same sequence.
    """

    registration = registration_for(effect)
    for ref in registration.writes:
        value = getattr(effect, ref.field, None)
        if not isinstance(value, str):
            continue
        if ref.vocabulary == "locations":
            vocab.location_ids.add(value)
        elif ref.vocabulary == "entities":
            vocab.entity_ids.add(value)
            # v3 materialises a runtime object into `item_instances`, which is
            # what makes it portable; a v2 entity or an NPC never becomes one.
            if is_v3 and getattr(effect, "entity_kind", None) == "object":
                vocab.portable_item_ids.add(value)


__all__ = [
    "EFFECTS",
    "ApplyContext",
    "ApplyResult",
    "ClassificationContext",
    "EffectRegistration",
    "EffectServices",
    "FieldRef",
    "ValidationVocabulary",
    "absorb_writes",
    "apply",
    "classification_context",
    "classify",
    "reject",
    "registration_for",
    "resolve_entity_storage",
    "validate",
]
