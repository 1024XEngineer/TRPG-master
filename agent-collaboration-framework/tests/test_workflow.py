from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from collaboration_framework.contracts import (
    EngineRequest,
    GameState,
    Intent,
    InterpretRequest,
    ModuleContent,
    NarrationOutput,
    NarrationRequest,
    PlayerInput,
    StateModifiedEvent,
    TurnState,
)
from collaboration_framework.agents import (
    FakeRuntimeAgent,
    PydanticAIRuntimeAgent,
)
from collaboration_framework.engine import FakeAtomicEngine
from collaboration_framework.schema_export import rendered_schemas
from collaboration_framework.workflow import (
    TurnDependencies,
    build_safe_narration_request,
    run_turn_sync,
)

models.ALLOW_MODEL_REQUESTS = False
ROOT = Path(__file__).resolve().parents[1]


def load_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def with_input(base: PlayerInput, *, action_id: str, utterance: str) -> PlayerInput:
    return base.model_copy(
        update={"client_action_id": action_id, "utterance": utterance}
    )


def replay_events(
    initial_state: GameState,
    events: list[StateModifiedEvent],
) -> GameState:
    """从初始状态按序重放状态事件，重建物化视图。"""

    payload = initial_state.model_dump(mode="python", by_alias=True)
    for event in sorted(events, key=lambda item: item.sequence):
        cursor = payload
        parts = event.payload.path.split(".")
        for part in parts[:-1]:
            cursor = cursor[part]
        leaf = parts[-1]
        if cursor.get(leaf) != event.payload.from_value:
            raise AssertionError(f"Event 重放前值不匹配: {event.payload.path}")
        cursor[leaf] = event.payload.to
        payload["event_sequence"] = event.sequence
    return GameState.model_validate(payload)


class CountingEngine:
    def __init__(self, inner: FakeAtomicEngine) -> None:
        self.inner = inner
        self.context_calls = 0
        self.execute_calls = 0

    async def assemble_context(self, player_input):
        self.context_calls += 1
        return await self.inner.assemble_context(player_input)

    async def execute_action(self, request):
        self.execute_calls += 1
        return await self.inner.execute_action(request)

    def snapshot(self):
        return self.inner.snapshot()


class CountingAgent:
    def __init__(self) -> None:
        self.inner = FakeRuntimeAgent()
        self.interpret_calls = 0
        self.narrate_calls = 0
        self.last_narration_request = None

    async def interpret(self, request):
        self.interpret_calls += 1
        return await self.inner.interpret(request)

    async def narrate(self, request):
        self.narrate_calls += 1
        self.last_narration_request = request
        return await self.inner.narrate(request)


class UnsafeNarrativeOpenAgent(CountingAgent):
    """Interpreter double that tries to bypass the engine with NoCheck."""

    async def interpret(self, request):
        self.interpret_calls += 1
        return Intent.model_validate(
            {
                "execution": "narrative",
                "kind": "interact",
                "action": "open",
                "target": {"matched": True, "id": "cabinet"},
                "check": {"route": "none"},
                "narrative_intent": request.player_input.utterance,
            }
        )


class PythonWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = ModuleContent.model_validate_json(load_text("fixtures/demo-module.json"))
        cls.state = GameState.model_validate_json(load_text("fixtures/demo-state.json"))
        cls.player_input = PlayerInput.model_validate_json(load_text("fixtures/demo-turn.json"))

    def dependencies(self):
        engine = CountingEngine(FakeAtomicEngine(self.module, self.state))
        agent = CountingAgent()
        deps = TurnDependencies(
            context_assembler=engine,
            interpreter=agent,
            engine=engine,
            narrator=agent,
        )
        return deps, engine, agent

    def test_all_json_files_are_valid(self) -> None:
        for path in sorted(ROOT.rglob("*.json")):
            if ".venv" in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNotNone(json.loads(path.read_text(encoding="utf-8")))

    def test_exported_schemas_match_pydantic_source(self) -> None:
        expected = rendered_schemas()
        self.assertEqual(len(expected), 13)
        for filename, content in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(load_text(f"schemas/{filename}"), content)

    def test_runtime_code_has_no_langgraph_dependency(self) -> None:
        for path in sorted((ROOT / "collaboration_framework").rglob("*.py")):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("langgraph", path.read_text(encoding="utf-8").lower())
        self.assertNotIn("langgraph", load_text("pyproject.toml").lower())

    def test_pydantic_rejects_unknown_fields(self) -> None:
        payload = self.player_input.to_json_dict()
        payload["workflow_thread_id"] = "must-not-exist"
        with self.assertRaises(ValidationError):
            PlayerInput.model_validate(payload)

    def test_execution_and_check_are_independent_contract_dimensions(self) -> None:
        engine_no_check = Intent.model_validate(
            {
                "execution": "engine",
                "kind": "interact",
                "action": "open",
                "target": {"matched": True, "id": "cabinet"},
                "check": {"route": "none"},
                "narrative_intent": "打开柜子",
            }
        )
        request = EngineRequest(player_input=self.player_input, intent=engine_no_check)
        self.assertEqual(request.intent.check.route, "none")

        with self.assertRaises(ValidationError):
            Intent.model_validate(
                {
                    "execution": "narrative",
                    "kind": "interact",
                    "action": "investigate",
                    "target": {"matched": True, "id": "bookshelf"},
                    "check": {
                        "route": "module",
                        "checkpoint_id": "investigate_bookshelf",
                    },
                    "narrative_intent": "调查书架",
                }
            )

        narrative = Intent.model_validate(
            {
                "execution": "narrative",
                "kind": "communicate",
                "action": "talk",
                "target": {"matched": True, "id": "butler"},
                "check": {"route": "none"},
                "narrative_intent": "和管家闲聊",
            }
        )
        with self.assertRaises(ValidationError):
            EngineRequest(player_input=self.player_input, intent=narrative)

    def test_turn_state_does_not_own_game_state(self) -> None:
        self.assertNotIn("game_state", TurnState.model_json_schema()["properties"])

    def test_module_route_calls_atomic_engine_once(self) -> None:
        deps, engine, agent = self.dependencies()
        output = run_turn_sync(self.player_input, deps)

        self.assertEqual(output.status, "completed")
        self.assertEqual(output.intent.execution, "engine")
        self.assertEqual(output.intent.check.route, "module")
        self.assertEqual(engine.context_calls, 2)
        self.assertEqual(engine.execute_calls, 1)
        self.assertEqual(agent.interpret_calls, 1)
        self.assertEqual(agent.narrate_calls, 1)
        self.assertTrue(engine.snapshot().entities["bookshelf"]["key_found"])
        self.assertEqual(len(output.action_result.events), 1)
        self.assertEqual(output.summary_op.source_event_ids, ["evt_0001"])

        event_json = output.action_result.events[0].to_json_dict()
        self.assertEqual(event_json["type"], "state.modified")
        self.assertEqual(
            event_json["payload"],
            {
                "path": "entities.bookshelf.key_found",
                "from": False,
                "to": True,
            },
        )
        self.assertNotIn("path", event_json)
        self.assertNotIn("from", event_json)
        self.assertNotIn("to", event_json)

        player_output = output.to_player_output()
        self.assertIsInstance(player_output, NarrationOutput)
        self.assertEqual(player_output, output.narration)
        self.assertIsNot(player_output, output.narration)
        self.assertNotIn("action_result", player_output.model_dump())
        self.assertNotIn("summary_op", player_output.model_dump())

    def test_engine_route_refreshes_context_before_narration(self) -> None:
        deps, engine, agent = self.dependencies()
        smash = with_input(
            self.player_input,
            action_id="smash_001",
            utterance="我用力砸开柜子。",
        )
        output = run_turn_sync(smash, deps)

        self.assertEqual(output.intent.check.route, "module")
        self.assertEqual(engine.snapshot().phase, "ended")
        self.assertEqual(engine.context_calls, 2)
        self.assertIsNotNone(agent.last_narration_request)
        self.assertEqual(agent.last_narration_request.context.phase, "ended")

    def test_all_events_rebuild_committed_snapshot(self) -> None:
        deps, engine, _ = self.dependencies()
        smash = with_input(
            self.player_input,
            action_id="smash_replay_001",
            utterance="我用力砸开柜子。",
        )
        output = run_turn_sync(smash, deps)

        self.assertEqual(
            [event.payload.path for event in output.action_result.events],
            [
                "entities.cabinet.opened",
                "entities.document.destroyed",
                "ending_id",
                "phase",
            ],
        )
        ending_event = output.action_result.events[-2]
        self.assertIsNone(ending_event.payload.from_value)
        self.assertEqual(ending_event.payload.to, "ending_document_destroyed")
        self.assertEqual(
            replay_events(self.state, output.action_result.events),
            engine.snapshot(),
        )

    def test_narration_request_exposes_only_safe_projection(self) -> None:
        deps, _, agent = self.dependencies()
        smash = with_input(
            self.player_input,
            action_id="smash_fact_001",
            utterance="我用力砸开柜子。",
        )
        first = run_turn_sync(smash, deps)
        first_request = agent.last_narration_request

        self.assertIsNotNone(first.action_result)
        self.assertIsNotNone(first_request)
        self.assertEqual(len(first.action_result.confirmed_facts), 3)
        self.assertEqual(len(first.action_result.player_visible_information), 2)
        self.assertEqual(first_request.utterance, smash.utterance)
        self.assertEqual(
            [fact.text for fact in first_request.player_visible_facts],
            first.action_result.player_visible_information,
        )
        self.assertEqual(
            [fact.id for fact in first_request.player_visible_facts],
            [
                "checkpoint:smash_cabinet:success:result:1",
                "checkpoint:smash_cabinet:success:result:2",
            ],
        )
        self.assertEqual(
            first_request.narration_constraints,
            first.action_result.narration_constraints,
        )

        prompt_payload = first_request.model_dump_json()
        for forbidden in (
            '"player_input"',
            '"action_result"',
            '"intent"',
            '"confirmed_facts"',
            '"state_changes"',
            '"events"',
            '"visibility"',
            "entities.cabinet.opened",
            "evt_0001",
            "玩家成功砸开柜门",
            "ending_document_destroyed",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt_payload)

        unsafe_payload = first_request.to_json_dict()
        unsafe_payload["action_result"] = first.action_result.to_json_dict()
        with self.assertRaises(ValidationError):
            NarrationRequest.model_validate(unsafe_payload)

        first_fact_ids = [fact.id for fact in first_request.player_visible_facts]
        run_turn_sync(smash, deps)
        replay_fact_ids = [
            fact.id for fact in agent.last_narration_request.player_visible_facts
        ]
        self.assertEqual(replay_fact_ids, first_fact_ids)

    def test_narrative_execution_skips_engine(self) -> None:
        deps, engine, agent = self.dependencies()
        talk = with_input(
            self.player_input,
            action_id="talk_001",
            utterance="我和管家聊聊。",
        )
        output = run_turn_sync(talk, deps)

        self.assertEqual(output.intent.execution, "narrative")
        self.assertEqual(output.intent.check.route, "none")
        self.assertEqual(engine.execute_calls, 0)
        self.assertEqual(agent.narrate_calls, 1)
        self.assertIsNone(output.action_result)
        self.assertIsNotNone(output.summary_op)

    def test_clarification_ends_without_engine_or_narrator(self) -> None:
        deps, engine, agent = self.dependencies()
        unclear = PlayerInput.model_validate_json(
            load_text("fixtures/clarification-turn.json")
        )
        output = run_turn_sync(unclear, deps)

        self.assertEqual(output.status, "clarification")
        self.assertEqual(output.narration.kind, "clarification")
        self.assertEqual(engine.execute_calls, 0)
        self.assertEqual(agent.narrate_calls, 0)
        self.assertIsNone(output.summary_op)

    def test_engine_execution_with_no_check_still_uses_engine(self) -> None:
        deps, engine, _ = self.dependencies()
        open_cabinet = with_input(
            self.player_input,
            action_id="open_001",
            utterance="我打开柜子。",
        )
        output = run_turn_sync(open_cabinet, deps)

        self.assertEqual(output.intent.execution, "engine")
        self.assertEqual(output.intent.check.route, "none")
        self.assertEqual(engine.execute_calls, 1)
        self.assertFalse(output.action_result.success)
        self.assertEqual(output.action_result.resolution, "blocked")

    def test_workflow_hardens_narrative_world_action_to_engine(self) -> None:
        engine = CountingEngine(FakeAtomicEngine(self.module, self.state))
        agent = UnsafeNarrativeOpenAgent()
        deps = TurnDependencies(
            context_assembler=engine,
            interpreter=agent,
            engine=engine,
            narrator=agent,
        )
        open_cabinet = with_input(
            self.player_input,
            action_id="open_bypass_001",
            utterance="我打开柜子。",
        )

        output = run_turn_sync(open_cabinet, deps)

        self.assertEqual(output.intent.execution, "engine")
        self.assertEqual(output.intent.check.route, "none")
        self.assertEqual(engine.execute_calls, 1)
        self.assertFalse(output.action_result.success)
        self.assertEqual(output.action_result.resolution, "blocked")

    def test_replayed_action_does_not_duplicate_events(self) -> None:
        deps, engine, _ = self.dependencies()
        first = run_turn_sync(self.player_input, deps)
        second = run_turn_sync(self.player_input, deps)

        self.assertEqual(len(first.action_result.events), 1)
        self.assertEqual(second.action_result, first.action_result)
        self.assertEqual(
            [event.event_id for event in second.action_result.events],
            [event.event_id for event in first.action_result.events],
        )
        self.assertEqual(second.summary_op, first.summary_op)
        self.assertEqual(engine.snapshot().event_sequence, 1)

    def test_fake_interpreter_matches_shared_route_examples(self) -> None:
        engine = FakeAtomicEngine(self.module, self.state)
        context = asyncio.run(engine.assemble_context(self.player_input))
        agent = FakeRuntimeAgent()
        for case in json.loads(load_text("fixtures/demo-cases.json")):
            player_input = with_input(
                self.player_input,
                action_id=case["case_id"],
                utterance=case["utterance"],
            )
            intent = asyncio.run(
                agent.interpret(
                    InterpretRequest(player_input=player_input, context=context)
                )
            )
            with self.subTest(case=case["case_id"]):
                self.assertEqual(intent.kind, case["expected_kind"])
                self.assertEqual(intent.action, case["expected_action"])
                self.assertEqual(intent.execution, case["expected_execution"])
                self.assertEqual(intent.check.route, case["expected_check_route"])
                self.assertEqual(getattr(intent.target, "id", None), case["expected_target"])


class PydanticAIPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = ModuleContent.model_validate_json(load_text("fixtures/demo-module.json"))
        cls.state = GameState.model_validate_json(load_text("fixtures/demo-state.json"))
        cls.player_input = PlayerInput.model_validate_json(load_text("fixtures/demo-turn.json"))

    def test_testmodel_exercises_structured_outputs(self) -> None:
        engine = FakeAtomicEngine(self.module, self.state)
        context = asyncio.run(engine.assemble_context(self.player_input))
        intent_payload = {
            "execution": "engine",
            "kind": "interact",
            "action": "investigate",
            "target": {"matched": True, "id": "bookshelf"},
            "check": {
                "route": "module",
                "checkpoint_id": "investigate_bookshelf",
                "proposed_skills": ["spot_hidden"],
            },
            "narrative_intent": "调查书架",
            "clarification_question": None,
        }
        narration_payload = {
            "kind": "narration",
            "text": "你检查了书架。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }
        agent = PydanticAIRuntimeAgent(
            TestModel(custom_output_args=intent_payload),
            TestModel(custom_output_args=narration_payload),
        )
        request = InterpretRequest(player_input=self.player_input, context=context)
        intent = asyncio.run(agent.interpret(request))
        action_result = asyncio.run(
            engine.execute_action(
                EngineRequest(player_input=self.player_input, intent=intent)
            )
        )
        refreshed_context = asyncio.run(engine.assemble_context(self.player_input))
        narration_request = build_safe_narration_request(
            TurnState(
                player_input=self.player_input,
                context=refreshed_context,
                intent=Intent.model_validate(intent),
                action_result=action_result,
            )
        )
        narration = asyncio.run(agent.narrate(narration_request))
        self.assertEqual(intent.check.route, "module")
        self.assertEqual(narration.text, "你检查了书架。")

    def test_checkpoint_route_is_hardened_from_other_proposals(self) -> None:
        engine = FakeAtomicEngine(self.module, self.state)
        smash_input = with_input(
            self.player_input,
            action_id="smash_validator_001",
            utterance="我用力砸开柜子。",
        )
        context = asyncio.run(engine.assemble_context(smash_input))
        base_payload = {
            "kind": "interact",
            "action": "smash",
            "target": {"matched": True, "id": "cabinet"},
            "narrative_intent": "砸开柜子",
            "clarification_question": None,
        }
        invalid_routes = {
            "narrative_no_check": {
                "execution": "narrative",
                "check": {"route": "none"},
            },
            "engine_no_check": {
                "execution": "engine",
                "check": {"route": "none"},
            },
            "engine_default_check": {
                "execution": "engine",
                "check": {
                    "route": "default",
                    "proposed_skills": ["strength"],
                },
            },
        }

        for label, route_payload in invalid_routes.items():
            payload = {**base_payload, **route_payload}
            agent = PydanticAIRuntimeAgent(TestModel(custom_output_args=payload))
            with self.subTest(route=label):
                intent = asyncio.run(
                    agent.interpret(
                        InterpretRequest(player_input=smash_input, context=context)
                    )
                )
                self.assertEqual(intent.kind, "interact")
                self.assertEqual(intent.execution, "engine")
                self.assertEqual(intent.check.route, "module")
                self.assertEqual(intent.check.checkpoint_id, "smash_cabinet")

    def test_authoritative_action_without_checkpoint_requires_engine(self) -> None:
        engine = FakeAtomicEngine(self.module, self.state)
        open_input = with_input(
            self.player_input,
            action_id="open_validator_001",
            utterance="我打开窗户。",
        )
        context = asyncio.run(engine.assemble_context(open_input))
        payload = {
            "execution": "narrative",
            "kind": "interact",
            "action": "open",
            "target": {"matched": True, "id": "window"},
            "check": {"route": "none"},
            "narrative_intent": "打开窗户",
            "clarification_question": None,
        }
        agent = PydanticAIRuntimeAgent(TestModel(custom_output_args=payload))

        intent = asyncio.run(
            agent.interpret(InterpretRequest(player_input=open_input, context=context))
        )

        self.assertEqual(intent.kind, "interact")
        self.assertEqual(intent.execution, "engine")
        self.assertEqual(intent.check.route, "none")

    def test_authoritative_no_check_and_pure_narrative_routes_remain_valid(self) -> None:
        engine = FakeAtomicEngine(self.module, self.state)
        context = asyncio.run(engine.assemble_context(self.player_input))
        cases = {
            "authoritative_no_check": {
                "execution": "engine",
                "kind": "interact",
                "action": "open",
                "target": {"matched": True, "id": "window"},
                "check": {"route": "none"},
                "narrative_intent": "打开窗户",
                "clarification_question": None,
            },
            "pure_narrative": {
                "execution": "narrative",
                "kind": "communicate",
                "action": "talk",
                "target": {"matched": True, "id": "butler"},
                "check": {"route": "none"},
                "narrative_intent": "和管家闲聊",
                "clarification_question": None,
            },
        }

        for label, payload in cases.items():
            agent = PydanticAIRuntimeAgent(TestModel(custom_output_args=payload))
            with self.subTest(route=label):
                intent = asyncio.run(
                    agent.interpret(
                        InterpretRequest(player_input=self.player_input, context=context)
                    )
                )
                self.assertEqual(intent.execution, payload["execution"])
                self.assertEqual(intent.check.route, "none")


if __name__ == "__main__":
    unittest.main()
