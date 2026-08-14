"""Controlled Keeper-side capability view handed to the adjudicating Agent.

Issue #212 splits the two views the Agent runs on: a revision-bound, player-safe
`PlayerView`, and a controlled `GMView / Canon 图谱` that lets it name the Canon
objects an effect may legally reference. Without the second one the Agent can
only ever propose `enter_location` and `narrative_only`, because every other
registered effect needs an id the player-safe view deliberately withholds — a
Canon Information that has not been discovered yet, an Ending, an Entity that is
not in the current scene.

Two boundaries make this safe to hand to a model:

* it is **capability data, not narration input** — it goes to the planner and the
  step adjudicator only. `ActionPlanNarrationContext` never carries it, and the
  Narrator still may cite nothing but committed evidence refs.
* it never reaches the client. It is not part of `PlayerView` and no transport
  payload embeds it.

The Engine remains the authority regardless: everything named here is
re-validated against the same runtime snapshot when the adjudication is
submitted, so a stale or mis-copied id is refused rather than trusted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel
from .module_v3 import WorldProfileSpec


class KeeperInformationCapability(ContractModel):
    """One Canon Information the Agent may reveal or hide."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    # Keeper-only until an effect releases it. Present so the Agent can judge
    # whether a player's action actually earns this specific fact.
    content: str = Field(min_length=1)
    related_entities: tuple[str, ...] = ()
    related_scenes: tuple[str, ...] = ()
    known_by_party: bool = False
    known_by_actor: bool = False


class KeeperLocationCapability(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    origin: Literal["canon", "runtime"]
    is_current: bool = False


class KeeperEntityCapability(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    origin: Literal["canon", "runtime"]
    location_id: str | None = Field(default=None, min_length=1)
    holder_actor_id: str | None = Field(default=None, min_length=1)
    consumed: bool = False


class KeeperEndingCapability(ContractModel):
    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class KeeperRuleOption(ContractModel):
    """One opaque choice on a rule's candidate menu.

    The Agent submits `id` and nothing else; what the option *does* stays on the
    server, so a creative model cannot pick an outcome (#226 §1).

    `requires_check` is the one exception, and it is not an outcome: it says
    only whether this branch rolls dice. The Agent has to know, because it must
    decide between proposing a check and proposing none — without it the prompt
    had to tell the model to always send a check and reuse the option id as a
    skill id, which breaks for options that name no skill at all (`proceed`,
    `STR`). The player sees the dice either way, so nothing hidden leaks.
    """

    id: str = Field(min_length=1)
    semantic_hints: tuple[str, ...] = ()
    requires_check: bool = True


class KeeperRuleCandidate(ContractModel):
    """An `agent_match` Rule that could apply where the actor currently is.

    This is the minimal Rule Match View of #226 §2: the Engine decides which
    rules are even in scope, and the Agent only judges which option the player's
    words mean. It rides on the Keeper view because it is keeper-side, agent-only
    data that must never reach the client — the same boundary #226 draws between
    the Match View and PlayerView.
    """

    rule_id: str = Field(min_length=1)
    question_kind: Literal["action_declaration", "method", "intent_relation"]
    semantic_hints: tuple[str, ...] = ()
    action_families: tuple[str, ...] = ()
    target_kinds: tuple[Literal["information", "entity", "location", "actor", "world"], ...] = ()
    target_ids: tuple[str, ...] = ()
    options: tuple[KeeperRuleOption, ...] = ()


class KeeperTimeCapability(ContractModel):
    """What one `advance_world_time` effect would do, and whether it may run.

    The Agent has to be able to count jumps ("sleep until 20:00" is two of
    them), so it needs the ordered points, not just the next one. `blocked_reason`
    is populated instead of hiding the capability, because "you cannot advance
    time here, and here is why" is what lets the Agent say something true to the
    player rather than silently doing nothing.
    """

    current_point_id: str = Field(min_length=1)
    current_hour_of_day: int = Field(ge=0, le=23)
    current_day_index: int = Field(ge=0)
    next_point_id: str | None = Field(default=None, min_length=1)
    ordered_point_ids: tuple[str, ...] = ()
    blocked_reason: str | None = None


class KeeperCapabilityView(ContractModel):
    """Everything the Agent needs to name a legal target or effect payload."""

    room_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    # Bound to the same revision as the PlayerView it accompanies, so a step
    # adjudicated against a stale capability list is rejected on submit.
    revision: str = Field(min_length=1)
    # The only id `ActionTarget(kind="world", ...)` accepts. It is the module's
    # `world_ref`, which is a rule-system id (`coc-7e` for 追书人) — nothing in
    # PlayerView or anywhere else hints at it, so before #313 an Agent that
    # wanted the world as a target had to guess and was rejected every time
    # (TARGET_UNAVAILABLE on "今天几点了" and other non-object utterances).
    world_id: str | None = Field(default=None, min_length=1)
    # v3 Runtime content must be judged against authored setting constraints,
    # not reconstructed from prose or guessed from the player's wording.
    # v2 has no WorldProfile contract and therefore leaves this absent.
    world_profile: WorldProfileSpec | None = None
    information: tuple[KeeperInformationCapability, ...] = ()
    locations: tuple[KeeperLocationCapability, ...] = ()
    entities: tuple[KeeperEntityCapability, ...] = ()
    endings: tuple[KeeperEndingCapability, ...] = ()
    rule_candidates: tuple[KeeperRuleCandidate, ...] = ()
    time: KeeperTimeCapability | None = None
    core_resolved: bool = False
    ending_available: bool = False


__all__ = [
    "KeeperCapabilityView",
    "KeeperEndingCapability",
    "KeeperEntityCapability",
    "KeeperInformationCapability",
    "KeeperLocationCapability",
    "KeeperRuleCandidate",
    "KeeperRuleOption",
    "KeeperTimeCapability",
]
