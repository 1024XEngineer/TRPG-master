from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import ContractError, ModuleContent
from collaboration_framework.engine import (
    CompletedAction,
    GameState,
    InMemoryEngineStore,
    RevisionConflictError,
    RuleEngineService,
    RuleKernel,
)

from tests.test_engine_service import checkpoint_request, load_model

ROOT = Path(__file__).resolve().parents[1]


class InMemoryEngineStoreContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.module = load_model("fixtures/demo-module.json", ModuleContent)
        self.state = load_model("fixtures/demo-state.json", GameState)

    def store(self, **kwargs) -> InMemoryEngineStore:
        store = InMemoryEngineStore(**kwargs)
        store.register_room(
            module_content=self.module,
            initial_state=self.state,
        )
        return store

    async def test_runtime_identifies_bound_module_version(self) -> None:
        store = self.store()
        async with store.transaction("room_01") as transaction:
            runtime = await transaction.load_runtime()

        self.assertEqual(runtime.module_id, self.module.module_id)
        self.assertEqual(runtime.module_version, self.module.version)
        self.assertEqual(runtime.revision, "0")

    async def test_loaded_models_are_deep_copy_isolated(self) -> None:
        store = self.store()
        async with store.transaction("room_01") as transaction:
            runtime = await transaction.load_runtime()
            runtime.game_state.entities["bookshelf"]["key_found"] = True
            runtime.module_content.entities[0].direct_responses["invented"] = "泄漏"

        async with store.transaction("room_01") as transaction:
            reloaded = await transaction.load_runtime()

        self.assertFalse(reloaded.game_state.entities["bookshelf"]["key_found"])
        self.assertNotIn(
            "invented",
            reloaded.module_content.entities[0].direct_responses,
        )

    async def test_stale_expected_revision_rejects_entire_commit(self) -> None:
        store = self.store()
        request = checkpoint_request(request_id="stale_commit_001")
        async with store.transaction("room_01") as transaction:
            runtime = await transaction.load_runtime()
            execution, new_state = RuleKernel().execute(
                request=request,
                module_content=runtime.module_content,
                game_state=runtime.game_state,
            )
            with self.assertRaises(RevisionConflictError):
                await transaction.commit(
                    expected_revision="999",
                    new_state=new_state,
                    events=execution.events,
                    completed_action=CompletedAction(
                        request=request,
                        execution=execution,
                    ),
                )

        self.assertEqual(store.inspect_state("room_01"), self.state)
        self.assertEqual(store.inspect_events("room_01"), ())
        with self.assertRaises(ContractError):
            store.inspect_completed_action("room_01", request.request_id)

    async def test_commit_failure_has_no_partial_writes(self) -> None:
        def fail_before_commit(room_id: str) -> None:
            raise RuntimeError(f"simulated failure for {room_id}")

        store = self.store(before_commit=fail_before_commit)
        request = checkpoint_request(request_id="failure_001")

        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            await RuleEngineService(store).execute(request)

        self.assertEqual(store.inspect_state("room_01"), self.state)
        self.assertEqual(store.inspect_events("room_01"), ())
        with self.assertRaises(ContractError):
            store.inspect_completed_action("room_01", request.request_id)

    async def test_successful_commit_publishes_all_records(self) -> None:
        store = self.store()
        request = checkpoint_request(request_id="atomic_001")
        result = await RuleEngineService(store).execute(request)

        state = store.inspect_state("room_01")
        events = store.inspect_events("room_01")
        completed = store.inspect_completed_action("room_01", request.request_id)

        self.assertEqual(state.event_sequence, 1)
        self.assertEqual(tuple(event.event_id for event in events), result.event_refs)
        self.assertEqual(completed.request, request)
        self.assertEqual(completed.execution.events, events)
        self.assertEqual(completed.execution.state_version, state.event_sequence)


if __name__ == "__main__":
    unittest.main()
