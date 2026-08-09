"""Projecting a v3 module (#212 §7 / §4 / §8).

Driven by the real 追书人 v3 fixture rather than a toy module, because the
things most likely to break — a gated crypt, a study that is a room, an entity
placed by `located_in` — only exist at that scale.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    CommitTerminalEndingEffect,
    ContractError,
    EnterLocationEffect,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    ModuleContentV3,
    NoAdjudicationCheck,
    PlayerViewScope,
    PostRollDecisionRequest,
    PredicateCondition,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
    SelectCheckChoice,
    SkillCheckCandidate,
    RevealInformationEffect,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
)
from collaboration_framework.engine.projection_v3 import location_breadcrumbs
from collaboration_framework.engine.rules_v3 import evaluate_condition, walk_rule

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
ROOM = "room_v3"
ACTOR = "pc_1"
PLAYER = "player_v3"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(content: ModuleContentV3, **overrides) -> GameState:
    base = {
        "room_id": ROOM,
        "scene_id": content.initial_state.start_location_id,
        "actors": {
            ACTOR: ActorState(
                player_id=PLAYER,
                name="陈探员",
                source_character_id="character_v3",
                source_character_version=1,
                state={
                    "skills": {"spot-hidden": 60, "library-use": 70},
                    "occupation": "私家侦探",
                },
            )
        },
        "entities": {},
    }
    base.update(overrides)
    return GameState(**base)


class ProjectionV3Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.content = module()

    async def project(self, state: GameState):
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=state)
        engine = RuleEngineService(store)
        return await engine.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

    async def test_opening_location_projects_its_entities_and_exits(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.scene_id, "thomas_office")
        # thomas is placed here by `located_in`, not by a Scene entity list.
        self.assertIn(
            "thomas", {entity.id for entity in snapshot.scene.visible_entities}
        )
        self.assertIn(
            "arnoldsburg_streets",
            {
                exit_.destination.scene_id
                for exit_ in snapshot.scene.available_exits
                if exit_.destination
            },
        )
        known_ids = {location.id for location in snapshot.known_locations}
        self.assertIn("library", known_ids)
        self.assertIn("kimball_study", known_ids)
        self.assertNotIn("crypt", known_ids)
        self.assertNotIn("speakeasy", known_ids)
        assert snapshot.location_context is not None
        self.assertEqual(
            [item.name for item in snapshot.location_context.breadcrumbs],
            ["阿诺兹堡", "托马斯的会客室"],
        )

    async def test_hidden_edges_stay_out_of_the_view(self) -> None:
        # The crypt and the speakeasy must not be advertised before they are found.
        state = game_state(self.content, scene_id="cemetery")
        snapshot = await self.project(state)
        destinations = {
            exit_.destination.scene_id
            for exit_ in snapshot.scene.available_exits
            if exit_.destination
        }
        self.assertNotIn("crypt", destinations)
        self.assertIn("surveillance_point", destinations)

    async def test_inventory_and_loose_items_require_separate_knowledge(self) -> None:
        held = ItemInstance(
            id="held_lamp",
            room_id=ROOM,
            origin="runtime",
            definition_id="lamp",
            display=ItemDisplay(name="提灯"),
            item_component=ItemComponent(),
            custody=ItemCustody(kind="actor_inventory", ref_id=ACTOR, form="carried"),
            created_event_id="seed-held",
            last_event_id="seed-held",
            updated_revision="0",
        )
        loose = held.model_copy(
            update={
                "id": "loose_key",
                "display": ItemDisplay(name="铜钥匙"),
                "custody": ItemCustody(
                    kind="location", ref_id="thomas_office", form="loose"
                ),
            }
        )
        hidden = held.model_copy(
            update={
                "id": "hidden_note",
                "display": ItemDisplay(name="暗格信纸"),
                "custody": ItemCustody(
                    kind="location", ref_id="thomas_office", form="loose"
                ),
            }
        )
        state = game_state(
            self.content,
            item_instances={item.id: item for item in (held, loose, hidden)},
            party_item_knowledge={
                loose.id: ItemKnowledge(item_id=loose.id, identity="recognized")
            },
            actor_item_knowledge={
                ACTOR: {
                    held.id: ItemKnowledge(
                        item_id=held.id, scope="actor", identity="known"
                    )
                }
            },
        )

        snapshot = await self.project(state)

        self.assertEqual([item.id for item in snapshot.inventory], [held.id])
        self.assertEqual([item.id for item in snapshot.scene.loose_items], [loose.id])
        self.assertEqual(snapshot.self_actor.equipment, ("提灯",))

    async def test_discovered_locked_location_is_known_but_not_entered(self) -> None:
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"crypt_entrance": {"discovered": True, "slab_moved": False}},
        )
        snapshot = await self.project(state)
        crypt = next(item for item in snapshot.known_locations if item.id == "crypt")
        self.assertEqual(crypt.access, "blocked")
        self.assertIn(
            "crypt",
            {
                exit_.destination.scene_id
                for exit_ in snapshot.scene.available_exits
                if exit_.destination
            },
        )

    async def test_moving_an_entity_moves_where_it_is_projected(self) -> None:
        # `located_in` is the module's placement; runtime state overrides it, which
        # is what `move_entity` writes.
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"douglas_diary": {"location_id": "cemetery"}},
        )
        snapshot = await self.project(state)
        self.assertIn(
            "douglas_diary",
            {entity.id for entity in snapshot.scene.visible_entities},
        )

    async def test_a_carried_entity_follows_the_actor(self) -> None:
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"douglas_diary": {"holder_actor_id": ACTOR}},
        )
        snapshot = await self.project(state)
        self.assertIn(
            "douglas_diary",
            {entity.id for entity in snapshot.scene.visible_entities},
        )

    async def test_a_consumed_entity_disappears(self) -> None:
        state = game_state(
            self.content,
            scene_id="speakeasy",
            entities={"liquor": {"consumed": True}},
        )
        snapshot = await self.project(state)
        self.assertNotIn(
            "liquor", {entity.id for entity in snapshot.scene.visible_entities}
        )

    async def test_undiscovered_information_is_withheld(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.known_information, ())

    async def test_released_information_shows_only_the_player_half(self) -> None:
        state = game_state(self.content, discovered_facts=("cemetery_dance_report",))
        snapshot = await self.project(state)
        released = next(
            item
            for item in snapshot.known_information
            if item.id == "cemetery_dance_report"
        )
        keeper_text = next(
            item.keeper_content
            for item in self.content.information
            if item.id == "cemetery_dance_report"
        )
        self.assertEqual(released.scope, "party")
        self.assertNotIn(keeper_text, released.content)

    async def test_world_block_carries_the_time_point_and_ending_state(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.world.day_index, 0)
        self.assertEqual(snapshot.world.hour_of_day, 12)
        self.assertEqual(snapshot.world.time_of_day, "day")
        self.assertFalse(snapshot.world.core_resolved)
        self.assertFalse(snapshot.world.ending_available)

    async def test_v3_publishes_no_checkpoint_options(self) -> None:
        # The candidate menu is produced per action by an agent_match Rule, not
        # published with the scene (#226 §2).
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.checkpoint_options, ())

    def test_breadcrumbs_follow_containment_not_reachability(self) -> None:
        trail = location_breadcrumbs(self.content, "kimball_study")
        self.assertEqual(
            [name for _, name in trail],
            ["阿诺兹堡", "金博尔宅", "道格拉斯的书房"],
        )

    async def test_entering_a_runtime_location_still_projects(self) -> None:
        # v2 raised "当前 Scene 不存在" here and bricked the room.
        state = game_state(
            self.content,
            scene_id="alley",
            runtime_locations={
                "alley": {
                    "name": "后巷",
                    "connected_location_id": "arnoldsburg_streets",
                }
            },
        )
        snapshot = await self.project(state)
        self.assertEqual(snapshot.scene_id, "alley")
        self.assertEqual(snapshot.scene.name, "后巷")


class AdjudicationAgainstV3Tests(unittest.IsolatedAsyncioTestCase):
    """The Engine must validate a v3 room against v3 collections (阶段 3b)."""

    def setUp(self) -> None:
        self.content = module()

    def build(self, **overrides):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, **overrides),
        )
        return store, AdjudicationEngineService(store), RuleEngineService(store)

    async def submit(self, engine, revision, *effects, target=None):
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"v3-{revision}-{len(effects)}",
                    source_revision=revision,
                    actor_id=ACTOR,
                    summary="测试用 v3 裁决",
                    target=target or ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="action", description="测试"),
                    check=NoAdjudicationCheck(),
                    success_effects=tuple(effects),
                ),
            )
        )

    async def test_revealing_a_v3_information_reaches_the_player_view(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await self.submit(
            engine,
            snapshot.revision,
            RevealInformationEffect(
                information_id="cemetery_dance_report", scope="party"
            ),
        )
        after = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertIn(
            "cemetery_dance_report", {item.id for item in after.known_information}
        )

    async def test_entering_a_v3_location_moves_the_actor(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await self.submit(
            engine,
            snapshot.revision,
            EnterLocationEffect(location_id="arnoldsburg_streets"),
        )
        after = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertEqual(after.scene_id, "arnoldsburg_streets")

    async def test_known_multi_edge_route_resolves_in_one_travel(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await self.submit(
            engine,
            snapshot.revision,
            EnterLocationEffect(location_id="library"),
        )

        self.assertEqual(store.inspect_state(ROOM).scene_id, "library")
        travel = next(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "travel.resolved"
        )
        self.assertEqual(
            travel.payload["path"],
            ["thomas_office", "arnoldsburg_streets", "library"],
        )

    async def test_locked_route_stops_at_access_boundary(self) -> None:
        store, engine, rules = self.build(
            scene_id="cemetery",
            entities={"crypt_entrance": {"discovered": True, "slab_moved": False}},
        )
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await self.submit(
            engine,
            snapshot.revision,
            EnterLocationEffect(location_id="crypt"),
        )

        self.assertEqual(store.inspect_state(ROOM).scene_id, "cemetery")
        interrupted = next(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "travel.interrupted"
        )
        self.assertEqual(interrupted.payload["destination_id"], "crypt")
        after = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        assert after.location_context is not None
        assert after.location_context.position_context is not None
        self.assertEqual(after.location_context.current_location_id, "cemetery")
        self.assertEqual(after.location_context.position_context.state, "locked")

    async def test_unrevealed_hidden_location_cannot_be_entered(self) -> None:
        store, engine, rules = self.build(scene_id="cemetery")
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with self.assertRaisesRegex(ContractError, "可确认的目标路线"):
            await self.submit(
                engine,
                snapshot.revision,
                EnterLocationEffect(location_id="crypt"),
            )
        self.assertEqual(store.inspect_state(ROOM).scene_id, "cemetery")

    async def test_a_v2_scene_id_is_no_longer_a_valid_location(self) -> None:
        # `client_briefing` was the v2 opening Scene; it must not resolve now.
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with self.assertRaises(ContractError):
            await self.submit(
                engine,
                snapshot.revision,
                EnterLocationEffect(location_id="client_briefing"),
            )

    async def test_ending_ids_come_from_v3_anchors(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await self.submit(
            engine,
            snapshot.revision,
            CommitTerminalEndingEffect(ending_id="ending_douglas_departs"),
        )
        after = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertEqual(after.world.ending_id, "ending_douglas_departs")
        self.assertEqual(after.phase, "ended")

    async def test_keeper_capabilities_read_the_v3_collections(self) -> None:
        store, engine, rules = self.build()
        capabilities = await rules.read_keeper_capabilities(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertIn(
            "douglas_true_nature", {item.id for item in capabilities.information}
        )
        self.assertIn("crypt", {item.id for item in capabilities.locations})
        self.assertIn(
            "ending_douglas_departs", {item.id for item in capabilities.endings}
        )
        # Keeper text is what the Agent judges with, and it is not the player half.
        keeper = next(
            item
            for item in capabilities.information
            if item.id == "douglas_true_nature"
        )
        self.assertNotEqual(keeper.content, keeper.summary)


class EventRuleChainingTests(unittest.IsolatedAsyncioTestCase):
    """v3 event rules chain off committed events (阶段 3c, #226 §4 partial)."""

    def setUp(self) -> None:
        self.content = module()

    async def test_a_state_change_fires_the_rule_that_watches_it(self) -> None:
        # locked_study_window_breaks fires once the visit is observed and the
        # window is still locked and unbroken.
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(
                self.content,
                scene_id="kimball_study",
                entities={
                    "study_window": {"locked": True, "broken": False},
                    "cemetery_figure": {"visit_observed": False},
                },
            ),
        )
        engine = AdjudicationEngineService(store)
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="observe-visit",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="看到有人来过",
                    target=ActionTarget(kind="entity", id="cemetery_figure"),
                    method=ActionMethod(family="observe", description="看到有人来过"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="cemetery_figure",
                            key="visit_observed",
                            value=True,
                        ),
                    ),
                ),
            )
        )
        state = store.inspect_state(ROOM)
        self.assertTrue(state.entities["study_window"]["broken"])
        self.assertIn(
            "rule.triggered",
            {event.type for event in store.inspect_domain_events(ROOM)},
        )

    def test_a_rule_walk_stops_honestly_at_a_check(self) -> None:
        # first_sight_of_douglas marks the flag, then needs a sanity check. The
        # simplified executor commits the effect and reports why it stopped
        # rather than pretending the check happened.
        rule = next(
            item for item in self.content.rules if item.id == "first_sight_of_douglas"
        )
        walk = walk_rule(rule)
        self.assertEqual(len(walk.effects), 1)
        self.assertEqual(walk.suspended_kind, "check")

    def test_an_unregistered_predicate_never_fires_a_rule(self) -> None:
        # Predicates are a closed set (#226 §1): an unknown name must read false,
        # not crash and not accidentally match.
        state = game_state(self.content)
        self.assertFalse(
            evaluate_condition(
                PredicateCondition(predicate="not_registered", args={}),
                state=state,
                actor_id=ACTOR,
            )
        )


