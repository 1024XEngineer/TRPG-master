"""Every registered high-level effect must become observable, not just committed.

Issue #212 froze a set of high-level effects the Rule Engine commits atomically.
Committing them is only half of the loop: the Agent's next step and the player's
UI both read the world back through `PlayerView`, so an effect that changes
`GameState` without changing the projection is a capability that exists on paper
only. These tests pin the projection side of each one.

`KeeperCapabilityView` is covered here too, because it is the reason the Agent
can name the ids these effects need — and because the same tests are the right
place to prove it does not leak into the player-safe view.
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
    ModuleContent,
    MoveEntityEffect,
    NoAdjudicationCheck,
    PlayerViewScope,
    RevealInformationEffect,
    SetEndingAvailabilityEffect,
    SetVisibilityEffect,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)

ROOT = Path(__file__).resolve().parents[1]
SCOPE = PlayerViewScope(room_id="room_01", player_id="player_01", actor_id="pc_1")


def load_model(path: str, model_type):
    return model_type.model_validate_json((ROOT / path).read_text(encoding="utf-8"))


class EngineCapabilityProjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = load_model("fixtures/demo-module.json", ModuleContent)
        state = load_model("fixtures/demo-state.json", GameState)
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

        await self.commit("reveal-1", RevealInformationEffect(information_id="document_truth"))

        after = await self.engine.read(SCOPE)
        self.assertEqual([item.id for item in after.known_information], ["document_truth"])
        self.assertEqual(after.known_information[0].scope, "party")

    async def test_runtime_entity_becomes_visible_in_the_current_scene(self) -> None:
        await self.commit(
            "runtime-entity-1",
            EnsureRuntimeEntityEffect(
                entity_id="night_clerk",
                entity_kind="npc",
                name="值班的管理员",
                location_id="study",
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
                connected_location_id="study",
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
                connected_location_id="study",
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
            {"study"},
        )

    async def test_generic_entity_cannot_claim_item_inventory_custody(self) -> None:
        await self.commit(
            "runtime-location-3",
            EnsureRuntimeLocationEffect(
                location_id="attic",
                name="阁楼",
                connected_location_id="study",
            ),
        )
        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.commit(
                "take-document",
                MoveEntityEffect(entity_id="document", holder_actor_id="pc_1"),
            )

        self.assertEqual(
            raised.exception.result.code,
            "INVENTORY_TARGET_NOT_PORTABLE",
        )
        state = self.store.inspect_state(SCOPE.room_id)
        self.assertNotIn("holder_actor_id", state.entities.get("document", {}))

    async def test_party_scoped_set_visibility_hides_a_canon_entity(self) -> None:
        before = await self.engine.read(SCOPE)
        self.assertIn("window", {entity.id for entity in before.scene.visible_entities})

        await self.commit(
            "hide-window",
            SetVisibilityEffect(
                target_kind="entity",
                target_id="window",
                visible=False,
                scope="party",
            ),
        )

        after = await self.engine.read(SCOPE)
        self.assertNotIn("window", {entity.id for entity in after.scene.visible_entities})

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
                CommitTerminalEndingEffect(ending_id="ending_document_recovered"),
            )

    async def test_keeper_capabilities_name_ids_the_player_view_withholds(self) -> None:
        capabilities = await self.engine.read_keeper_capabilities(SCOPE)
        snapshot = await self.engine.read(SCOPE)

        self.assertEqual(capabilities.revision, snapshot.revision)
        # The Canon Information is keeper-only until an effect releases it: the
        # Agent can name it, the player cannot see it.
        self.assertIn("document_truth", {item.id for item in capabilities.information})
        self.assertEqual(snapshot.known_information, ())
        undiscovered = next(
            item for item in capabilities.information if item.id == "document_truth"
        )
        self.assertFalse(undiscovered.known_by_party)
        self.assertIn(
            "ending_document_recovered",
            {item.id for item in capabilities.endings},
        )
        self.assertEqual(
            {item.id for item in capabilities.locations if item.is_current},
            {"study"},
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
        await self.commit("reveal-2", RevealInformationEffect(information_id="document_truth"))
        await self.commit(
            "runtime-entity-3",
            EnsureRuntimeEntityEffect(
                entity_id="street_vendor",
                entity_kind="npc",
                name="街边小贩",
                location_id="study",
            ),
        )

        capabilities = await self.engine.read_keeper_capabilities(SCOPE)
        revealed = next(
            item for item in capabilities.information if item.id == "document_truth"
        )
        self.assertTrue(revealed.known_by_party)
        vendor = next(item for item in capabilities.entities if item.id == "street_vendor")
        self.assertEqual(vendor.origin, "runtime")
        self.assertEqual(vendor.location_id, "study")

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
