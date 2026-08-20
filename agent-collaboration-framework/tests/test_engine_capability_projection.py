"""Every registered high-level effect must become observable, not just committed.

Issue #212 froze a set of high-level effects the Rule Engine commits atomically.
Committing them is only half of the loop: the Agent's next step and the player's
UI both read the world back through `PlayerView`, so an effect that changes
`GameState` without changing the projection is a capability that exists on paper
only. These tests pin the projection side of each one.

`KeeperCapabilityView` is covered here too, because it is the reason the Agent
can name the ids these effects need — and because the same tests are the right
place to prove it does not leak into the player-safe view.

The effects and the projection are both schema-independent; only the ids these
assertions name are not. They now come from the v3 fixture (#384).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    AdjudicationValidationError,
    ActionMethod,
    ActionTarget,
    CommitTerminalEndingEffect,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    ContractError,
    MarkCoreResolvedEffect,
    ModuleContentV3,
    MoveEntityEffect,
    NoAdjudicationCheck,
    PlayerViewScope,
    RevealInformationEffect,
    SetEndingAvailabilityEffect,
    SetVisibilityEffect,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
SCOPE = PlayerViewScope(room_id="room_01", player_id="player_01", actor_id="pc_1")
# 开局所在地点，以及站在那里的 Canon NPC。
START = "thomas_office"
CANON_NPC = "thomas"
# 一条开局尚未被发现的 Canon Information，和一个结局锚点。
INFORMATION = "lyla_cemetery_sighting"
ENDING = "ending_douglas_departs"


class EngineCapabilityProjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = ModuleContentV3.model_validate_json(
            FIXTURE.read_text(encoding="utf-8")
        )
        state = GameState(
            room_id=SCOPE.room_id,
            scene_id=self.module.initial_state.start_location_id,
            actors={
                SCOPE.actor_id: ActorState(
                    player_id=SCOPE.player_id,
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                    state={"skills": {"spot-hidden": 60}},
                )
            },
            entities={},
        )
        self.store = InMemoryEngineStore()
        self.store.register_room(module_content=self.module, initial_state=state)
        self.engine = RuleEngineService(self.store)
        self.adjudication_engine = AdjudicationEngineService(self.store)

    async def commit(self, request_id: str, *effects) -> None:
        """Submit one check-free adjudication carrying `effects`."""

        snapshot = await self.engine.read(SCOPE)
        await self.adjudication_engine.submit(
            SubmitAdjudicationRequest(
                room_id=SCOPE.room_id,
                player_id=SCOPE.player_id,
                adjudication=ActionAdjudication(
                    request_id=request_id,
                    source_revision=snapshot.revision,
                    actor_id=SCOPE.actor_id,
                    summary="测试用高层效果",
                    target=ActionTarget(kind="world", id=self.module.world_ref),
                    method=ActionMethod(family="action", description="测试用高层效果"),
                    check=NoAdjudicationCheck(),
                    success_effects=tuple(effects),
                ),
            )
        )

    async def test_revealed_information_reaches_the_player_view(self) -> None:
        before = await self.engine.read(SCOPE)
        self.assertEqual(before.known_information, ())

        await self.commit("reveal-1", RevealInformationEffect(information_id=INFORMATION))

        after = await self.engine.read(SCOPE)
        self.assertEqual([item.id for item in after.known_information], [INFORMATION])
        self.assertEqual(after.known_information[0].scope, "party")

    async def test_runtime_entity_becomes_visible_in_the_current_scene(self) -> None:
        await self.commit(
            "runtime-entity-1",
            EnsureRuntimeEntityEffect(
                entity_id="night_clerk",
                entity_kind="npc",
                name="值班的管理员",
                location_id=START,
            ),
        )

        snapshot = await self.engine.read(SCOPE)
        clerk = next(
            entity for entity in snapshot.scene.visible_entities if entity.id == "night_clerk"
        )
        self.assertEqual(clerk.kind, "npc")
        self.assertEqual(clerk.name, "值班的管理员")

    async def test_runtime_entity_placed_elsewhere_stays_out_of_the_scene(self) -> None:
        await self.commit(
            "runtime-location-1",
            EnsureRuntimeLocationEffect(
                location_id="corridor",
                name="走廊",
                connected_location_id=START,
            ),
        )
        await self.commit(
            "runtime-entity-2",
            EnsureRuntimeEntityEffect(
                entity_id="passing_maid",
                entity_kind="npc",
                name="路过的女仆",
                location_id="corridor",
            ),
        )

        snapshot = await self.engine.read(SCOPE)
        self.assertNotIn(
            "passing_maid",
            {entity.id for entity in snapshot.scene.visible_entities},
        )

    async def test_runtime_location_is_reachable_and_can_be_entered(self) -> None:
        await self.commit(
            "runtime-location-2",
            EnsureRuntimeLocationEffect(
                location_id="cellar",
                name="地窖",
                connected_location_id=START,
            ),
        )

        before = await self.engine.read(SCOPE)
        exits = {item.destination.scene_id for item in before.scene.available_exits}
        self.assertIn("cellar", exits)

        await self.commit("enter-runtime-1", EnterLocationEffect(location_id="cellar"))

        inside = await self.engine.read(SCOPE)
        self.assertEqual(inside.scene_id, "cellar")
        self.assertEqual(inside.scene.name, "地窖")
        # The only route out is the location it was attached to; a runtime
        # location must not silently open travel to every Canon Scene.
        self.assertEqual(
            {item.destination.scene_id for item in inside.scene.available_exits},
            {START},
        )

    async def test_generic_entity_cannot_claim_item_inventory_custody(self) -> None:
        await self.commit(
            "runtime-location-3",
            EnsureRuntimeLocationEffect(
                location_id="attic",
                name="阁楼",
                connected_location_id=START,
            ),
        )
        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.commit(
                "take-document",
                MoveEntityEffect(entity_id="study_window", holder_actor_id="pc_1"),
            )

        self.assertEqual(
            raised.exception.result.code,
            "INVENTORY_TARGET_NOT_PORTABLE",
        )
        state = self.store.inspect_state(SCOPE.room_id)
        self.assertNotIn("holder_actor_id", state.entities.get("study_window", {}))

    async def test_party_scoped_set_visibility_hides_a_canon_entity(self) -> None:
        before = await self.engine.read(SCOPE)
        self.assertIn(CANON_NPC, {entity.id for entity in before.scene.visible_entities})

        await self.commit(
            "hide-window",
            SetVisibilityEffect(
                target_kind="entity",
                target_id=CANON_NPC,
                visible=False,
                scope="party",
            ),
        )

        after = await self.engine.read(SCOPE)
        self.assertNotIn(CANON_NPC, {entity.id for entity in after.scene.visible_entities})

    async def test_world_time_is_projected_as_a_discrete_point(self) -> None:
        """时间只在离散点上，投影出的是 day_index + hour_of_day，不是流逝分钟数。"""

        snapshot = await self.engine.read(SCOPE)
        self.assertEqual(snapshot.world.day_index, 0)
        self.assertEqual(snapshot.world.hour_of_day, 12)
        self.assertEqual(snapshot.world.time_of_day, "day")

    async def test_core_resolution_opens_draft_but_direct_ending_is_refused(self) -> None:
        await self.commit(
            "resolve-core",
            MarkCoreResolvedEffect(),
            SetEndingAvailabilityEffect(available=True),
        )

        opened = await self.engine.read(SCOPE)
        self.assertTrue(opened.world.core_resolved)
        self.assertTrue(opened.world.ending_available)
        self.assertIsNone(opened.world.ending_id)
        self.assertEqual(opened.phase, "playing")

        with self.assertRaisesRegex(ContractError, "EndingDraft"):
            await self.commit(
                "confirm-ending",
                CommitTerminalEndingEffect(ending_id=ENDING),
            )

    async def test_keeper_capabilities_name_ids_the_player_view_withholds(self) -> None:
        capabilities = await self.engine.read_keeper_capabilities(SCOPE)
        snapshot = await self.engine.read(SCOPE)

        self.assertEqual(capabilities.revision, snapshot.revision)
        # The Canon Information is keeper-only until an effect releases it: the
        # Agent can name it, the player cannot see it.
        self.assertIn(INFORMATION, {item.id for item in capabilities.information})
        self.assertEqual(snapshot.known_information, ())
        undiscovered = next(
            item for item in capabilities.information if item.id == INFORMATION
        )
        self.assertFalse(undiscovered.known_by_party)
        self.assertIn(
            ENDING,
            {item.id for item in capabilities.endings},
        )
        self.assertEqual(
            {item.id for item in capabilities.locations if item.is_current},
            {START},
        )

    async def test_keeper_capabilities_publish_the_only_legal_world_target(self) -> None:
        """`kind="world"` 只认 `world_ref`，所以必须把它发出去（#313）。

        它是规则系统 id（追书人是 `coc-7e`），PlayerView 里没有、场景里也推不出。
        不发就等于「world 这个 target kind 对 Agent 不存在」：玩家问时间、问天气、
        纯应答这类没有具体对象的输入，模型只能猜一个 id，然后每次都吃
        TARGET_UNAVAILABLE。
        """

        capabilities = await self.engine.read_keeper_capabilities(SCOPE)

        self.assertEqual(capabilities.world_id, self.module.world_ref)
        # 发布出来的这个值必须真的能当目标用，而不只是多了一个字段。
        snapshot = await self.engine.read(SCOPE)
        await self.adjudication_engine.submit(
            SubmitAdjudicationRequest(
                room_id=SCOPE.room_id,
                player_id=SCOPE.player_id,
                adjudication=ActionAdjudication(
                    request_id="world-target-313",
                    source_revision=snapshot.revision,
                    actor_id=SCOPE.actor_id,
                    summary="现在几点了？",
                    target=ActionTarget(kind="world", id=capabilities.world_id or ""),
                    method=ActionMethod(family="talk", description="询问时间"),
                    check=NoAdjudicationCheck(),
                ),
            )
        )

    async def test_keeper_capabilities_track_committed_effects(self) -> None:
        await self.commit("reveal-2", RevealInformationEffect(information_id=INFORMATION))
        await self.commit(
            "runtime-entity-3",
            EnsureRuntimeEntityEffect(
                entity_id="street_vendor",
                entity_kind="npc",
                name="街边小贩",
                location_id=START,
            ),
        )

        capabilities = await self.engine.read_keeper_capabilities(SCOPE)
        revealed = next(
            item for item in capabilities.information if item.id == INFORMATION
        )
        self.assertTrue(revealed.known_by_party)
        vendor = next(item for item in capabilities.entities if item.id == "street_vendor")
        self.assertEqual(vendor.origin, "runtime")
        self.assertEqual(vendor.location_id, START)

    async def test_engine_still_refuses_ids_that_are_not_in_the_capability_list(self) -> None:
        """The capability view is vocabulary, not authorization."""

        with self.assertRaises(ContractError):
            await self.commit(
                "unknown-information",
                RevealInformationEffect(information_id="information_that_does_not_exist"),
            )
        with self.assertRaisesRegex(ContractError, "EndingDraft"):
            await self.commit(
                "unknown-ending",
                CommitTerminalEndingEffect(ending_id="ending_that_does_not_exist"),
            )


if __name__ == "__main__":
    unittest.main()
