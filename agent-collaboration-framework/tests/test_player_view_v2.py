from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ContractError,
    DefaultCheck,
    Intent,
    MatchedTarget,
    ModuleCheck,
    ModuleContent,
    NoCheck,
    PlayerInput,
    PlayerViewScope,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    RuleKernel,
    SequenceDiceSource,
)
from collaboration_framework.host.adapters.fakes import FakeIntentModel
from collaboration_framework.host.application import (
    IntentParser,
    PlayerViewProjector,
    validate_intent_against_view,
)
from collaboration_framework.host.schemas import IntentContext, RecentTurnContext

ROOT = Path(__file__).resolve().parents[1]
KEEPER_SECRET = "KEEPER_ONLY_SCENE_INSTRUCTIONS"
RAW_STATE_SECRET = "RAW_ENTITY_STATE_SECRET"
OTHER_CARD_SECRET = "OTHER_ACTOR_PRIVATE_CARD"
PRIVATE_NOTE = "PLAYER_PRIVATE_NOTE"


def intent_context(*, player_input: PlayerInput, player_view) -> IntentContext:
    return IntentContext(
        player_input=player_input,
        player_view=player_view,
        recent_history=RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
        ),
    )


def player_view_module() -> ModuleContent:
    payload = json.loads(
        (ROOT / "fixtures" / "demo-module.json").read_text(encoding="utf-8")
    )
    study = payload["scenes"][0]
    study["content"] = KEEPER_SECRET
    study["player_visible_name"] = "安全书房"
    study["player_visible_description"] = "灯光照着书架与一只上锁的木柜。"
    study["exits"] = ["garden"]
    study["available_exits"] = [
        {
            "id": "north_door",
            "name": "北侧门",
            "aliases": ["去花园", "离开房间"],
            "description": "一扇通向别处的木门。",
            "destination_scene_id": "garden",
            "reveal_destination": False,
        }
    ]
    payload["scenes"].append(
        {
            "id": "garden",
            "name": "Keeper Garden",
            "content": "Keeper-only garden logic.",
            "player_visible_name": "花园",
            "player_visible_description": "潮湿的花园笼罩在夜色中。",
            "entity_ids": [],
            "checkpoint_ids": [],
            "exits": ["study"],
            "available_exits": [
                {
                    "id": "garden_door",
                    "name": "返回书房的门",
                    "destination_scene_id": "study",
                    "reveal_destination": True,
                }
            ],
        }
    )

    cabinet = next(item for item in payload["entities"] if item["id"] == "cabinet")
    cabinet["state"]["keeper_code"] = RAW_STATE_SECRET
    payload["information_items"].extend(
        [
            {
                "id": "party_clue",
                "title": "泥脚印",
                "summary": "脚印从窗边延伸到书架。",
                "content": "你们已经确认湿泥脚印从窗边延伸到了书架。",
                "related_entities": ["bookshelf", "window"],
                "related_scenes": ["study"],
                "visibility": {"audience": "all"},
            },
            {
                "id": "private_clue",
                "title": "旧警徽",
                "summary": "只有当前调查员认出了警徽。",
                "content": "你认出柜角划痕来自一枚旧式警徽。",
                "related_entities": ["cabinet"],
                "related_scenes": ["study"],
                "visibility": {
                    "audience": "actor",
                    "discovery_shares_to_party": False,
                },
            },
            {
                "id": "other_private_clue",
                "title": "他人的秘密",
                "summary": "属于另一位调查员。",
                "content": "这条内容不能出现在当前玩家视图。",
                "visibility": {
                    "audience": "actor",
                    "discovery_shares_to_party": False,
                },
            },
            {
                "id": "released_keeper_clue",
                "title": "已确认的旧闻",
                "summary": "规则结算已经向玩家释放这条事实。",
                "content": "这条内容在被规则结果发现后可以进入玩家已知信息。",
                "visibility": {"audience": "keeper"},
            },
            {
                "id": "unreleased_keeper_clue",
                "content": "尚未被规则结果发现的守秘人秘密。",
                "visibility": {"audience": "keeper"},
            },
        ]
    )
    return ModuleContent.model_validate(payload)


