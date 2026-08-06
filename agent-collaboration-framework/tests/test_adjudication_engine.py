from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceTimeEffect,
    CancelCheckChoice,
    CheckDecisionRequest,
    ContractError,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EventRuleSpec,
    ModuleContent,
    NoAdjudicationCheck,
    PlayerChoiceAdjudicationCheck,
    PostRollDecisionRequest,
    PushAdjudication,
    RequiredAdjudicationCheck,
    RevealInformationEffect,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    InMemoryEngineStore,
    SequenceDiceSource,
)

ROOT = Path(__file__).resolve().parents[1]


def load_model(path: str, model_type):
    return model_type.model_validate_json((ROOT / path).read_text(encoding="utf-8"))


def candidate(
    candidate_id: str,
    skill_id: str,
    *,
    difficulty: str = "regular",
) -> SkillCheckCandidate:
    return SkillCheckCandidate(
        candidate_id=candidate_id,
        skill_id=skill_id,
        difficulty=difficulty,
        method_summary=f"使用 {skill_id} 调查",
        player_safe_reason=f"侧重 {skill_id} 的方法",
    )


def adjudication(
    request_id: str,
    revision: str,
    *,
    check=None,
) -> ActionAdjudication:
    return ActionAdjudication(
        request_id=request_id,
        source_revision=revision,
        actor_id="pc_1",
        summary="调查文件中的真相",
        target=ActionTarget(kind="information", id="document_truth"),
        method=ActionMethod(family="research", description="检查书房中的文件"),
        check=check or RequiredAdjudicationCheck(candidates=(candidate("spot", "spot"),)),
        success_effects=(RevealInformationEffect(information_id="document_truth"),),
    )


class AdjudicationEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        module = load_model("fixtures/demo-module.json", ModuleContent)
        self.module = module
        state = load_model("fixtures/demo-state.json", GameState)
        actor = state.actors["pc_1"]
        actor_state = dict(actor.state)
        actor_state.update(
            {
                "skills": {"spot": 60, "library": 50},
                "skill_labels": {"spot": "侦查", "library": "图书馆使用"},
            }
        )
        actors = dict(state.actors)
        actors["pc_1"] = actor.model_copy(update={"state": actor_state}, deep=True)
        self.store = InMemoryEngineStore()
        self.store.register_room(
            module_content=module,
            initial_state=state.model_copy(update={"actors": actors}, deep=True),
        )

    def service(self, *rolls: int) -> AdjudicationEngineService:
        return AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource(rolls)),
        )

    async def submit(self, service, action: ActionAdjudication):
        return await service.submit(
            SubmitAdjudicationRequest(
                room_id="room_01",
                player_id="player_01",
                adjudication=action,
            )
        )

    async def test_no_check_commits_registered_effect_and_replays(self) -> None:
        service = self.service()
        request = SubmitAdjudicationRequest(
            room_id="room_01",
            player_id="player_01",
            adjudication=adjudication(
                "direct-1",
                "0",
                check=NoAdjudicationCheck(),
            ),
        )

        first = await service.submit(request)
        replay = await service.submit(request)

        self.assertEqual(first.status, "resolved")
        self.assertEqual(replay.event_refs, first.event_refs)
        self.assertIn("document_truth", self.store.inspect_state("room_01").discovered_facts)
        self.assertEqual(
            [event.type for event in self.store.inspect_domain_events("room_01")],
            ["information.revealed", "action.succeeded"],
        )

    async def test_candidate_collection_is_rejected_as_a_whole(self) -> None:
        service = self.service()
        action = adjudication(
            "invalid-candidates",
            "0",
            check=PlayerChoiceAdjudicationCheck(
                candidates=(candidate("spot", "spot"), candidate("bad", "missing"))
            ),
        )

        with self.assertRaisesRegex(ContractError, "技能候选"):
            await self.submit(service, action)

        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 0)
        self.assertEqual(self.store.inspect_domain_events("room_01"), ())

    async def test_one_intent_can_atomically_create_linked_runtime_content(self) -> None:
        action = ActionAdjudication(
            request_id="runtime-content",
            source_revision="0",
            actor_id="pc_1",
            summary="登记并进入一家普通旅店",
            target=ActionTarget(kind="world", id=self.module.world_ref),
            method=ActionMethod(family="travel", description="寻找附近正常营业的旅店"),
            check=NoAdjudicationCheck(),
            success_effects=(
                EnsureRuntimeLocationEffect(
                    location_id="runtime_inn",
                    name="街角旅店",
                    connected_location_id="study",
                ),
                EnsureRuntimeEntityEffect(
                    entity_id="runtime_innkeeper",
                    entity_kind="npc",
                    name="旅店老板",
                    location_id="runtime_inn",
                ),
            ),
        )

        resolved = await self.submit(self.service(), action)

        self.assertEqual(resolved.outcome, "success")
        state = self.store.inspect_state("room_01")
        self.assertEqual(state.runtime_locations["runtime_inn"]["name"], "街角旅店")
        self.assertEqual(
            state.runtime_entities["runtime_innkeeper"]["location_id"],
            "runtime_inn",
        )

    async def test_event_rule_only_reacts_to_final_domain_event(self) -> None:
        module = self.module.model_copy(
            update={
                "event_rules": (
                    EventRuleSpec(
                        id="truth-advances-time",
                        event_type="information.revealed",
                        payload_matches={"information_id": "document_truth"},
                        effects=(AdvanceTimeEffect(minutes=15, reason="整理已揭示线索"),),
                    ),
                )
            },
            deep=True,
        )
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module,
            initial_state=self.store.inspect_state("room_01"),
        )
        service = AdjudicationEngineService(store)

        await service.submit(
            SubmitAdjudicationRequest(
                room_id="room_01",
                player_id="player_01",
                adjudication=adjudication(
                    "event-rule",
                    "0",
                    check=NoAdjudicationCheck(),
                ),
            )
        )

        self.assertEqual(store.inspect_state("room_01").clock.elapsed_minutes, 15)
        self.assertEqual(
            [event.type for event in store.inspect_domain_events("room_01")],
            [
                "information.revealed",
                "action.succeeded",
                "rule.triggered",
                "time.elapsed",
            ],
        )

    def test_event_rule_rejects_provisional_roll_trigger(self) -> None:
        with self.assertRaisesRegex(ValueError, "provisional"):
            EventRuleSpec(
                id="invalid-roll-rule",
                event_type="check.rolled",
            )

    async def test_cancel_before_roll_commits_cancelled_without_effects(self) -> None:
        service = self.service(17)
        pending = await self.submit(service, adjudication("cancel-action", "0"))
        decision = pending.pending_decision
        assert decision is not None

        cancelled = await service.decide(
            CheckDecisionRequest(
                request_id="cancel-choice",
                room_id="room_01",
                player_id="player_01",
                source_revision=pending.view_revision,
                decision_id=decision.decision_id,
                decision_version=decision.decision_version,
                choice=CancelCheckChoice(),
            )
        )

        self.assertEqual(cancelled.status, "cancelled")
        self.assertNotIn("document_truth", self.store.inspect_state("room_01").discovered_facts)
        self.assertEqual(
            [event.type for event in self.store.inspect_domain_events("room_01")],
            ["check.choice_requested", "action.cancelled"],
        )

    async def test_failed_roll_is_persisted_then_exact_luck_spend_resolves(self) -> None:
        service = self.service(64)
        pending = await self.submit(service, adjudication("luck-action", "0"))
        decision = pending.pending_decision
        assert decision is not None
        choice = CheckDecisionRequest(
            request_id="luck-select",
            room_id="room_01",
            player_id="player_01",
            source_revision=pending.view_revision,
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot"),
        )

        rolled = await service.decide(choice)
        replay = await service.decide(choice)
        run = rolled.check_run
        assert run is not None

        self.assertEqual(run.roll.value, 64)
        self.assertEqual(replay.check_run, run)
        self.assertNotIn(
            "action.failed",
            [e.type for e in self.store.inspect_domain_events("room_01")],
        )
        luck_option = next(
            option
            for option in run.post_roll_options
            if option.kind == "spend_resource"
        )
        resolved = await service.decide_post_roll(
            PostRollDecisionRequest(
                request_id="luck-resolve",
                room_id="room_01",
                player_id="player_01",
                source_revision=rolled.view_revision,
                check_id=run.check_id,
                check_version=run.version,
                option_id=luck_option.option_id,
            )
        )

        self.assertEqual(resolved.outcome, "success")
        assert resolved.check_run is not None
        self.assertEqual(resolved.check_run.roll.degree, "failure")
        self.assertEqual(resolved.check_run.final_result.degree, "regular_success")
        self.assertEqual(self.store.inspect_state("room_01").actors["pc_1"].resources.luck, 46)
        self.assertIn("document_truth", self.store.inspect_state("room_01").discovered_facts)
        event_types = [event.type for event in self.store.inspect_domain_events("room_01")]
        self.assertIn("check.resolved", event_types)
        self.assertIn("action.succeeded", event_types)

    async def test_push_rerolls_once_and_first_roll_cannot_be_cancelled(self) -> None:
        service = self.service(80, 30)
        pending = await self.submit(service, adjudication("push-action", "0"))
        decision = pending.pending_decision
        assert decision is not None
        rolled = await service.decide(
            CheckDecisionRequest(
                request_id="push-select",
                room_id="room_01",
                player_id="player_01",
                source_revision=pending.view_revision,
                decision_id=decision.decision_id,
                decision_version=decision.decision_version,
                choice=SelectCheckChoice(candidate_id="spot"),
            )
        )
        run = rolled.check_run
        assert run is not None

        with self.assertRaisesRegex(ContractError, "不能再次选择或取消"):
            await service.decide(
                CheckDecisionRequest(
                    request_id="late-cancel",
                    room_id="room_01",
                    player_id="player_01",
                    source_revision=rolled.view_revision,
                    decision_id=decision.decision_id,
                    decision_version=decision.decision_version + 1,
                    choice=CancelCheckChoice(),
                )
            )

        resolved = await service.decide_post_roll(
            PostRollDecisionRequest(
                request_id="push-resolve",
                room_id="room_01",
                player_id="player_01",
                source_revision=rolled.view_revision,
                check_id=run.check_id,
                check_version=run.version,
                option_id="push-once",
                push_adjudication=PushAdjudication(
                    method_description="先缩小年份范围，再重新检索"
                ),
            )
        )

        assert resolved.check_run is not None
        self.assertEqual(resolved.check_run.roll_count, 2)
        self.assertEqual(resolved.check_run.roll.value, 80)
        self.assertEqual(resolved.check_run.final_result.value, 30)
        self.assertEqual(resolved.outcome, "success")


if __name__ == "__main__":
    unittest.main()
