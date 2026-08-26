"""Projecting a v3 module (#212 §7 / §4 / §8).

Driven by the real 追书人 v3 fixture rather than a toy module, because the
things most likely to break — a gated crypt, a study that is a room, an entity
placed by `located_in` — only exist at that scale.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdjudicationValidationError,
    AdvanceWorldTimeEffect,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    CommitTerminalEndingEffect,
    ConsumeEntityEffect,
    ContractError,
    EnsureRuntimeEntityEffect,
    EnterLocationEffect,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    LocationKnowledge,
    ModuleContentV3,
    MoveEntityEffect,
    NoAdjudicationCheck,
    PersistenceIntent,
    PlayerViewScope,
    PostRollDecisionRequest,
    PredicateCondition,
    RequiredAdjudicationCheck,
    RevealInformationEffect,
    RuleDecisionRef,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
    TimeSegment,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
    WorldTimePoint,
    WorldTimeState,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.navigation import resolve_location_target
from collaboration_framework.engine.projection_v3 import location_breadcrumbs
from collaboration_framework.engine.rules_v3 import evaluate_condition, walk_rule
from tests.time_fixtures import day_cycle_module

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
                    # 属性和技能分开存，和真实建卡一致：STR 检定要走 attributes。
                    "attributes": {"STR": 45},
                    "occupation": "私家侦探",
                },
                # 真实建卡会从 derived_stats["SAN"] 填进来（room.py 的
                # `_character_runtime_resources`）。被动理智检定的目标值就读这里。
                resources=ActorResources(san=55, luck=50),
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
        # 会客室是金博尔宅内的一个房间，面包屑必须带上这一层包含关系。
        self.assertEqual(
            [item.name for item in snapshot.location_context.breadcrumbs],
            ["阿诺兹堡", "金博尔宅", "托马斯的会客室"],
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

    async def test_canon_item_stays_behind_its_entity_visibility_gate(self) -> None:
        """一个 Canon 物品仍然是一个 Canon Entity，必须走同一道可见性门禁。

        日记的 `visibility_conditions` 要求 `found=true`。物品投影若只看
        ItemKnowledge，就会把它当作散落物品直接摆进书房——玩家还没找到，
        它已经出现在场景物品列表里了。
        """

        seeded = create_initial_game_state(
            module_content=self.content,
            room_id=ROOM,
            actors={
                ACTOR: ActorState(
                    player_id=PLAYER,
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                )
            },
        )
        # 日记确实被播种成了 ItemInstance，否则这条测试会因为「根本没有物品」而假绿。
        self.assertIn("douglas_diary", seeded.item_instances)

        hidden = seeded.model_copy(update={"scene_id": "kimball_study"}, deep=True)
        snapshot = await self.project(hidden)
        self.assertNotIn(
            "douglas_diary", {item.id for item in snapshot.scene.loose_items}
        )

        found = hidden.model_copy(
            update={
                "entities": {
                    **hidden.entities,
                    "douglas_diary": {
                        **hidden.entities.get("douglas_diary", {}),
                        "found": True,
                    },
                }
            },
            deep=True,
        )
        revealed = await self.project(found)
        self.assertIn(
            "douglas_diary", {item.id for item in revealed.scene.loose_items}
        )

    async def test_stolen_books_are_gated_to_the_opened_crypt(self) -> None:
        """The physical books start in the crypt and stay hidden behind its gate."""

        seeded = create_initial_game_state(
            module_content=self.content,
            room_id=ROOM,
            actors={
                ACTOR: ActorState(
                    player_id=PLAYER,
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                )
            },
        )
        study = await self.project(
            seeded.model_copy(update={"scene_id": "kimball_study"}, deep=True)
        )
        unopened_crypt = await self.project(
            seeded.model_copy(update={"scene_id": "crypt"}, deep=True)
        )
        opened_entities = {
            **seeded.entities,
            "crypt_entrance": {
                **seeded.entities["crypt_entrance"],
                "slab_moved": True,
            },
        }
        opened_crypt = await self.project(
            seeded.model_copy(
                update={"scene_id": "crypt", "entities": opened_entities}, deep=True
            )
        )

        self.assertNotIn(
            "missing_books", {item.id for item in study.scene.loose_items}
        )
        self.assertNotIn(
            "missing_books", {item.id for item in study.scene.visible_entities}
        )
        self.assertNotIn(
            "missing_books", {item.id for item in unopened_crypt.scene.loose_items}
        )
        self.assertNotIn(
            "missing_books", {item.id for item in unopened_crypt.scene.visible_entities}
        )
        self.assertIn(
            "missing_books", {item.id for item in opened_crypt.scene.loose_items}
        )
        self.assertIn(
            "missing_books", {item.id for item in opened_crypt.scene.visible_entities}
        )

    async def test_character_equipment_is_carried_from_the_first_revision(self) -> None:
        """角色卡上的装备必须在开局就是真的物品。

        否则背包一开始是空的，等到绳子或手电真正用得上时才凭空出现——玩家看到
        的就是一个时空背包。
        """

        seeded = create_initial_game_state(
            module_content=self.content,
            room_id=ROOM,
            actors={
                ACTOR: ActorState(
                    player_id=PLAYER,
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                    state={
                        "skills": {"spot-hidden": 60},
                        "equipment": ["手电筒", "笔记本与钢笔", "", "手电筒"],
                    },
                )
            },
        )

        snapshot = await self.project(seeded)

        self.assertEqual(
            [item.name for item in snapshot.inventory], ["手电筒", "笔记本与钢笔"]
        )
        self.assertTrue(
            all(item.source_label == "随身携带" for item in snapshot.inventory)
        )
        # 是自己带着的，不是散落在开场地点等人来捡。
        self.assertEqual(snapshot.scene.loose_items, ())

    async def test_agent_created_npc_and_item_custody_lifecycle(self) -> None:
        state = game_state(self.content, scene_id="library")
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=state)
        engine = RuleEngineService(store)
        adjudicator = AdjudicationEngineService(store)
        scope = PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)

        async def commit(
            request_id: str,
            *effects,
            family: str = "action",
            persistence_intent: PersistenceIntent = "none",
        ) -> None:
            before = await engine.read(scope)
            await adjudicator.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id=request_id,
                        source_revision=before.revision,
                        actor_id=ACTOR,
                        summary=request_id,
                        target=ActionTarget(kind="location", id="library"),
                        method=ActionMethod(family=family, description=request_id),
                        persistence_intent=persistence_intent,
                        check=NoAdjudicationCheck(),
                        success_effects=effects,
                    ),
                )
            )

        await commit(
            "create-and-take",
            EnsureRuntimeEntityEffect(
                entity_id="runtime_librarian",
                entity_kind="npc",
                name="图书馆管理员",
                location_id="library",
            ),
            EnsureRuntimeEntityEffect(
                entity_id="ordinary_pebble",
                entity_kind="object",
                name="一枚普通石子",
                location_id="library",
            ),
            MoveEntityEffect(entity_id="ordinary_pebble", holder_actor_id=ACTOR),
            family="pick_up",
            persistence_intent="inventory",
        )

        carried = await engine.read(scope)
        self.assertIn(
            "runtime_librarian",
            {entity.id for entity in carried.scene.visible_entities},
        )
        self.assertEqual([item.id for item in carried.inventory], ["ordinary_pebble"])
        self.assertEqual(carried.self_actor.equipment, ("一枚普通石子",))
        self.assertNotIn(
            "ordinary_pebble",
            {entity.id for entity in carried.scene.visible_entities},
        )
        committed = store.inspect_state(ROOM)
        self.assertIn("runtime_librarian", committed.runtime_entities)
        self.assertNotIn("ordinary_pebble", committed.runtime_entities)
        self.assertEqual(
            committed.item_instances["ordinary_pebble"].custody.kind,
            "actor_inventory",
        )
        capabilities = await engine.read_keeper_capabilities(scope)
        pebble = next(
            item for item in capabilities.entities if item.id == "ordinary_pebble"
        )
        self.assertEqual(pebble.holder_actor_id, ACTOR)

        await commit(
            "throw-pebble",
            MoveEntityEffect(entity_id="ordinary_pebble", location_id="library"),
        )
        placed = await engine.read(scope)
        self.assertEqual(placed.inventory, ())
        self.assertEqual(
            [item.id for item in placed.scene.loose_items],
            ["ordinary_pebble"],
        )

        await commit(
            "consume-pebble",
            ConsumeEntityEffect(entity_id="ordinary_pebble"),
        )
        consumed = await engine.read(scope)
        self.assertEqual(consumed.inventory, ())
        self.assertEqual(consumed.scene.loose_items, ())
        self.assertEqual(
            store.inspect_state(ROOM).item_instances["ordinary_pebble"].state.status,
            "retired",
        )

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

    async def test_undiscovered_cemetery_secrets_never_enter_the_player_view(
        self,
    ) -> None:
        hidden = await self.project(game_state(self.content, scene_id="cemetery"))
        visible_ids = {entity.id for entity in hidden.scene.visible_entities}
        self.assertNotIn("favorite_grave", visible_ids)
        self.assertNotIn("crypt_entrance", visible_ids)
        projected_text = hidden.model_dump_json()
        self.assertNotIn("连续读上数小时", projected_text)
        self.assertNotIn("沉重石板遮住了向下的通道", projected_text)

        revealed = await self.project(
            game_state(
                self.content,
                scene_id="cemetery",
                entities={
                    "favorite_grave": {"identified": True},
                    "crypt_entrance": {"discovered": True},
                },
            )
        )
        revealed_ids = {entity.id for entity in revealed.scene.visible_entities}
        self.assertIn("favorite_grave", revealed_ids)
        self.assertIn("crypt_entrance", revealed_ids)

    async def test_moving_an_entity_moves_where_it_is_projected(self) -> None:
        # `located_in` is the module's placement; runtime state overrides it, which
        # is what `move_entity` writes.
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"douglas_diary": {"location_id": "cemetery", "found": True}},
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
            entities={"douglas_diary": {"holder_actor_id": ACTOR, "found": True}},
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
        # 玩家只看到模组允许他看到的措辞：12:00 没声明 label，走 afternoon
        # 的缺省推导。精确的 day_index / hour_of_day 留在权威状态里。
        self.assertEqual(snapshot.world.time_label, "下午")
        self.assertEqual(snapshot.scene.time, "下午")
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

    async def test_runtime_location_is_contained_by_region_not_by_its_anchor(
        self,
    ) -> None:
        """连接锚点是可达性，不是包含关系。

        玩家站在书房里让 Agent 开一家旅店时，锚点就是书房。按锚点当父节点，
        地图会把旅店画进金博尔宅里 —— 正是 #212 §7.3 要求分开的两张图。
        """

        state = game_state(
            self.content,
            scene_id="inn",
            runtime_locations={
                "inn": {
                    "name": "镇上的寄宿屋",
                    "connected_location_id": "kimball_study",
                }
            },
            party_location_knowledge={
                "inn": LocationKnowledge(
                    location_id="inn", existence="known", localization="located"
                )
            },
        )

        snapshot = await self.project(state)
        inn = next(
            location for location in snapshot.known_locations if location.id == "inn"
        )
        self.assertEqual(inn.parent_location_id, "arnoldsburg")
        self.assertEqual(
            [item.name for item in snapshot.location_context.breadcrumbs],
            ["阿诺兹堡", "镇上的寄宿屋"],
        )

    def _inn_state(self) -> GameState:
        """站在 Agent 新开的旅店里 —— 玩家直奔旅店，中途的街道没有单独进过。"""

        return game_state(
            self.content,
            scene_id="ambient_inn",
            runtime_locations={
                "ambient_inn": {
                    "name": "镇上的旅店",
                    "connected_location_id": "arnoldsburg_streets",
                }
            },
            party_location_knowledge={
                "ambient_inn": LocationKnowledge(
                    location_id="ambient_inn",
                    existence="known",
                    localization="located",
                    visited=True,
                )
            },
        )

    async def test_standing_in_a_runtime_location_keeps_the_rest_of_the_map(
        self,
    ) -> None:
        """登记旅店时也就铺好了路，进去之后整张镇子还在。

        已知地图是每次从当前场景现推出来的。Runtime Location 没有任何 authored
        edge，反向那半条路一旦缺席，图就只剩脚下这一个点——玩家开一家旅店，
        阿诺兹堡的街道、图书馆、墓地全部从地图上消失。
        """

        snapshot = await self.project(self._inn_state())

        known = {location.id for location in snapshot.known_locations}
        self.assertIn("ambient_inn", known)
        self.assertLessEqual(
            {"arnoldsburg", "arnoldsburg_streets", "library", "cemetery"},
            known,
        )

    async def test_the_way_out_of_a_runtime_location_is_one_the_engine_accepts(
        self,
    ) -> None:
        """投影出来的出口必须是导航真的走得通的那一条。"""

        state = self._inn_state()
        snapshot = await self.project(state)

        back = next(
            item
            for item in snapshot.scene.available_exits
            if item.destination and item.destination.scene_id == "arnoldsburg_streets"
        )
        self.assertEqual(back.name, "阿诺兹堡街道")
        for target_id in ("arnoldsburg_streets", "library"):
            resolution = resolve_location_target(
                self.content,
                state,
                actor_id=ACTOR,
                target_id=target_id,
            )
            self.assertEqual(resolution.status, "known_reachable")


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

    def condition_night_watch_on_night(self) -> None:
        """Give the real Paper Chase candidate the small engine extension under test."""

        rules = []
        for rule in self.content.rules:
            if rule.id != "keep_night_watch":
                rules.append(rule)
                continue
            rules.append(
                rule.model_copy(
                    update={
                        "trigger": rule.trigger.model_copy(
                            update={
                                "when": PredicateCondition(
                                    predicate="time_of_day_is",
                                    args={"value": "night"},
                                )
                            },
                            deep=True,
                        )
                    },
                    deep=True,
                )
            )
        self.content = self.content.model_copy(update={"rules": tuple(rules)}, deep=True)

    @staticmethod
    def at_time(point_id: str, hour: int, segment: TimeSegment) -> WorldTimeState:
        return WorldTimeState(
            current_point_id=point_id,
            current=WorldTimePoint(day_index=0, hour_of_day=hour),
            current_time_segment=segment,
        )

    async def test_agent_match_when_filters_the_published_candidate(self) -> None:
        self.condition_night_watch_on_night()

        async def candidates(world_time: WorldTimeState) -> set[str]:
            _, _, rules = self.build(
                scene_id="surveillance_point",
                world_time=world_time,
            )
            view = await rules.read_keeper_capabilities(
                PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
            )
            return {candidate.rule_id for candidate in view.rule_candidates}

        day = await candidates(self.at_time("hour_06", 6, "morning"))
        night = await candidates(self.at_time("hour_18", 18, "evening"))

        self.assertNotIn("keep_night_watch", day)
        self.assertIn("keep_night_watch", night)

    async def test_agent_match_when_is_rechecked_on_submission(self) -> None:
        """Naming a hidden or stale candidate id cannot bypass its state condition."""

        self.condition_night_watch_on_night()
        store, engine, rules = self.build(
            scene_id="surveillance_point",
            world_time=self.at_time("hour_06", 6, "morning"),
        )
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

        with self.assertRaises(AdjudicationValidationError) as rejected:
            await engine.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id="night-watch-during-day",
                        source_revision=snapshot.revision,
                        actor_id=ACTOR,
                        summary="白天点名夜间监视规则",
                        target=ActionTarget(kind="entity", id="surveillance_area"),
                        method=ActionMethod(family="surveil", description="监视环境"),
                        rule_decision=RuleDecisionRef(
                            rule_id="keep_night_watch",
                            option_id="luck",
                        ),
                        check=NoAdjudicationCheck(),
                        success_effects=(),
                        failure_effects=(),
                    ),
                )
            )

        self.assertEqual(rejected.exception.result.code, "RULE_OUT_OF_SCOPE")
        self.assertEqual(len(store.inspect_domain_events(ROOM)), 0)

    async def test_active_luck_check_reads_the_actor_resource(self) -> None:
        """Luck is an ActorResource, not a synthetic entry in the skill map."""

        store, engine, rules = self.build(
            scene_id="surveillance_point",
            world_time=self.at_time("hour_18", 18, "evening"),
            entities={
                "case_tracker": {"night_watch_checked": False},
                "cemetery_figure": {"visit_observed": False},
            },
        )
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="night-watch-luck-resource",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="在夜间监视区域留意动静",
                    target=ActionTarget(kind="entity", id="surveillance_area"),
                    method=ActionMethod(family="surveil", description="监视环境"),
                    rule_decision=RuleDecisionRef(
                        rule_id="keep_night_watch",
                        option_id="luck",
                    ),
                    check=RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="luck",
                                skill_id="luck",
                                difficulty="regular",
                                method_summary="留守观察",
                                player_safe_reason="规则要求进行幸运检定",
                            ),
                        )
                    ),
                ),
            )
        )

        pending = execution.pending_decision
        assert pending is not None
        self.assertEqual(pending.options[0].display_name, "幸运")
        self.assertEqual(pending.options[0].target_value, 50)
        self.assertNotIn("luck", store.inspect_state(ROOM).actors[ACTOR].state["skills"])

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

    async def test_greeting_a_neighbour_is_repairable_not_a_dead_turn(self) -> None:
        """#313 回归：动作族不同也不能阻断结构范围匹配的规则。

        菜单是按「玩家站在哪」发布的，所以 `question_neighbors` 会出现在候选里；
        `target=lyla` 仍需在提交时复查，但模型把打招呼归成 `social` 不再导致
        `RULE_OUT_OF_SCOPE`。
        """

        store, engine, rules = self.build(scene_id="neighborhood")
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        capabilities = await rules.read_keeper_capabilities(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        published = {item.rule_id for item in capabilities.rule_candidates}
        self.assertIn("question_neighbors", published)

        greeting = ActionAdjudication(
            request_id="greet-neighbour-313",
            source_revision=snapshot.revision,
            actor_id=ACTOR,
            summary="跟邻居打个招呼",
            target=ActionTarget(kind="entity", id="lyla"),
            method=ActionMethod(family="social", description="打招呼"),
            check=NoAdjudicationCheck(),
            rule_decision=RuleDecisionRef(
                rule_id="question_neighbors", option_id="fast-talk"
            ),
        )
        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM, player_id=PLAYER, adjudication=greeting
            )
        )
        self.assertEqual(execution.status, "resolved")
        self.assertGreater(self.store_events(store), 0)

    @staticmethod
    def store_events(store: InMemoryEngineStore) -> int:
        return len(store.inspect_domain_events(ROOM))

    async def test_keeper_capabilities_publish_the_v3_world_target(self) -> None:
        """v3 侧同样要发 world_id，否则「今天周几」这类输入没有合法目标（#313）。"""

        store, engine, rules = self.build(scene_id="neighborhood")
        scope = PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        capabilities = await rules.read_keeper_capabilities(scope)
        self.assertEqual(capabilities.world_id, self.content.world_ref)

        snapshot = await rules.read(scope)
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="ask-the-date-313",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="今天周几？",
                    target=ActionTarget(kind="world", id=capabilities.world_id or ""),
                    method=ActionMethod(family="talk", description="询问日期"),
                    check=NoAdjudicationCheck(),
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

    async def test_sleeping_until_eight_walks_the_timeline_one_point_at_a_time(
        self,
    ) -> None:
        """「睡一觉，到晚上八点」= 12 点 → 18 点 → 20 点，两跳，两个事件。

        一次 advance_world_time 只走一个点，中间的 hour_18 不能被跳过：挂在
        `time.point_entered` 上的规则，跳过点就等于跳过规则。

        走的是时间线 fixture 而不是真实模组：这条断言只关心引擎怎么走点，而
        《追书人》的 time_policy 是模组内容，会随模组改版而变（#451 已把它收敛成
        昼夜两点，20 点不复存在）。
        """

        content = day_cycle_module()
        store = InMemoryEngineStore()
        store.register_room(
            module_content=content, initial_state=game_state(content)
        )
        engine = AdjudicationEngineService(store)
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertEqual(snapshot.world.time_label, "下午")

        await self.submit(
            engine,
            snapshot.revision,
            AdvanceWorldTimeEffect(to_point_id="hour_18"),
            AdvanceWorldTimeEffect(to_point_id="hour_20"),
            target=ActionTarget(kind="location", id="only_room"),
        )

        after = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertEqual(after.world.time_label, "晚上")

        # 两跳都真的发生过——这一点由权威事件负责证明，不由玩家侧投影负责：
        # hour_18 与 hour_20 同为 evening，玩家看到的措辞本来就该一样。
        entered = [
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "time.point_entered"
        ]
        self.assertEqual(
            [event.payload["point_id"] for event in entered], ["hour_18", "hour_20"]
        )

    async def test_advance_world_time_refuses_a_point_that_is_not_next(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

        with self.assertRaises(ContractError):
            await self.submit(
                engine,
                snapshot.revision,
                # 12 点的下一个点是 18 点，不是 20 点。
                AdvanceWorldTimeEffect(to_point_id="hour_20"),
            )

    async def test_party_room_cannot_advance_time_without_the_ready_round(
        self,
    ) -> None:
        """时间是共享状态：一个人不能替全队睡到天黑（#245 §四）。"""

        store, engine, rules = self.build(
            actors={
                ACTOR: ActorState(
                    player_id=PLAYER,
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                ),
                "actor_2": ActorState(
                    player_id="player_2",
                    name="李探员",
                    source_character_id="character_v3b",
                    source_character_version=1,
                ),
            }
        )
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

        with self.assertRaises(ContractError):
            await self.submit(engine, snapshot.revision, AdvanceWorldTimeEffect())

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

    async def test_v3_ending_requires_the_reviewable_draft_api(self) -> None:
        store, engine, rules = self.build()
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with self.assertRaisesRegex(ContractError, "EndingDraft"):
            await self.submit(
                engine,
                snapshot.revision,
                CommitTerminalEndingEffect(ending_id="ending_douglas_departs"),
            )
        self.assertEqual(store.inspect_state(ROOM).phase, "playing")

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
        self.assertEqual(capabilities.world_profile, self.content.world_profile)
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
        # locked_study_window_breaks fires once he has actually got inside and
        # taken the books, with the window still locked and unbroken. #451 moved
        # the trigger off "you saw him": being seen at the watch point and
        # climbing through the study window happen at different moments.
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(
                self.content,
                scene_id="kimball_study",
                entities={
                    "study_window": {"locked": True, "broken": False},
                    "case_tracker": {"books_taken": False},
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
                    summary="确认他取走了书",
                    target=ActionTarget(kind="entity", id="case_tracker"),
                    method=ActionMethod(family="observe", description="清点少掉的书"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="case_tracker",
                            key="books_taken",
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

    async def run_grave_tracking(self, roll: int):
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"favorite_grave": {"identified": True}},
        )
        actor = state.actors[ACTOR]
        actors = dict(state.actors)
        actors[ACTOR] = actor.model_copy(
            update={
                "state": {
                    **actor.state,
                    "skills": {**actor.state["skills"], "track": 90},
                }
            },
            deep=True,
        )
        state = state.model_copy(update={"actors": actors}, deep=True)
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=state)
        engine = AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([roll]))
        )
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        pending_execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"track-grave-{roll}",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="追踪墓碑附近的痕迹",
                    target=ActionTarget(kind="entity", id="favorite_grave"),
                    method=ActionMethod(family="track", description="追踪痕迹"),
                    rule_decision=RuleDecisionRef(
                        rule_id="inspect_grave_area", option_id="track"
                    ),
                    check=RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="track",
                                skill_id="track",
                                difficulty="regular",
                                method_summary="追踪墓碑附近的痕迹",
                                player_safe_reason="使用追踪",
                            ),
                        )
                    ),
                ),
            )
        )
        pending = pending_execution.pending_decision
        assert pending is not None
        resolved = await engine.decide(
            CheckDecisionRequest(
                request_id=f"track-grave-{roll}:select",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=pending_execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id="track"),
            )
        )
        check_run = resolved.check_run
        assert check_run is not None
        resolved = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id=f"track-grave-{roll}:accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=resolved.view_revision,
                check_id=check_run.check_id,
                check_version=check_run.version,
                option_id="accept-current",
            )
        )
        return store, resolved

    async def test_discovering_crypt_entrance_produces_required_safe_evidence(self) -> None:
        store, execution = await self.run_grave_tracking(25)

        self.assertIs(store.inspect_state(ROOM).entities["crypt_entrance"]["discovered"], True)
        self.assertEqual(len(execution.narration_evidence), 1)
        evidence = execution.narration_evidence[0]
        self.assertEqual(evidence.kind, "entity_discovered")
        self.assertEqual(evidence.subject_id, "crypt_entrance")
        self.assertEqual(evidence.subject_name, "石板下的地穴入口")
        self.assertIn("沉重石板", evidence.description)
        self.assertTrue(evidence.required_in_narration)
        self.assertIn(evidence.ref, execution.public_event_refs)

    async def test_failed_tracking_produces_no_crypt_discovery_evidence(self) -> None:
        store, execution = await self.run_grave_tracking(95)

        self.assertIsNot(
            store.inspect_state(ROOM).entities.get("crypt_entrance", {}).get("discovered"),
            True,
        )
        self.assertEqual(execution.narration_evidence, ())

    async def test_non_discovery_action_skips_player_projection_for_narration_evidence(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, scene_id="cemetery"),
        )
        engine = AdjudicationEngineService(store)
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        with patch(
            "collaboration_framework.engine.adjudication.project_v3",
            side_effect=AssertionError("projection should be skipped"),
        ):
            execution = await engine.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id="ordinary-action-no-discovery",
                        source_revision=snapshot.revision,
                        actor_id=ACTOR,
                        summary="观察墓地",
                        target=ActionTarget(kind="location", id="cemetery"),
                        method=ActionMethod(family="observe", description="观察墓地"),
                        check=NoAdjudicationCheck(),
                        success_effects=(),
                    ),
                )
            )
        self.assertEqual(execution.narration_evidence, ())

    async def _submit_rule_decision(
        self,
        *,
        scene_id: str,
        rule_id: str,
        option_id: str,
        target: ActionTarget,
        family: str,
    ):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, scene_id=scene_id),
        )
        engine = AdjudicationEngineService(store, dice=DiceRoller(SequenceDiceSource([5])))
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="scope-probe",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="越界提交探测",
                    target=target,
                    method=ActionMethod(family=family, description="探测"),
                    rule_decision=RuleDecisionRef(rule_id=rule_id, option_id=option_id),
                    check=NoAdjudicationCheck(),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )

    async def test_rule_without_a_check_still_commits_its_effects(self) -> None:
        """纯效果规则也必须真的生效（#226 §5），而被动检定必须真的出现（#398）。

        `enter_crypt/proceed` 不掷骰，整条分支就是它的后果。此前 `_owned_effects`
        返回空元组、注释声称「链在提交时已经跑过了」，但没有任何地方跑它。

        这条链还是失败案例 B 的最短复现：分支的第三个效果把
        `cemetery_figure.true_form_seen` 翻成 true，`first_sight_of_douglas`
        随即要求一次被动理智检定。#398 之前**检定静默丢失**——规则前面的效果照常
        提交，骰子却从不出现，世界就这么继续往下走。现在它在检定处停住，结算完
        才继续跑父动作剩下的效果。
        """

        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, scene_id="crypt"),
        )
        engine = AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([5, 5]))
        )
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="enter-crypt-1",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary="进入地穴",
                    target=ActionTarget(kind="entity", id="crypt_entrance"),
                    method=ActionMethod(family="enter", description="进入地穴"),
                    rule_decision=RuleDecisionRef(
                        rule_id="enter_crypt", option_id="proceed"
                    ),
                    # 不掷骰的分支：Agent 不该为了凑格式编一个技能出来。
                    check=NoAdjudicationCheck(),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )

        # 停在规则要求的那次检定上，而不是一路跑到底。
        self.assertEqual(execution.status, "awaiting_skill_choice")
        pending = execution.pending_decision
        assert pending is not None
        # 规则自己指定技能，所以菜单只有一条；规则强制的检定也不能取消。
        self.assertEqual(len(pending.options), 1)
        self.assertEqual(pending.options[0].display_name, "理智")
        self.assertEqual(pending.options[0].target_value, 55)
        self.assertFalse(pending.allow_cancel)

        state = store.inspect_state(ROOM)
        figure = state.entities["cemetery_figure"]
        # 检定之前的效果照常提交……
        self.assertIs(state.entities["crypt_entrance"]["entered"], True)
        self.assertIs(figure["sighted"], True)
        self.assertIs(figure["true_form_seen"], True)
        self.assertIs(
            state.entities["case_tracker"]["first_ghoul_sight_resolved"], True
        )
        # ……但触发检定之后的那个效果被屏障挡住了，等结算。
        self.assertNotIn("willing_to_talk", figure)

        rolled = await engine.decide(
            CheckDecisionRequest(
                request_id="enter-crypt-1-san",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
            )
        )
        # 被动检定走的就是既有的检定工作流，奖惩骰确认这一步也一样。
        self.assertEqual(rolled.status, "awaiting_post_roll_decision")
        assert rolled.check_run is not None
        self.assertEqual(rolled.check_run.selected_skill_name, "理智")
        resolved = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="enter-crypt-1-san-accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=rolled.view_revision,
                check_id=rolled.check_run.check_id,
                check_version=rolled.check_run.version,
                option_id="accept-current",
            )
        )

        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.outcome, "success")
        state = store.inspect_state(ROOM)
        # 规则稳定之后，父动作剩下的效果接着跑完。
        self.assertIs(state.entities["cemetery_figure"]["willing_to_talk"], True)
        # Agenda 是游标，不是记录：跑完就不该留在 state 里（#398 §阶段一）。
        self.assertEqual(state.rule_agendas, {})

    async def test_the_crypt_endgame_is_reachable_and_commits(self) -> None:
        """把地穴终局整段钉住：搬石板 → 进地穴 → 与身影对话 → 主线收束。

        这段此前有两处各自独立的断点，任一都足以让模组「玩到中段就断」：

        1. `move_crypt_slab` 的 scope 误写成 `crypt`，而进地穴的边正是由它置位的
           `slab_moved` 把门——搬石板要先在地穴里，闭环，地穴不可达；
        2. 纯效果分支的后果被 `_owned_effects` 丢掉，所以即使进得去，
           `talk_to_figure` 的 `mark_core_resolved` 也不会发生。

        自动化覆盖到这里，验收路径就不必依赖有人手动摸到地穴才发现问题。
        """

        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(
                self.content,
                scene_id="cemetery",
                # 石板已被发现，剩下的就是搬开它。
                entities={"crypt_entrance": {"discovered": True}},
            ),
        )
        # STR 检定取 5，稳定成功。
        engine = AdjudicationEngineService(store, dice=DiceRoller(SequenceDiceSource([5])))
        rules = RuleEngineService(store)

        async def revision() -> str:
            snapshot = await rules.read(
                PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
            )
            return snapshot.revision

        # 1. 在墓地搬开石板（规则自有检定，STR）。
        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="crypt-slab",
                    source_revision=await revision(),
                    actor_id=ACTOR,
                    summary="搬开石板",
                    target=ActionTarget(kind="entity", id="crypt_entrance"),
                    method=ActionMethod(family="move", description="搬开石板"),
                    rule_decision=RuleDecisionRef(
                        rule_id="move_crypt_slab", option_id="STR"
                    ),
                    check=RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="STR",
                                skill_id="STR",
                                difficulty="regular",
                                method_summary="用力搬开石板",
                                player_safe_reason="这是当前可用的做法",
                            ),
                        )
                    ),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )
        pending = execution.pending_decision
        assert pending is not None
        resolved = await engine.decide(
            CheckDecisionRequest(
                request_id="crypt-slab:select",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id="STR"),
            )
        )
        check_run = resolved.check_run
        assert check_run is not None
        await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="crypt-slab:accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=resolved.view_revision,
                check_id=check_run.check_id,
                check_version=check_run.version,
                option_id="accept-current",
            )
        )
        self.assertIs(
            store.inspect_state(ROOM).entities["crypt_entrance"]["slab_moved"], True
        )

        # 2. 石板搬开后，地穴这条隐藏边才真正打开。
        view = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertIn(
            "crypt",
            {
                exit_.destination.scene_id
                for exit_ in view.scene.available_exits
                if exit_.destination
            },
        )

        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="crypt-enter",
                    source_revision=await revision(),
                    actor_id=ACTOR,
                    summary="进入地穴",
                    target=ActionTarget(kind="location", id="crypt"),
                    method=ActionMethod(family="travel", description="进入地穴"),
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id="crypt"),),
                ),
            )
        )
        self.assertEqual(store.inspect_state(ROOM).scene_id, "crypt")

        # 3. 与身影对话：纯效果规则，必须真的收束主线。
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="crypt-talk",
                    source_revision=await revision(),
                    actor_id=ACTOR,
                    summary="与身影交谈",
                    target=ActionTarget(kind="entity", id="cemetery_figure"),
                    method=ActionMethod(family="talk", description="与身影交谈"),
                    rule_decision=RuleDecisionRef(
                        rule_id="talk_to_figure", option_id="proceed"
                    ),
                    check=NoAdjudicationCheck(),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )

        state = store.inspect_state(ROOM)
        self.assertTrue(state.core_resolved)
        self.assertTrue(state.ending_available)
        self.assertIn("douglas_true_nature", state.discovered_facts)
        self.assertIn("douglas_confession", state.discovered_facts)

    async def test_branch_suspended_on_an_executor_refuses_half_effects(self) -> None:
        """停在 invoke_ruleset_action 上的分支不能提交走过的那一半。

        `crypt_stench_on_entry/just_enter` 先要 `coc7.apply_condition` 让调查员
        昏迷，之后才置位「见过身影」。把「无检定」一律当成「整条链跑完」，就会
        跳过昏迷直接记下见过身影——世界停在半截状态。这类分支要等 RuleAgenda
        的恢复侧（R4）落地，现在应当可见地失败。
        """

        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, scene_id="cemetery"),
        )
        engine = AdjudicationEngineService(store, dice=DiceRoller(SequenceDiceSource([5])))
        rules = RuleEngineService(store)
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

        with self.assertRaises(ContractError):
            await engine.submit(
                SubmitAdjudicationRequest(
                    room_id=ROOM,
                    player_id=PLAYER,
                    adjudication=ActionAdjudication(
                        request_id="stench-1",
                        source_revision=snapshot.revision,
                        actor_id=ACTOR,
                        summary="直接钻进石板下的洞口",
                        target=ActionTarget(kind="entity", id="crypt_entrance"),
                        method=ActionMethod(family="enter", description="直接进入"),
                        rule_decision=RuleDecisionRef(
                            rule_id="crypt_stench_on_entry", option_id="just_enter"
                        ),
                        check=NoAdjudicationCheck(),
                        success_effects=(),
                        failure_effects=(),
                    ),
                )
            )

        # 半截状态尤其不能落库：昏迷没生效，就不该记下「见过身影」。
        state = store.inspect_state(ROOM)
        self.assertNotIn("sighted", state.entities.get("cemetery_figure", {}))

    async def test_rule_option_publishes_whether_it_rolls_dice(self) -> None:
        """Agent 必须能分辨哪条分支要掷骰，否则只能编一个技能 id 出来。"""

        async def candidates(scene_id: str):
            store = InMemoryEngineStore()
            store.register_room(
                module_content=self.content,
                initial_state=game_state(self.content, scene_id=scene_id),
            )
            view = await RuleEngineService(store).read_keeper_capabilities(
                PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
            )
            return {item.rule_id: item for item in view.rule_candidates}

        # 地穴内的 proceed 类选项不掷骰。
        in_crypt = await candidates("crypt")
        self.assertFalse(in_crypt["enter_crypt"].options[0].requires_check)

        # 搬石板要掷 STR，而它属于墓地——石板在墓地，不在地穴里。
        at_cemetery = await candidates("cemetery")
        self.assertTrue(at_cemetery["move_crypt_slab"].options[0].requires_check)
        self.assertNotIn("move_crypt_slab", in_crypt)

    async def test_rule_decision_from_another_location_is_refused(self) -> None:
        """候选按场景发布，提交也必须按场景复查。

        `research_library_archive` 的 scope 只覆盖图书馆。站在墓地却点名它，
        等于把另一个地点的规则后果搬到这里来——存在性校验拦不住这件事。
        """

        with self.assertRaises(ContractError):
            await self._submit_rule_decision(
                scene_id="cemetery",
                rule_id="research_library_archive",
                option_id="library-use",
                target=ActionTarget(kind="entity", id="newspaper_archive"),
                family="research",
            )

    async def test_rule_decision_with_a_target_outside_scope_is_refused(self) -> None:
        """规则绑定的是档案，不是守墓人；换个目标就不该还算同一条规则。"""

        with self.assertRaises(ContractError):
            await self._submit_rule_decision(
                scene_id="library",
                rule_id="research_library_archive",
                option_id="library-use",
                target=ActionTarget(kind="entity", id="melodias"),
                family="research",
            )

    async def test_rule_decision_with_a_foreign_action_family_is_admitted(self) -> None:
        """开放动作族只作参考，结构范围匹配时不能阻断规则。"""

        execution = await self._submit_rule_decision(
            scene_id="crypt",
            rule_id="enter_crypt",
            option_id="proceed",
            target=ActionTarget(kind="entity", id="crypt_entrance"),
            family="travel",
        )
        self.assertIn(execution.status, {"resolved", "awaiting_skill_choice"})

    async def test_rule_decision_with_a_foreign_family_keeps_target_scope_hard(self) -> None:
        """放宽 family 不得放宽规则声明的目标范围。"""

        with self.assertRaises(ContractError):
            await self._submit_rule_decision(
                scene_id="library",
                rule_id="research_library_archive",
                option_id="library-use",
                target=ActionTarget(kind="entity", id="melodias"),
                family="intimidate",
            )

    async def test_success_commits_the_rules_effects_not_the_agents(self) -> None:
        # The Agent sent empty effect lists; the release of the newspaper report
        # can only come from the rule's success route.
        store, engine, rules, resolved = await self.run_rule_check([5])
        self.assertEqual(resolved.status, "awaiting_post_roll_decision")
        check_run = resolved.check_run
        assert check_run is not None
        resolved = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="rule-owned-1:accept-success",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=resolved.view_revision,
                check_id=check_run.check_id,
                check_version=check_run.version,
                option_id="accept-current",
            )
        )
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
