"""Read-side guarantees of `RuleEngineService`.

Neither assertion is version-specific — the service owns no per-room authority
state, and a projection never carries Keeper-only material — but both have to be
proven against the one published schema, so they ride on the v3 fixture (#384).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActorBindingError,
    ModuleContentV3,
    PlayerInput,
)
from collaboration_framework.engine import (
    ActorState,
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
ROOM = "room_01"
PLAYER = "player_01"
# `lyla_cemetery_sighting.keeper_content` 的独有片段——玩家侧线索只写到
# 「往公墓方向走去」，这半句只存在于主持人稿里。
KEEPER_ONLY = "但他本来走到哪里都带着书"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(content: ModuleContentV3) -> GameState:
    """两名调查员，分属两个玩家——绑定校验要区分「别人的角色」和「不存在的角色」。"""

    return GameState(
        room_id=ROOM,
        scene_id=content.initial_state.start_location_id,
        actors={
            "pc_1": ActorState(
                player_id=PLAYER,
                name="陈探员",
                source_character_id="character_v3",
                source_character_version=1,
                state={"skills": {"spot-hidden": 60}},
            ),
            "pc_2": ActorState(
                player_id="player_02",
                name="林记者",
                source_character_id="character_v3_b",
                source_character_version=1,
                state={"skills": {"library-use": 55}},
            ),
        },
        entities={},
    )


class RuleEngineServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = module()
        self.state = game_state(self.module)
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
                room_id=ROOM,
                player_id=PLAYER,
                actor_id="pc_1",
                client_action_id="read_001",
                utterance="查看房间",
            )
        )
        payload = projection.model_dump()

        self.assertEqual(projection.revision, "0")
        self.assertNotIn("actors", payload)
        self.assertNotIn("event_sequence", payload)
        self.assertNotIn("keeper_content", projection.model_dump_json())
        self.assertNotIn(KEEPER_ONLY, projection.model_dump_json())

    async def test_read_rejects_an_actor_bound_to_another_player(self) -> None:
        with self.assertRaises(ActorBindingError):
            await self.service.read(
                PlayerInput(
                    room_id=ROOM,
                    player_id=PLAYER,
                    actor_id="pc_2",
                    client_action_id="read_wrong_actor",
                    utterance="查看房间",
                )
            )


if __name__ == "__main__":
    unittest.main()