class RuleOwnedCheckTests(unittest.IsolatedAsyncioTestCase):
    """A named rule owns the outcome of the check the Agent proposed (#226 §5)."""

    def setUp(self) -> None:
        self.content = module()

    def build(self, rolls, **overrides):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, scene_id="library", **overrides),
        )
        return (
            store,
            AdjudicationEngineService(
                store, dice=DiceRoller(SequenceDiceSource(rolls))
            ),
            RuleEngineService(store),
        )

    async def run_rule_check(self, rolls, option_id="library-use"):
        store, engine, rules = self.build(rolls)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="rule-owned-1",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="查阅旧报",
                    target=ActionTarget(kind="entity", id="newspaper_archive"),
                    method=ActionMethod(family="research", description="查阅旧报"),
                    rule_decision=RuleDecisionRef(
                        rule_id="research_library_archive", option_id=option_id
                    ),
                    check=RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="library-use",
                                skill_id="library-use",
                                difficulty="regular",
                                method_summary="按年份检索",
                                player_safe_reason="使用图书馆使用",
                            ),
                        )
                    ),
                    # Deliberately wrong: the rule must override these.
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )
        pending = execution.pending_decision
        assert pending is not None
        resolved = await engine.decide(
            CheckDecisionRequest(
                request_id="rule-owned-1:select",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id="library-use"),
            )
        )
        return store, engine, rules, resolved

    async def test_success_commits_the_rules_effects_not_the_agents(self) -> None:
        # The Agent sent empty effect lists; the release of the newspaper report
        # can only come from the rule's success route.
        store, engine, rules, resolved = await self.run_rule_check([5])
        self.assertEqual(resolved.outcome, "success")
        state = store.inspect_state(ROOM)
        self.assertIn("cemetery_dance_report", state.discovered_facts)

    async def test_failure_routes_somewhere_else_entirely(self) -> None:
        store, engine, rules, resolved = await self.run_rule_check([100])
        # A fumble offers post-roll options; accept to settle it as a failure.
        self.assertEqual(resolved.status, "awaiting_post_roll_decision")
        check_run = resolved.check_run
        assert check_run is not None
        final = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="rule-owned-1:accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=resolved.view_revision,
                check_id=check_run.check_id,
                check_version=check_run.version,
                option_id="accept-current",
            )
        )
        self.assertEqual(final.outcome, "failure")
        state = store.inspect_state(ROOM)
        self.assertNotIn("cemetery_dance_report", state.discovered_facts)

    async def test_an_invented_rule_id_is_refused(self) -> None:
        store, engine, rules = self.build([5])
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with self.assertRaises(ContractError):
            await engine.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id="invented-rule",
                        source_revision=snapshot.revision,
                        actor_id=ACTOR,
                        summary="乱编一条规则",
                        target=ActionTarget(kind="entity", id="newspaper_archive"),
                        method=ActionMethod(family="research", description="x"),
                        rule_decision=RuleDecisionRef(
                            rule_id="no_such_rule", option_id="whatever"
                        ),
                        check=NoAdjudicationCheck(),
                        success_effects=(),
                    ),
                )
            )

    async def test_an_option_the_rule_never_declared_is_refused(self) -> None:
        store, engine, rules = self.build([5])
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with self.assertRaises(ContractError):
            await engine.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id="invented-option",
                        source_revision=snapshot.revision,
                        actor_id=ACTOR,
                        summary="选一个不存在的候选",
                        target=ActionTarget(kind="entity", id="newspaper_archive"),
                        method=ActionMethod(family="research", description="x"),
                        rule_decision=RuleDecisionRef(
                            rule_id="research_library_archive",
                            option_id="by_smell",
                        ),
                        check=NoAdjudicationCheck(),
                        success_effects=(),
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
