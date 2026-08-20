"""Atomicity guarantees every EngineStore implementation owes its callers.

These used to build their commit payload by running the Checkpoint kernel. The
kernel is gone (#226) but the store contract is not — the adjudication engine
and the ActionPlan runtime commit through the same transaction — so the payload
is now assembled by hand and the assertions are unchanged: a stale revision
rejects the whole commit, a mid-commit failure leaves nothing behind, and a
successful commit publishes state, events and the completed action together.

Nothing here is version-specific: the store never looks inside `module_content`.
It rides on the v3 fixture only because that is the one published schema (#384).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    ModuleContentV3,
)
from collaboration_framework.engine import (
    ActorState,
    CompletedAction,
    EngineExecutionResult,
    GameState,
    InMemoryEngineStore,
    RevisionConflictError,
    StateModifiedEvent,
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
ACTOR = "pc_1"
PLAYER = "player_01"
# 一个带布尔状态的 Canon 实体，用来做「翻一位」的最小提交载荷。
ENTITY = "douglas_diary"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(content: ModuleContentV3) -> GameState:
    return GameState(
        room_id=ROOM,
        scene_id=content.initial_state.start_location_id,
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="陈探员",
                source_character_id="character_v3",
                source_character_version=1,
                state={"skills": {"spot-hidden": 60}},
            )
        },
        entities={ENTITY: {"found": False, "read": False}},
    )


def checkpoint_request(*, request_id: str) -> ActionRequest:
    return ActionRequest(
        request_id=request_id,
        room_id=ROOM,
        player_id=PLAYER,
        actor_id=ACTOR,
        source_view_revision="0",
        intent=Intent(
            kind="action",
            verb="inspect",
            target=MatchedTarget(id=ENTITY),
            check=ModuleCheck(
                checkpoint_id="investigate_diary",
                proposed_skills=("spot-hidden",),
            ),
            summary=f"检查 {ENTITY}",
        ),
    )


class InMemoryEngineStoreContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = module()
        self.state = game_state(self.module)

    def store(self, **kwargs) -> InMemoryEngineStore:
        store = InMemoryEngineStore(**kwargs)
        store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        return store

    def commit_payload(
        self,
        request: ActionRequest,
    ) -> tuple[GameState, tuple[StateModifiedEvent, ...], CompletedAction]:
        """One well-formed write: flip `douglas_diary.found` and record it."""

        new_state = self.state.model_copy(deep=True)
        new_state.entities[ENTITY]["found"] = True
        new_state = new_state.model_copy(
            update={"event_sequence": self.state.event_sequence + 1}
        )
        events = (
            StateModifiedEvent(
                event_id=f"evt_{request.request_id}",
                sequence=new_state.event_sequence,
                room_id=request.room_id,
                actor_id=request.actor_id,
                client_action_id=request.request_id,
                cause=f"action:{request.request_id}",
                payload={
                    "path": f"entities.{ENTITY}.found",
                    "from": False,
                    "to": True,
                },
            ),
        )
        completed = CompletedAction(
            request=request,
            execution=EngineExecutionResult(
                action_result=ActionResult(
                    request_id=request.request_id,
                    action_id=request.request_id,
                    resolution="checkpoint",
                    outcome="success",
                    view_revision=str(new_state.event_sequence),
                    event_refs=tuple(event.event_id for event in events),
                ),
                events=events,
                state_version=new_state.event_sequence,
            ),
        )
        return new_state, events, completed

    async def test_runtime_identifies_bound_module_version(self) -> None:
        store = self.store()
        async with store.transaction(ROOM) as transaction:
            runtime = await transaction.load_runtime()

        self.assertEqual(runtime.module_id, self.module.module_id)
        self.assertEqual(runtime.module_version, self.module.version)
        self.assertEqual(runtime.revision, "0")

    async def test_loaded_models_are_deep_copy_isolated(self) -> None:
        store = self.store()
        async with store.transaction(ROOM) as transaction:
            runtime = await transaction.load_runtime()
            runtime.game_state.entities[ENTITY]["found"] = True
            runtime.module_content.entities[0].state["invented"] = "泄漏"

        async with store.transaction(ROOM) as transaction:
            reloaded = await transaction.load_runtime()

        self.assertFalse(reloaded.game_state.entities[ENTITY]["found"])
        self.assertNotIn("invented", reloaded.module_content.entities[0].state)

    async def test_stale_expected_revision_rejects_entire_commit(self) -> None:
        store = self.store()
        request = checkpoint_request(request_id="stale_commit_001")
        new_state, events, completed = self.commit_payload(request)
        async with store.transaction(ROOM) as transaction:
            await transaction.load_runtime()
            with self.assertRaises(RevisionConflictError):
                await transaction.commit(
                    expected_revision="999",
                    new_state=new_state,
                    events=events,
                    completed_action=completed,
                )

        self.assertEqual(store.inspect_state(ROOM), self.state)
        self.assertEqual(store.inspect_events(ROOM), ())
        with self.assertRaises(ContractError):
            store.inspect_completed_action(ROOM, request.request_id)

    async def test_commit_failure_has_no_partial_writes(self) -> None:
        def fail_before_commit(room_id: str) -> None:
            raise RuntimeError(f"simulated failure for {room_id}")

        store = self.store(before_commit=fail_before_commit)
        request = checkpoint_request(request_id="failure_001")
        new_state, events, completed = self.commit_payload(request)

        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            async with store.transaction(ROOM) as transaction:
                runtime = await transaction.load_runtime()
                await transaction.commit(
                    expected_revision=runtime.revision,
                    new_state=new_state,
                    events=events,
                    completed_action=completed,
                )

        self.assertEqual(store.inspect_state(ROOM), self.state)
        self.assertEqual(store.inspect_events(ROOM), ())
        with self.assertRaises(ContractError):
            store.inspect_completed_action(ROOM, request.request_id)

    async def test_successful_commit_publishes_all_records(self) -> None:
        store = self.store()
        request = checkpoint_request(request_id="atomic_001")
        new_state, events, completed = self.commit_payload(request)
        async with store.transaction(ROOM) as transaction:
            runtime = await transaction.load_runtime()
            await transaction.commit(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=events,
                completed_action=completed,
            )

        state = store.inspect_state(ROOM)
        stored_events = store.inspect_events(ROOM)
        stored = store.inspect_completed_action(ROOM, request.request_id)

        self.assertEqual(state.event_sequence, 1)
        self.assertEqual(
            tuple(event.event_id for event in stored_events),
            completed.execution.action_result.event_refs,
        )
        self.assertEqual(stored.request, request)
        self.assertEqual(stored.execution.events, stored_events)
        self.assertEqual(stored.execution.state_version, state.event_sequence)


if __name__ == "__main__":
    unittest.main()