def route_module(exits: list[str]) -> ModuleContent:
    payload = player_view_module().to_json_dict()
    study = payload["scenes"][0]
    study["exits"] = exits
    study["available_exits"] = []
    payload["scenes"].append(
        {
            "id": "attic",
            "name": "Keeper Attic",
            "content": "Keeper-only attic logic.",
            "player_visible_name": "阁楼",
            "player_visible_description": "低矮的阁楼里积着灰尘。",
            "entity_ids": [],
            "checkpoint_ids": [],
            "exits": [],
        }
    )
    return ModuleContent.model_validate(payload)


def player_view_state() -> GameState:
    state = GameState.model_validate_json(
        (ROOT / "fixtures" / "demo-state.json").read_text(encoding="utf-8")
    )
    self_actor = state.actors["pc_1"].model_copy(
        update={
            "state": {
                **state.actors["pc_1"].state,
                "attributes": {"STR": 55, "DEX": 60},
                "attribute_labels": {"STR": "力量", "DEX": "敏捷"},
                "skills": {
                    "spot-hidden": 65,
                    "locksmith": 40,
                    "stealth": 50,
                },
                "skill_labels": {
                    "spot-hidden": "侦查",
                    "locksmith": "锁匠",
                    "stealth": "潜行",
                },
                "notes": PRIVATE_NOTE,
                "public_status": "衣着整洁。",
            },
            "resources": ActorResources(hp=9, san=54, mp=8, luck=45, mythos=2),
            "conditions": ("wounded",),
        }
    )
    other_actor = ActorState(
        player_id="player_02",
        name="同伴",
        source_character_id="character_02",
        source_character_version=1,
        state={
            "attributes": {"STR": 99},
            "skills": {OTHER_CARD_SECRET: 99},
            "occupation": "医生",
            "background": OTHER_CARD_SECRET,
            "notes": OTHER_CARD_SECRET,
            "public_status": "手臂受伤，但仍能行动。",
        },
        resources=ActorResources(hp=3, san=10),
        conditions=("dying",),
    )
    entities = {
        entity_id: dict(entity_state)
        for entity_id, entity_state in state.entities.items()
    }
    entities["cabinet"]["opened"] = True
    entities["cabinet"]["keeper_code"] = RAW_STATE_SECRET
    return state.model_copy(
        update={
            "actors": {"pc_1": self_actor, "pc_2": other_actor},
            "entities": entities,
            "discovered_facts": ("party_clue", "released_keeper_clue"),
            "actor_discovered_facts": {
                "pc_1": ("private_clue",),
                "pc_2": ("other_private_clue",),
            },
        }
    )


def player_input(
    *,
    player_id: str = "player_01",
    actor_id: str = "pc_1",
    action_id: str = "view-v2",
    utterance: str = "我在哪里",
) -> PlayerInput:
    return PlayerInput(
        room_id="room_01",
        player_id=player_id,
        actor_id=actor_id,
        client_action_id=action_id,
        utterance=utterance,
    )


