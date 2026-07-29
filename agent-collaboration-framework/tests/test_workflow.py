from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from collaboration_framework.bootstrap import build_fake_application
from collaboration_framework.contracts import (
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    ModuleContent,
    PlayerInput,
)
from collaboration_framework.engine import GameState
from collaboration_framework.host.adapters import OneShotHostAgentAdapter
from collaboration_framework.host.adapters.fakes import (
    FakeIntentModel,
    FakeNarrationModel,
)
from collaboration_framework.host.application import (
    ContextAssembler,
    HostAgentIntentResolver,
    IntentParser,
    NarrationValidationError,
    Narrator,
    Orchestrator,
    PlayerViewProjector,
    TurnExecutionError,
)
from collaboration_framework.host.schemas import RecentTurnContext
from collaboration_framework.schema_export import rendered_schemas
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def load_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def with_input(base: PlayerInput, *, action_id: str, utterance: str) -> PlayerInput:
    return base.model_copy(
        update={"client_action_id": action_id, "utterance": utterance}
    )


def replay_events(initial_state: GameState, events) -> GameState:
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
    def __init__(self, inner, store, room_id: str) -> None:
        self.inner = inner
        self.store = store
        self.room_id = room_id
        self.read_calls = 0
        self.execute_calls = 0

    async def read(self, player_input):
        self.read_calls += 1
        return await self.inner.read(player_input)

    async def execute(self, request):
        self.execute_calls += 1
        return await self.inner.execute(request)

    def snapshot(self):
        return self.store.inspect_state(self.room_id)

    def execution_for(self, request_id):
        return self.store.inspect_completed_action(
            self.room_id,
            request_id,
        ).execution


class StaticIntentModel:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def generate(self, context):
        return self.payload


class StaticNarrationModel:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def generate(self, context):
        return self.payload


class RecordingNarrationModel(FakeNarrationModel):
    def __init__(self) -> None:
        self.last_context = None

    async def generate(self, context):
        self.last_context = context
        return await super().generate(context)


class UnifiedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = ModuleContent.model_validate_json(
            load_text("fixtures/demo-module.json")
        )
        cls.state = GameState.model_validate_json(load_text("fixtures/demo-state.json"))
        cls.player_input = PlayerInput.model_validate_json(
            load_text("fixtures/demo-turn.json")
        )

    def application(self, intent_model=None, narration_model=None):
        base = build_fake_application(self.module, self.state)
        engine = CountingEngine(
            base.engine,
            base.engine_store,
            self.state.room_id,
        )
        recording = narration_model or RecordingNarrationModel()
        orchestrator = Orchestrator(
            context_assembler=ContextAssembler(),
            host_intent_resolver=HostAgentIntentResolver(
                OneShotHostAgentAdapter(intent_model or FakeIntentModel())
            ),
            action_executor=engine,
            player_view_projector=PlayerViewProjector(engine),
            narrator=Narrator(recording),
        )
        return orchestrator, engine, recording

    def test_actor_character_snapshot_is_loaded_and_preserved(self) -> None:
        actor = self.state.actors["pc_1"]
        self.assertEqual(actor.source_character_id, "character_01")
        self.assertEqual(actor.source_character_version, 1)
        self.assertEqual(actor.state["hp"], 10)
        self.assertEqual(actor.state["san"], 60)

        orchestrator, engine, _ = self.application()
        self.run_turn(orchestrator)
        self.assertEqual(engine.snapshot().actors["pc_1"], actor)

    def run_turn(self, orchestrator, player_input=None):
        return asyncio.run(orchestrator.run(player_input or self.player_input))

    def test_all_json_files_are_valid(self) -> None:
        for path in sorted(ROOT.rglob("*.json")):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNotNone(json.loads(path.read_text(encoding="utf-8")))

    def test_exported_schemas_match_pydantic_source(self) -> None:
        expected = rendered_schemas()
        self.assertEqual(len(expected), 13)
        self.assertIn("host-agent-context.schema.json", expected)
        self.assertIn("host-agent-usage.schema.json", expected)
        self.assertIn("host-agent-event.schema.json", expected)
        self.assertNotIn("turn-state.schema.json", expected)
        self.assertNotIn("event.schema.json", expected)
        self.assertNotIn("summary-operation.schema.json", expected)
        for filename, content in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(load_text(f"schemas/{filename}"), content)

    def test_intent_keeps_check_proposal_but_has_no_execution(self) -> None:
        schema = Intent.model_json_schema()
        self.assertNotIn("execution", schema["properties"])
        intent = Intent.model_validate(
            {
                "kind": "action",
                "verb": "inspect_in_my_own_way",
                "target": {"matched": True, "id": "bookshelf"},
                "check": {
                    "route": "module",
                    "checkpoint_id": "investigate_bookshelf",
                    "proposed_skills": ["spot-hidden"],
                },
                "approach": "慢慢翻查书背",
                "summary": "调查书架",
            }
        )
        self.assertIsInstance(intent.target, MatchedTarget)
        self.assertIsInstance(intent.check, ModuleCheck)
        self.assertEqual(intent.check.checkpoint_id, "investigate_bookshelf")
        self.assertEqual(intent.verb, "inspect_in_my_own_way")

    def test_discriminated_target_rejects_ambiguous_shape(self) -> None:
        with self.assertRaises(ValidationError):
            Intent.model_validate(
                {
                    "kind": "action",
                    "verb": "open",
                    "target": {
                        "matched": True,
                        "id": "cabinet",
                        "raw": "柜子",
                    },
                    "check": {"route": "none"},
                    "summary": "打开柜子",
                }
            )

    def test_module_checkpoint_action_goes_through_executor_once(self) -> None:
        orchestrator, engine, narrator = self.application()
        output = self.run_turn(orchestrator)

        self.assertEqual(output.intent.check.route, "module")
        self.assertEqual(engine.read_calls, 2)
        self.assertEqual(engine.execute_calls, 1)
        self.assertTrue(engine.snapshot().entities["bookshelf"]["key_found"])
        self.assertEqual(output.action_result.resolution, "checkpoint")
        self.assertEqual(output.action_result.outcome, "success")
        self.assertEqual(output.action_result.event_refs, ("evt_0001",))
        self.assertEqual(output.player_view.revision, "1")
        self.assertIsNotNone(narrator.last_context)
        self.assertEqual(narrator.last_context.background, self.module.background)

    def test_dialogue_also_goes_through_executor_once(self) -> None:
        orchestrator, engine, _ = self.application()
        talk = with_input(
            self.player_input,
            action_id="talk_001",
            utterance="我和管家聊聊。",
        )
        output = self.run_turn(orchestrator, talk)

        self.assertEqual(output.intent.kind, "dialogue")
        self.assertEqual(output.intent.check.route, "none")
        self.assertEqual(engine.execute_calls, 1)
        self.assertEqual(engine.read_calls, 2)
        self.assertEqual(output.action_result.resolution, "direct")
        self.assertEqual(output.action_result.outcome, "not_applicable")

    def test_unknown_intent_also_goes_through_executor_then_clarifies(self) -> None:
        orchestrator, engine, _ = self.application()
        unclear = PlayerInput.model_validate_json(
            load_text("fixtures/clarification-turn.json")
        )
        output = self.run_turn(orchestrator, unclear)

        self.assertEqual(output.intent.kind, "unknown")
        self.assertEqual(engine.execute_calls, 1)
        self.assertEqual(output.action_result.resolution, "unrecognized")
        self.assertEqual(output.status, "clarification")
        self.assertEqual(output.narration.kind, "clarification")

    def test_narrator_classifies_invalid_outer_schema_at_application_boundary(
        self,
    ) -> None:
        narrator = StaticNarrationModel(
            {
                "kind": "narration",
                "text": "",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        )
        orchestrator, engine, _ = self.application(narration_model=narrator)

        with self.assertRaises(NarrationValidationError) as failed:
            self.run_turn(orchestrator)

        self.assertEqual(failed.exception.reason, "outer_schema")
        self.assertEqual(engine.execute_calls, 1)

    def test_narrator_classifies_unconfirmed_fact_at_application_boundary(
        self,
    ) -> None:
        narrator = StaticNarrationModel(
            {
                "kind": "narration",
                "text": "书架后传来一声轻响。",
                "claimed_fact_ids": ["fact-not-confirmed"],
                "suggested_actions": [],
            }
        )
        orchestrator, engine, _ = self.application(narration_model=narrator)

        with self.assertRaises(NarrationValidationError) as failed:
            self.run_turn(orchestrator)

        self.assertEqual(failed.exception.reason, "fact_scope")
        self.assertEqual(engine.execute_calls, 1)

    def test_narrator_normalizes_literal_newlines_before_returning_output(self) -> None:
        narrator = StaticNarrationModel(
            {
                "kind": "narration",
                "text": "第一段\\r\\n第二段\\n第三段\\r第四段",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        )
        orchestrator, _, _ = self.application(narration_model=narrator)

        output = self.run_turn(orchestrator)

        self.assertEqual(output.narration.text, "第一段\n第二段\n第三段\n第四段")

    def test_narrator_checks_protocol_tail_after_newline_normalization(self) -> None:
        narrator = StaticNarrationModel(
            {
                "kind": "narration",
                "text": "托马斯说完便沉默。\\nclaimed_fact_ids: []",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        )
        orchestrator, engine, _ = self.application(narration_model=narrator)

        with self.assertRaises(NarrationValidationError) as failed:
            self.run_turn(orchestrator)

        self.assertEqual(failed.exception.reason, "protocol_tail")
        self.assertEqual(engine.execute_calls, 1)

    def test_host_semantic_checkpoint_choice_is_not_rejected_by_verb_equality(
        self,
    ) -> None:
        payload = {
            "kind": "action",
            "verb": "force_open_with_my_shoulder",
            "target": {"matched": True, "id": "cabinet"},
            "check": {
                "route": "module",
                "checkpoint_id": "smash_cabinet",
                "proposed_skills": ["STR"],
            },
            "approach": "用肩膀猛撞柜门",
            "summary": "强行撞开柜子",
        }
        orchestrator, engine, _ = self.application(StaticIntentModel(payload))
        custom_input = with_input(
            self.player_input,
            action_id="semantic_checkpoint_001",
            utterance="我用肩膀猛撞柜门。",
        )
        output = self.run_turn(orchestrator, custom_input)

        self.assertEqual(engine.execute_calls, 1)
        self.assertEqual(output.action_result.resolution, "checkpoint")
        self.assertEqual(engine.snapshot().phase, "ended")

    def test_checkpoint_must_still_come_from_trusted_player_view(self) -> None:
        payload = {
            "kind": "action",
            "verb": "investigate",
            "target": {"matched": True, "id": "bookshelf"},
            "check": {
                "route": "module",
                "checkpoint_id": "invented_checkpoint",
                "proposed_skills": ["spot-hidden"],
            },
            "summary": "调查书架",
        }
        orchestrator, engine, _ = self.application(StaticIntentModel(payload))
        with self.assertRaisesRegex(
            TurnExecutionError,
            "行动意图未通过安全校验",
        ):
            self.run_turn(orchestrator)
        self.assertEqual(engine.execute_calls, 0)

    def test_public_action_result_excludes_engine_internal_payloads(self) -> None:
        orchestrator, engine, narrator = self.application()
        output = self.run_turn(orchestrator)
        public_payload = output.action_result.model_dump()
        for forbidden in (
            "confirmed_facts",
            "state_changes",
            "events",
            "state_version",
            "game_state",
        ):
            self.assertNotIn(forbidden, public_payload)

        internal = engine.execution_for(self.player_input.client_action_id)
        self.assertEqual(len(internal.events), 1)
        self.assertEqual(len(internal.state_changes), 1)
        narration_payload = narrator.last_context.model_dump_json()
        self.assertNotIn("state_changes", narration_payload)
        self.assertNotIn("events", narration_payload)
        self.assertNotIn("confirmed_facts", narration_payload)

    def test_events_rebuild_committed_snapshot_without_crossing_host_contract(
        self,
    ) -> None:
        orchestrator, engine, _ = self.application()
        smash = with_input(
            self.player_input,
            action_id="smash_replay_001",
            utterance="我用力砸开柜子。",
        )
        self.run_turn(orchestrator, smash)
        internal = engine.execution_for(smash.client_action_id)

        self.assertEqual(
            [event.payload.path for event in internal.events],
            [
                "entities.cabinet.opened",
                "entities.document.destroyed",
                "ending_id",
                "phase",
            ],
        )
        self.assertEqual(replay_events(self.state, internal.events), engine.snapshot())

    def test_replayed_action_is_idempotent(self) -> None:
        orchestrator, engine, _ = self.application()
        first = self.run_turn(orchestrator)
        second = self.run_turn(orchestrator)

        self.assertEqual(first.action_result, second.action_result)
        self.assertEqual(engine.snapshot().event_sequence, 1)
        self.assertEqual(engine.execute_calls, 2)
        self.assertEqual(
            len(engine.execution_for(self.player_input.client_action_id).events), 1
        )

    def test_replayed_action_after_another_commit_uses_current_view_revision(
        self,
    ) -> None:
        orchestrator, engine, _ = self.application()
        first = self.run_turn(orchestrator)
        intervening = with_input(
            self.player_input,
            action_id="intervening_smash_001",
            utterance="我用力砸开柜子。",
        )
        self.run_turn(orchestrator, intervening)
        revision_before_replay = str(engine.snapshot().event_sequence)

        replay = self.run_turn(orchestrator)

        self.assertEqual(replay.action_result.view_revision, revision_before_replay)
        self.assertEqual(
            replay.action_result,
            first.action_result.model_copy(
                update={"view_revision": revision_before_replay}
            ),
        )
        self.assertEqual(str(engine.snapshot().event_sequence), revision_before_replay)
        self.assertEqual(
            len(engine.execution_for(self.player_input.client_action_id).events),
            1,
        )

    def test_reused_request_id_with_a_different_intent_is_rejected(self) -> None:
        orchestrator, engine, _ = self.application()
        self.run_turn(orchestrator)
        conflicting = with_input(
            self.player_input,
            action_id=self.player_input.client_action_id,
            utterance="我用力砸开柜子。",
        )

        with self.assertRaisesRegex(ContractError, "request_id 已用于不同"):
            self.run_turn(orchestrator, conflicting)

        self.assertEqual(engine.snapshot().event_sequence, 1)
        self.assertEqual(
            len(engine.execution_for(self.player_input.client_action_id).events),
            1,
        )

    def test_websocket_output_is_player_safe(self) -> None:
        app = build_fake_application(self.module, self.state)
        output = asyncio.run(app.websocket_gateway.handle(self.player_input))
        payload = output.model_dump()

        self.assertEqual(output.message_type, "turn.completed")
        self.assertNotIn("intent", payload["payload"])
        self.assertNotIn("action_result", payload["payload"])
        self.assertNotIn("player_input", payload["payload"])

    def test_fake_intent_model_matches_versioned_cases(self) -> None:
        app = build_fake_application(self.module, self.state)
        view = asyncio.run(
            app.orchestrator._player_view_projector.project(self.player_input)
        )
        model = FakeIntentModel()
        parser = IntentParser()
        assembler = ContextAssembler()
        for case in json.loads(load_text("fixtures/demo-cases.json")):
            player_input = with_input(
                self.player_input,
                action_id=case["case_id"],
                utterance=case["utterance"],
            )
            context = assembler.for_intent(
                player_input,
                view,
                RecentTurnContext.empty(
                    player_input=player_input,
                    player_view=view,
                ),
            )
            raw = asyncio.run(model.generate(context))
            intent = parser.parse(raw, context)
            with self.subTest(case=case["case_id"]):
                self.assertEqual(intent.kind, case["expected_kind"])
                self.assertEqual(intent.verb, case["expected_verb"])
                self.assertEqual(intent.check.route, case["expected_check_route"])
                self.assertEqual(
                    getattr(intent.target, "id", None),
                    case["expected_target"],
                )


if __name__ == "__main__":
    unittest.main()
