from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    ModuleContent,
    PlayerInput,
)
from collaboration_framework.engine import (
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)

ROOT = Path(__file__).resolve().parents[1]


def load_model(path: str, model_type):
    return model_type.model_validate_json((ROOT / path).read_text(encoding="utf-8"))


def checkpoint_request(
    *,
    request_id: str,
    room_id: str = "room_01",
    player_id: str = "player_01",
    revision: str = "0",
    target_id: str = "bookshelf",
    checkpoint_id: str = "investigate_bookshelf",
    skill: str = "spot-hidden",
) -> ActionRequest:
    return ActionRequest(
        request_id=request_id,
        room_id=room_id,
        player_id=player_id,
        actor_id="pc_1",
        source_view_revision=revision,
        intent=Intent(
            kind="action",
            verb="inspect",
            target=MatchedTarget(id=target_id),
            check=ModuleCheck(
                checkpoint_id=checkpoint_id,
                proposed_skills=(skill,),
            ),
            summary=f"检查 {target_id}",
        ),
    )


class RuleEngineServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = load_model("fixtures/demo-module.json", ModuleContent)
        self.state = load_model("fixtures/demo-state.json", GameState)
        self.store = InMemoryEngineStore()
        self.store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        self.service = RuleEngineService(self.store)

    async def test_service_has_no_single_room_authority_fields(self) -> None:
        self.assertEqual(set(vars(self.service)), {"_store", "_kernel"})

    async def test_multi_room_same_request_id_is_isolated(self) -> None:
        state_payload = self.state.model_dump(mode="python")
        state_payload["room_id"] = "room_02"
        state_payload["actors"]["pc_1"]["player_id"] = "player_02"
        self.store.register_room(
            module_content=self.module,
            initial_state=GameState.model_validate(state_payload),
        )

        first, second = await asyncio.gather(
            self.service.execute(checkpoint_request(request_id="shared_request")),
            self.service.execute(
                checkpoint_request(
                    request_id="shared_request",
                    room_id="room_02",
                    player_id="player_02",
                )
            ),
        )

        self.assertEqual(first.request_id, second.request_id)
        self.assertTrue(
            self.store.inspect_state("room_01").entities["bookshelf"]["key_found"]
        )
        self.assertTrue(
            self.store.inspect_state("room_02").entities["bookshelf"]["key_found"]
        )
        self.assertEqual(len(self.store.inspect_events("room_01")), 1)
        self.assertEqual(len(self.store.inspect_events("room_02")), 1)

    async def test_shared_store_keeps_idempotency_across_service_rebuild(self) -> None:
        request = checkpoint_request(request_id="rebuild_001")
        first = await self.service.execute(request)

        rebuilt_service = RuleEngineService(self.store)
        replay = await rebuilt_service.execute(request)

        self.assertEqual(replay, first)
        self.assertEqual(len(self.store.inspect_events("room_01")), 1)
        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 1)

    async def test_late_replay_keeps_semantics_and_current_revision(self) -> None:
        first_request = checkpoint_request(request_id="first_001")
        first = await self.service.execute(first_request)
        later = checkpoint_request(
            request_id="later_001",
            revision="1",
            target_id="cabinet",
            checkpoint_id="smash_cabinet",
            skill="STR",
        )
        await self.service.execute(later)

        replay = await RuleEngineService(self.store).execute(first_request)
        current_revision = str(self.store.inspect_state("room_01").event_sequence)

        self.assertEqual(replay.view_revision, current_revision)
        self.assertEqual(replay.event_refs, first.event_refs)
        self.assertEqual(replay.visible_facts, first.visible_facts)
        self.assertEqual(len(self.store.inspect_events("room_01")), 5)

    async def test_same_request_id_with_different_intent_is_rejected(self) -> None:
        request = checkpoint_request(request_id="collision_001")
        await self.service.execute(request)
        conflicting = checkpoint_request(
            request_id="collision_001",
            target_id="cabinet",
            checkpoint_id="smash_cabinet",
            skill="STR",
        )

        with self.assertRaisesRegex(ContractError, "request_id 已用于不同"):
            await self.service.execute(conflicting)

        self.assertEqual(len(self.store.inspect_events("room_01")), 1)

    async def test_concurrent_stale_actions_cannot_overwrite_new_state(self) -> None:
        results = await asyncio.gather(
            self.service.execute(checkpoint_request(request_id="race_001")),
            RuleEngineService(self.store).execute(
                checkpoint_request(request_id="race_002")
            ),
            return_exceptions=True,
        )

        self.assertEqual(sum(isinstance(item, ActionResult) for item in results), 1)
        self.assertEqual(sum(isinstance(item, ContractError) for item in results), 1)
        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 1)
        self.assertEqual(len(self.store.inspect_events("room_01")), 1)

    async def test_read_returns_only_safe_projection(self) -> None:
        projection = await self.service.read(
            PlayerInput(
                room_id="room_01",
                player_id="player_01",
                actor_id="pc_1",
                client_action_id="read_001",
                utterance="查看房间",
            )
        )
        payload = projection.model_dump()

        self.assertEqual(projection.revision, "0")
        self.assertNotIn("actors", payload)
        self.assertNotIn("event_sequence", payload)
        self.assertNotIn("secrets", projection.model_dump_json())
        self.assertNotIn("他知道柜中藏有文件", projection.model_dump_json())


if __name__ == "__main__":
    unittest.main()
