from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ActorBindingError,
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
        self.assertEqual(set(vars(self.service)), {"_store"})

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

    async def test_read_rejects_an_actor_bound_to_another_player(self) -> None:
        with self.assertRaises(ActorBindingError):
            await self.service.read(
                PlayerInput(
                    room_id="room_01",
                    player_id="player_01",
                    actor_id="pc_2",
                    client_action_id="read_wrong_actor",
                    utterance="查看房间",
                )
            )


if __name__ == "__main__":
    unittest.main()
