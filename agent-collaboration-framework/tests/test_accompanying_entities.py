"""随行实体跟着队伍换场景（#516）。

`accompanying_party` 在这之前是《幸福蛙蛙村》的私有布尔值，框架里零引用：规则把
NPC 标成随队同行之后，只有那一条规则自己顺手写的 `move_entity` 会真的搬他，下一次
不命中规则的移动就把他静默留在了上一个场景。玩家的移动措辞是开集，模组不可能把所有
移动规则穷举一遍，所以这件事必须由引擎来做。

这里钉的是引擎侧的那一条语义：`enter_location` 生效时，把所有标了 `accompanying`
且**此刻与队伍同场景**的实体一并带到队伍实际到达的地点。用真实的追书人 fixture 而不是
玩具模组，因为随行要和门禁、多跳路线、物品保管这些既有机制同时成立，而它们只在这个
规模上才真的存在。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    ContractError,
    EnterLocationEffect,
    ItemCustody,
    ModuleContentV3,
    MoveEntityEffect,
    NoAdjudicationCheck,
    PlayerViewScope,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    PUBLIC_STATE_KEYS,
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    EngineRuntimeSnapshot,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    committed_results_from_events,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.registry import effects as effect_registry

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)

ROOM = "room_accompanying"
ACTOR = "pc_1"
PLAYER = "player_accompanying"
ACCOMPANYING = effect_registry.ACCOMPANYING_STATE_KEY


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def actors() -> dict[str, ActorState]:
    return {
        ACTOR: ActorState(
            player_id=PLAYER,
            name="陈探员",
            source_character_id="character_v3",
            source_character_version=1,
            state={"skills": {"spot-hidden": 60}, "attributes": {"STR": 45}},
            resources=ActorResources(san=55, luck=50),
        )
    }


def game_state(content: ModuleContentV3, **overrides) -> GameState:
    base = {
        "room_id": ROOM,
        "scene_id": content.initial_state.start_location_id,
        "actors": actors(),
        "entities": {},
    }
    base.update(overrides)
    return GameState(**base)


class AccompanyingEntitiesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.content = module()

    def build(self, **overrides):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=game_state(self.content, **overrides),
        )
        return store, AdjudicationEngineService(store), RuleEngineService(store)

    async def submit(self, engine, rules, *effects, target_id: str, sequence: int = 1):
        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"accompanying-{sequence}",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary=f"前往 {target_id}",
                    target=ActionTarget(kind="location", id=target_id),
                    method=ActionMethod(family="travel", description="沿已知路线移动"),
                    persistence_intent="location",
                    check=NoAdjudicationCheck(),
                    success_effects=effects,
                ),
            )
        )

    async def enter(self, engine, rules, location_id: str, *, sequence: int = 1):
        return await self.submit(
            engine,
            rules,
            EnterLocationEffect(location_id=location_id),
            target_id=location_id,
            sequence=sequence,
        )

    async def mark(self, engine, rules, entity_id: str, *, sequence: int = 1):
        """主持人判断「他跟着走」之后落下的那一笔，走普通的角色状态裁决。

        这条路径本身就是引擎的校验面：`character_state` 意图要求效果落在裁决的
        目标上、键在公开状态白名单里、值在该键允许的取值内。主持人负责判断，
        引擎负责校验并落状态——和其它角色状态一样，随行不需要一条专用通道。
        """

        snapshot = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"accompanying-mark-{sequence}",
                    source_revision=snapshot.revision,
                    actor_id=ACTOR,
                    summary=f"带上 {entity_id}",
                    target=ActionTarget(kind="entity", id=entity_id),
                    method=ActionMethod(family="carry", description="请他一起走"),
                    persistence_intent="character_state",
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id=entity_id,
                            key=ACCOMPANYING,
                            value=True,
                        ),
                    ),
                ),
            )
        )

    @staticmethod
    def placed_at(store, entity_id: str) -> str | None:
        state = store.inspect_state(ROOM)
        payload = state.runtime_entities.get(entity_id) or state.entities.get(
            entity_id, {}
        )
        return payload.get("location_id")

    @staticmethod
    def moves_of(store, entity_id: str):
        return tuple(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "entity.moved"
            and event.payload.get("entity_id") == entity_id
        )

    # --- 跟随 -------------------------------------------------------------- #
    async def test_marked_entity_follows_the_party(self) -> None:
        """标了随行、和队伍同场景的 NPC，跟着队伍到下一个地点。"""

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: True}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertEqual(store.inspect_state(ROOM).scene_id, "arnoldsburg_streets")
        self.assertEqual(self.placed_at(store, "thomas"), "arnoldsburg_streets")

    async def test_follower_is_visible_in_the_destination(self) -> None:
        """跟过去之后要真的出现在那个场景里——否则玩家仍然 @ 不到他。"""

        _store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: True}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        view = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertIn("thomas", {item.id for item in view.scene.visible_entities})

    async def test_follower_moves_in_the_same_commit_as_the_party(self) -> None:
        """随行的 `entity.moved` 紧跟队伍的 `travel.resolved`，同一次提交、序号相邻。

        中间态是能被读到的东西：两次提交之间存在一个 revision，那一刻队伍已经到了而
        NPC 还在原地。验收项要求这一刻不存在。
        """

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: True}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        travel = next(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "travel.resolved"
        )
        (followed,) = self.moves_of(store, "thomas")
        self.assertEqual(followed.sequence, travel.sequence + 1)
        self.assertEqual(followed.client_action_id, travel.client_action_id)
        self.assertEqual(followed.payload["location_id"], "arnoldsburg_streets")
        self.assertEqual(followed.payload["reason"], "accompanying")

    async def test_follower_keeps_following_across_later_moves(self) -> None:
        """随行是一次声明、之后一直有效，不是一次性的搬运。"""

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: True}})

        await self.enter(engine, rules, "arnoldsburg_streets", sequence=1)
        await self.enter(engine, rules, "library", sequence=2)

        self.assertEqual(store.inspect_state(ROOM).scene_id, "library")
        self.assertEqual(self.placed_at(store, "thomas"), "library")

    async def test_runtime_entity_follows_the_party(self) -> None:
        """Agent 中途登记的运行时实体和 Canon 实体走同一条随行路径。"""

        store, engine, rules = self.build(
            runtime_entities={
                "stray_dog": {
                    "name": "跟来的狗",
                    "kind": "npc",
                    "location_id": "thomas_office",
                    ACCOMPANYING: True,
                }
            },
        )

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertEqual(self.placed_at(store, "stray_dog"), "arnoldsburg_streets")

    # --- 不跟随 ------------------------------------------------------------ #
    async def test_unmarked_entity_stays_put(self) -> None:
        store, engine, rules = self.build()

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertIsNone(self.placed_at(store, "thomas"))
        self.assertEqual(self.moves_of(store, "thomas"), ())

    async def test_clearing_the_mark_stops_the_following(self) -> None:
        """`stop_carrying` 一类规则把标记写回 False 之后，人就留在原地。"""

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: False}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertEqual(store.inspect_state(ROOM).scene_id, "arnoldsburg_streets")
        self.assertIsNone(self.placed_at(store, "thomas"))

    async def test_a_truthy_non_boolean_mark_does_not_follow(self) -> None:
        """只有布尔 True 算随行；别的写法在发布期就被拦下，运行期不再猜。"""

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: "yes"}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertIsNone(self.placed_at(store, "thomas"))

    async def test_marked_entity_elsewhere_is_not_teleported(self) -> None:
        """随行是位置关系，不是传送许可：不在队伍身边的人不会凭空出现。"""

        store, engine, rules = self.build(entities={"melodias": {ACCOMPANYING: True}})

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertIsNone(self.placed_at(store, "melodias"))

    async def test_consumed_entity_does_not_follow(self) -> None:
        store, engine, rules = self.build(
            entities={"thomas": {ACCOMPANYING: True, "consumed": True}},
        )

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertIsNone(self.placed_at(store, "thomas"))

    async def test_item_custody_is_not_touched_by_the_scene_change(self) -> None:
        """物品的权威位置是 ItemCustody；随行不去动它，否则同一件东西会出现在两处。"""

        state = create_initial_game_state(
            self.content,
            room_id=ROOM,
            actors=actors(),
        )
        liquor = state.item_instances["liquor"]
        items = dict(state.item_instances)
        items["liquor"] = liquor.model_copy(
            update={
                "custody": ItemCustody(
                    kind="location",
                    ref_id=state.scene_id,
                    form="placed",
                ),
                "state": liquor.state.model_copy(
                    update={"values": {ACCOMPANYING: True}}
                ),
            }
        )
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.content,
            initial_state=state.model_copy(update={"item_instances": items}),
        )
        engine = AdjudicationEngineService(store)
        rules = RuleEngineService(store)

        await self.enter(engine, rules, "arnoldsburg_streets")

        custody = store.inspect_state(ROOM).item_instances["liquor"].custody
        self.assertEqual(custody.kind, "location")
        self.assertEqual(custody.ref_id, "thomas_office")

    # --- 门禁 -------------------------------------------------------------- #
    async def test_blocked_route_keeps_the_follower_with_the_party(self) -> None:
        """门禁拦下的是整支队伍：队伍没走成，随行的人也不会被单独送到门后。"""

        store, engine, rules = self.build(
            scene_id="cemetery",
            entities={
                "crypt_entrance": {"discovered": True, "slab_moved": False},
                "melodias": {ACCOMPANYING: True},
            },
        )

        await self.enter(engine, rules, "crypt")

        state = store.inspect_state(ROOM)
        self.assertEqual(state.scene_id, "cemetery")
        interrupted = next(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "travel.interrupted"
        )
        self.assertEqual(interrupted.payload["destination_id"], "crypt")
        self.assertIsNone(self.placed_at(store, "melodias"))
        self.assertEqual(self.moves_of(store, "melodias"), ())

    async def test_refused_travel_moves_nobody(self) -> None:
        """连路线都确认不了的移动整条被拒；随行实体一步都不该动。"""

        store, engine, rules = self.build(
            scene_id="cemetery",
            entities={"melodias": {ACCOMPANYING: True}},
        )

        with self.assertRaises(ContractError):
            await self.enter(engine, rules, "crypt")

        self.assertEqual(store.inspect_state(ROOM).scene_id, "cemetery")
        self.assertIsNone(self.placed_at(store, "melodias"))

    # --- 主持人看得见、也说得出 ---------------------------------------------- #
    async def test_the_mark_is_visible_to_the_agent(self) -> None:
        """随行是玩家当场就看得见的事，主持人也必须读得到。

        读不到，就没法判断「他还该不该跟着」，也没法在叙事里如实描写——只能靠猜，
        或者干脆不提。这个键因此进公开状态白名单，和意识、姿态、伤势同级（#516）。
        """

        self.assertIn(ACCOMPANYING, PUBLIC_STATE_KEYS)

        _store, engine, rules = self.build()
        await self.mark(engine, rules, "thomas")

        view = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        thomas = next(
            item for item in view.scene.visible_entities if item.id == "thomas"
        )
        self.assertIn(
            (ACCOMPANYING, True),
            {(state.key, state.value) for state in thomas.observable_state},
        )

    async def test_setting_the_mark_becomes_narration_evidence(self) -> None:
        """「詹姆斯跟着你走出大厅」背后要有一条已提交的状态，而不是模型自己编的。"""

        store, engine, rules = self.build()
        await self.mark(engine, rules, "thomas")

        results = committed_results_from_events(store.inspect_domain_events(ROOM))
        self.assertIn(
            ("character_state", "thomas", ACCOMPANYING, True),
            {
                (item.kind, item.target_id, item.state_key, item.state_value)
                for item in results
            },
        )

    async def test_the_mark_survives_the_engine_moving_the_follower(self) -> None:
        """带人只改位置：标记本身、以及实体上别的状态，引擎一个都不碰。

        `test_follower_keeps_following_across_later_moves` 钉的是效果——一次声明
        一直有效；这里钉的是原因——引擎没有在到站时把标记清掉，也没有借这次写入
        顺手规整实体状态。整份状态做等值比较，多写和漏写都会红。
        """

        before = {ACCOMPANYING: True, "awake": True}
        store, engine, rules = self.build(entities={"thomas": dict(before)})

        await self.enter(engine, rules, "arnoldsburg_streets")

        self.assertEqual(
            store.inspect_state(ROOM).entities["thomas"],
            {**before, "location_id": "arnoldsburg_streets"},
        )

    # --- 与规则手写的 move_entity 的关系 ------------------------------------ #
    async def test_a_rule_that_moves_first_does_not_move_the_follower_twice(
        self,
    ) -> None:
        """规则先把人送到目的地、再让队伍过去：人已经不在出发地，引擎不会再搬一次。

        《幸福蛙蛙村》的 `force_james_out_of_resort` 就是这个形状——它要能从詹姆斯不在
        场的 `resort_boundary` 触发，所以那条显式 `move_entity` 不是冗余，随行也不该
        为它再补一次事件。
        """

        store, engine, rules = self.build(entities={"thomas": {ACCOMPANYING: True}})

        await self.submit(
            engine,
            rules,
            MoveEntityEffect(entity_id="thomas", location_id="arnoldsburg_streets"),
            EnterLocationEffect(location_id="arnoldsburg_streets"),
            target_id="arnoldsburg_streets",
        )

        self.assertEqual(store.inspect_state(ROOM).scene_id, "arnoldsburg_streets")
        self.assertEqual(self.placed_at(store, "thomas"), "arnoldsburg_streets")
        self.assertEqual(len(self.moves_of(store, "thomas")), 1)


class AccompanyingRegistryTests(unittest.TestCase):
    """登记表侧的直接单测：谁算随行者，不必绕一次裁决管线。"""

    def setUp(self) -> None:
        self.content = module()

    def runtime_for(self, state: GameState) -> EngineRuntimeSnapshot:
        return EngineRuntimeSnapshot(
            module_id=self.content.module_id,
            module_version=self.content.version,
            module_content=self.content,
            game_state=state,
            revision=str(state.event_sequence),
        )

    def followers(self, state: GameState, origin: str) -> tuple[str, ...]:
        return effect_registry.accompanying_entity_ids(
            self.runtime_for(state),
            state,
            origin_location_id=origin,
        )

    def test_authored_placement_counts_as_being_here(self) -> None:
        """没被搬动过的 Canon 实体，位置来自模组声明的 `located_in`。"""

        state = game_state(self.content, entities={"thomas": {ACCOMPANYING: True}})
        self.assertEqual(self.followers(state, "thomas_office"), ("thomas",))

    def test_runtime_placement_overrides_the_authored_one(self) -> None:
        """搬动过之后以运行态为准，和投影判断「谁在这个场景」用的是同一套优先级。"""

        state = game_state(
            self.content,
            entities={
                "thomas": {ACCOMPANYING: True, "location_id": "arnoldsburg_streets"}
            },
        )
        self.assertEqual(self.followers(state, "thomas_office"), ())
        self.assertEqual(self.followers(state, "arnoldsburg_streets"), ("thomas",))

    def test_followers_come_back_in_a_stable_order(self) -> None:
        """多个随行者的顺序是确定的，同一次移动的事件序列因此可复现。"""

        state = game_state(
            self.content,
            entities={
                "thomas": {ACCOMPANYING: True},
                "melodias": {ACCOMPANYING: True, "location_id": "thomas_office"},
            },
        )
        self.assertEqual(
            self.followers(state, "thomas_office"),
            ("melodias", "thomas"),
        )


if __name__ == "__main__":
    unittest.main()