class PlayerViewV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = player_view_module()
        self.state = player_view_state()
        self.store = InMemoryEngineStore()
        self.store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        self.service = RuleEngineService(
            self.store,
            kernel=RuleKernel(
                dice_source=SequenceDiceSource([30]),
                allow_legacy_missing_skill=False,
            ),
        )

    async def test_projection_is_complete_revision_bound_and_player_safe(self) -> None:
        scope = PlayerViewScope(
            room_id="room_01",
            player_id="player_01",
            actor_id="pc_1",
        )
        snapshot = await self.service.read(scope)
        view = await PlayerViewProjector(self.service).project_scope(scope)
        encoded = view.model_dump_json()

        self.assertEqual(snapshot.revision, view.revision)
        self.assertEqual(view.self_actor.id, "pc_1")
        self.assertEqual(
            {item.id: item.value for item in view.self_actor.attributes},
            {"STR": 55, "DEX": 60},
        )
        self.assertEqual(
            {item.id: item.name for item in view.self_actor.skills},
            {
                "spot-hidden": "侦查",
                "locksmith": "锁匠",
                "stealth": "潜行",
            },
        )
        self.assertEqual(
            {item.id: item.value for item in view.self_actor.resources},
            {"hp": 9, "san": 54, "mp": 8, "luck": 45, "mythos": 2},
        )
        self.assertEqual(view.self_actor.conditions, ("wounded",))
        self.assertEqual(view.self_actor.equipment, ("手电筒",))
        self.assertEqual(view.self_actor.public_status_summary, "衣着整洁。")

        self.assertEqual(view.scene.id, view.scene_id)
        self.assertEqual(view.scene.name, "安全书房")
        self.assertEqual(
            view.scene.description,
            "灯光照着书架与一只上锁的木柜。",
        )
        self.assertEqual(view.scene.time, "day")
        self.assertNotIn("document", {item.id for item in view.scene.visible_entities})
        cabinet = next(
            item for item in view.scene.visible_entities if item.id == "cabinet"
        )
        self.assertEqual(
            [(item.key, item.value) for item in cabinet.observable_state],
            [("opened", True)],
        )
        self.assertEqual(
            [
                (item.id, item.name, item.occupation, item.status_summary)
                for item in view.scene.visible_actors
            ],
            [("pc_2", "同伴", "医生", "手臂受伤，但仍能行动。")],
        )
        self.assertEqual(view.scene.available_exits[0].id, "north_door")
        self.assertIsNone(view.scene.available_exits[0].destination)

        self.assertEqual(
            [(item.id, item.scope) for item in view.known_information],
            [
                ("party_clue", "party"),
                ("private_clue", "actor"),
                ("released_keeper_clue", "party"),
            ],
        )
        self.assertIn("bookshelf", view.known_information[0].related_entities)
        self.assertNotIn(
            "unreleased_keeper_clue",
            {item.id for item in view.known_information},
        )

        for secret in (
            KEEPER_SECRET,
            RAW_STATE_SECRET,
            OTHER_CARD_SECRET,
            PRIVATE_NOTE,
            "Keeper Garden",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, encoded)

    async def test_private_known_information_is_scoped_to_bound_actor(self) -> None:
        other = await PlayerViewProjector(self.service).project(
            player_input(player_id="player_02", actor_id="pc_2")
        )
        self.assertEqual(
            [(item.id, item.scope) for item in other.known_information],
            [
                ("party_clue", "party"),
                ("other_private_clue", "actor"),
                ("released_keeper_clue", "party"),
            ],
        )
        self.assertNotIn(
            "private_clue",
            {item.id for item in other.known_information},
        )

    async def test_available_exit_is_a_trusted_target_and_moves_by_safe_id(
        self,
    ) -> None:
        view = await PlayerViewProjector(self.service).project(player_input())
        intent = Intent(
            kind="action",
            verb="go",
            target=MatchedTarget(id="north_door"),
            check=NoCheck(),
            summary="从北侧门离开",
        )
        context = intent_context(
            player_input=player_input(utterance="从北侧门离开"),
            player_view=view,
        )
        self.assertEqual(validate_intent_against_view(intent, context), intent)

        result = await self.service.execute(
            ActionRequest(
                request_id="move-north",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=intent,
            )
        )
        self.assertEqual(result.outcome, "success")
        self.assertEqual(self.store.inspect_state("room_01").scene_id, "garden")

    async def test_empty_exits_derive_every_other_scene_as_free_travel(self) -> None:
        module = route_module([])
        store = InMemoryEngineStore()
        store.register_room(module_content=module, initial_state=self.state)
        service = RuleEngineService(store)
        view = await PlayerViewProjector(service).project(player_input())

        self.assertEqual(
            [(item.id, item.name) for item in view.scene.available_exits],
            [("garden", "花园"), ("attic", "阁楼")],
        )
        intent = Intent(
            kind="action",
            verb="go",
            target=MatchedTarget(id="attic"),
            check=NoCheck(),
            summary="前往阁楼",
        )
        context = intent_context(
            player_input=player_input(utterance="前往阁楼"),
            player_view=view,
        )
        self.assertEqual(validate_intent_against_view(intent, context), intent)

        result = await service.execute(
            ActionRequest(
                request_id="move-attic",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=intent,
            )
        )
        self.assertEqual(result.outcome, "success")
        self.assertEqual(store.inspect_state("room_01").scene_id, "attic")

    async def test_non_empty_exits_only_allow_declared_destinations(self) -> None:
        module = route_module(["garden"])
        store = InMemoryEngineStore()
        store.register_room(module_content=module, initial_state=self.state)
        service = RuleEngineService(store)
        view = await PlayerViewProjector(service).project(player_input())

        self.assertEqual(
            [item.id for item in view.scene.available_exits],
            ["garden"],
        )
        blocked = Intent(
            kind="action",
            verb="go",
            target=MatchedTarget(id="attic"),
            check=NoCheck(),
            summary="前往阁楼",
        )
        context = intent_context(
            player_input=player_input(utterance="前往阁楼"),
            player_view=view,
        )
        with self.assertRaisesRegex(ContractError, "PlayerView"):
            validate_intent_against_view(blocked, context)

        result = await service.execute(
            ActionRequest(
                request_id="blocked-attic",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=blocked,
            )
        )
        self.assertEqual(result.resolution, "blocked")
        self.assertEqual(store.inspect_state("room_01").scene_id, "study")

    async def test_visible_door_checkpoint_takes_priority_over_scene_travel(
        self,
    ) -> None:
        payload = route_module(["garden"]).to_json_dict()
        cabinet = next(
            entity for entity in payload["entities"] if entity["id"] == "cabinet"
        )
        cabinet["name"] = "通往花园的门"
        cabinet["aliases"] = ["花园门"]
        cabinet["player_visible_name"] = "通往花园的门"
        cabinet["player_visible_aliases"] = ["花园门"]
        checkpoint = next(
            item for item in payload["checkpoints"] if item["id"] == "smash_cabinet"
        )
        checkpoint["action"] = "open"
        module = ModuleContent.model_validate(payload)
        store = InMemoryEngineStore()
        store.register_room(module_content=module, initial_state=self.state)
        service = RuleEngineService(store)
        view = await PlayerViewProjector(service).project(player_input())
        context = intent_context(
            player_input=player_input(utterance="打开花园门"),
            player_view=view,
        )

        raw = await FakeIntentModel().generate(context)
        intent = IntentParser.parse(raw, context)

        assert isinstance(intent.target, MatchedTarget)
        self.assertEqual(intent.target.id, "cabinet")
        self.assertEqual(intent.verb, "open")
        assert isinstance(intent.check, ModuleCheck)
        self.assertEqual(intent.check.route, "module")
        self.assertEqual(intent.check.checkpoint_id, "smash_cabinet")

    async def test_default_check_only_accepts_current_actor_candidates(self) -> None:
        view = await PlayerViewProjector(self.service).project(player_input())
        context = intent_context(player_input=player_input(), player_view=view)
        valid = Intent(
            kind="action",
            verb="inspect",
            target=MatchedTarget(id="bookshelf"),
            check=DefaultCheck(proposed_skills=("spot-hidden",)),
            summary="仔细检查书架",
        )
        self.assertEqual(validate_intent_against_view(valid, context), valid)

        invalid = valid.model_copy(
            update={
                "check": DefaultCheck(proposed_skills=("spot-hidden", "keeper-secret"))
            }
        )
        with self.assertRaisesRegex(ContractError, "当前 Actor"):
            validate_intent_against_view(invalid, context)
        with self.assertRaisesRegex(ContractError, "current Actor"):
            await self.service.execute(
                ActionRequest(
                    request_id="invalid-default-check",
                    room_id="room_01",
                    player_id="player_01",
                    actor_id="pc_1",
                    source_view_revision=view.revision,
                    intent=invalid,
                )
            )

    async def test_scene_default_check_returns_authoritative_roll_without_plot_change(
        self,
    ) -> None:
        view = await PlayerViewProjector(self.service).project(player_input())
        intent = Intent(
            kind="action",
            verb="investigate",
            target=MatchedTarget(id=view.scene.id),
            check=DefaultCheck(proposed_skills=("spot-hidden",)),
            summary="仔细观察整个房间",
        )
        context = intent_context(
            player_input=player_input(utterance="我仔细观察整个房间"),
            player_view=view,
        )
        self.assertEqual(validate_intent_against_view(intent, context), intent)

        before = self.store.inspect_state("room_01")
        result = await self.service.execute(
            ActionRequest(
                request_id="scene-spot-hidden",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=intent,
            )
        )

        self.assertEqual(result.resolution, "direct")
        self.assertEqual(result.outcome, "success")
        self.assertIsNotNone(result.check_result)
        assert result.check_result is not None
        self.assertIsNone(result.check_result.checkpoint_id)
        self.assertEqual(result.check_result.skill_id, "spot-hidden")
        self.assertEqual(result.check_result.target_value, 65)
        self.assertEqual(result.check_result.roll_value, 30)
        self.assertEqual(result.check_result.difficulty, "regular")
        self.assertTrue(result.check_result.passed)
        self.assertTrue(
            any("普通检定" in item for item in result.narration_constraints)
        )
        after = self.store.inspect_state("room_01")
        self.assertEqual(after.discovered_facts, before.discovered_facts)
        self.assertEqual(after.actor_discovered_facts, before.actor_discovered_facts)

    async def test_failed_entity_default_check_does_not_reveal_direct_response(
        self,
    ) -> None:
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        service = RuleEngineService(
            store,
            kernel=RuleKernel(
                dice_source=SequenceDiceSource([90]),
                allow_legacy_missing_skill=False,
            ),
        )
        view = await PlayerViewProjector(service).project(player_input())
        intent = Intent(
            kind="action",
            verb="investigate",
            target=MatchedTarget(id="cabinet"),
            check=DefaultCheck(proposed_skills=("spot-hidden",)),
            summary="仔细检查柜子的锁孔",
        )

        result = await service.execute(
            ActionRequest(
                request_id="failed-cabinet-check",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=intent,
            )
        )

        self.assertEqual(result.outcome, "failure")
        self.assertIsNotNone(result.check_result)
        assert result.check_result is not None
        self.assertFalse(result.check_result.passed)
        visible_text = " ".join(item.text for item in result.visible_facts)
        self.assertNotIn("柜门边缘没有被撬动过的痕迹", visible_text)
        self.assertIn("没能充分发挥", visible_text)
        self.assertFalse(result.event_refs)

    async def test_exit_default_check_rolls_and_does_not_gate_movement(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        service = RuleEngineService(
            store,
            kernel=RuleKernel(
                dice_source=SequenceDiceSource([90]),
                allow_legacy_missing_skill=False,
            ),
        )
        view = await PlayerViewProjector(service).project(player_input())
        intent = Intent(
            kind="action",
            verb="go",
            target=MatchedTarget(id="north_door"),
            check=DefaultCheck(proposed_skills=("stealth",)),
            approach="保持隐蔽",
            summary="潜行穿过北侧门",
        )
        context = intent_context(
            player_input=player_input(utterance="我潜行穿过北侧门"),
            player_view=view,
        )
        self.assertEqual(validate_intent_against_view(intent, context), intent)

        result = await service.execute(
            ActionRequest(
                request_id="stealth-through-door",
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                source_view_revision=view.revision,
                intent=intent,
            )
        )

        self.assertEqual(result.outcome, "failure")
        self.assertIsNotNone(result.check_result)
        assert result.check_result is not None
        self.assertEqual(result.check_result.skill_id, "stealth")
        self.assertFalse(result.check_result.passed)
        self.assertEqual(store.inspect_state("room_01").scene_id, "garden")


if __name__ == "__main__":
    unittest.main()
