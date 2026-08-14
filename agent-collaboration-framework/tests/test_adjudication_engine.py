from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    AdjudicationValidationError,
    CancelCheckChoice,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    CommitTerminalEndingEffect,
    ConsumeEntityEffect,
    ContractError,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    EventRuleSpec,
    GetAdjudicationStatusRequest,
    HideInformationEffect,
    MarkCoreResolvedEffect,
    ModuleContent,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerChoiceAdjudicationCheck,
    PostRollDecisionRequest,
    PushAdjudication,
    RequiredAdjudicationCheck,
    RevealInformationEffect,
    SelectCheckChoice,
    SetEndingAvailabilityEffect,
    SetVisibilityEffect,
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
        check=check
        or RequiredAdjudicationCheck(candidates=(candidate("spot", "spot"),)),
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
        self.assertIn(
            "document_truth", self.store.inspect_state("room_01").discovered_facts
        )
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

    async def test_one_intent_can_atomically_create_linked_runtime_content(
        self,
    ) -> None:
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

    async def test_persistent_travel_can_create_and_enter_runtime_location(
        self,
    ) -> None:
        action = ActionAdjudication(
            request_id="create-and-enter-runtime-location",
            source_revision="0",
            actor_id="pc_1",
            summary="进入一家普通旅店",
            target=ActionTarget(kind="location", id="study"),
            method=ActionMethod(family="travel", description="寻找并进入附近的旅店"),
            persistence_intent="location",
            check=NoAdjudicationCheck(),
            success_effects=(
                EnsureRuntimeLocationEffect(
                    location_id="runtime_inn",
                    name="街角旅店",
                    connected_location_id="study",
                ),
                EnterLocationEffect(location_id="runtime_inn"),
            ),
        )

        resolved = await self.submit(self.service(), action)

        self.assertEqual(resolved.outcome, "success")
        state = self.store.inspect_state("room_01")
        self.assertEqual(state.scene_id, "runtime_inn")
        self.assertIn("runtime_inn", state.runtime_locations)

    async def test_legacy_runtime_entity_cannot_fake_inventory_custody(
        self,
    ) -> None:
        action = ActionAdjudication(
            request_id="create-and-pick-up-runtime-item",
            source_revision="0",
            actor_id="pc_1",
            summary="捡起地上的石子",
            target=ActionTarget(kind="location", id="study"),
            method=ActionMethod(family="pick_up", description="捡起一枚普通石子"),
            persistence_intent="inventory",
            check=NoAdjudicationCheck(),
            success_effects=(
                EnsureRuntimeEntityEffect(
                    entity_id="ordinary_pebble",
                    entity_kind="object",
                    name="一枚普通石子",
                    location_id="study",
                ),
                MoveEntityEffect(
                    entity_id="ordinary_pebble",
                    holder_actor_id="pc_1",
                ),
            ),
        )

        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.submit(self.service(), action)

        self.assertEqual(
            raised.exception.result.code,
            "INVENTORY_TARGET_NOT_PORTABLE",
        )
        self.assertNotIn(
            "ordinary_pebble",
            self.store.inspect_state("room_01").runtime_entities,
        )

    async def test_event_rule_only_reacts_to_final_domain_event(self) -> None:
        module = self.module.model_copy(
            update={
                "event_rules": (
                    EventRuleSpec(
                        id="truth-marks-core-resolved",
                        event_type="information.revealed",
                        payload_matches={"information_id": "document_truth"},
                        effects=(MarkCoreResolvedEffect(),),
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

        self.assertTrue(store.inspect_state("room_01").core_resolved)
        self.assertEqual(
            [event.type for event in store.inspect_domain_events("room_01")],
            [
                "information.revealed",
                "action.succeeded",
                "rule.triggered",
                "core.resolved",
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
        self.assertNotIn(
            "document_truth", self.store.inspect_state("room_01").discovered_facts
        )
        self.assertEqual(
            [event.type for event in self.store.inspect_domain_events("room_01")],
            ["check.choice_requested", "action.cancelled"],
        )

    async def test_recover_action_returns_frozen_context_after_decision(self) -> None:
        service = self.service(80)
        action = adjudication("recover-action", "0")
        pending = await self.submit(service, action)
        recovery = await service.recover_action(
            GetAdjudicationStatusRequest(
                room_id="room_01",
                player_id="player_01",
                action_request_id=action.request_id,
            )
        )

        assert recovery is not None
        self.assertEqual(recovery.summary, action.summary)
        self.assertEqual(recovery.actor_id, action.actor_id)
        self.assertEqual(recovery.execution.status, "awaiting_skill_choice")

        decision = pending.pending_decision
        assert decision is not None
        selected = await service.decide(
            CheckDecisionRequest(
                request_id="recover-select",
                room_id="room_01",
                player_id="player_01",
                source_revision=pending.view_revision,
                decision_id=decision.decision_id,
                decision_version=decision.decision_version,
                choice=SelectCheckChoice(candidate_id="spot"),
            )
        )
        recovered = await service.recover_action(
            GetAdjudicationStatusRequest(
                room_id="room_01",
                player_id="player_01",
                action_request_id=action.request_id,
            )
        )

        assert recovered is not None
        self.assertEqual(recovered.execution, selected)
        self.assertEqual(recovered.execution.action_request_id, action.request_id)
        self.assertEqual(
            len(self.store.inspect_domain_events("room_01")),
            len(selected.event_refs) + 1,
        )

    async def test_failed_roll_is_persisted_then_exact_luck_spend_resolves(
        self,
    ) -> None:
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
        self.assertEqual(resolved.check_run.resolution_kind, "spend_luck")
        self.assertEqual(resolved.check_run.luck_spent, 4)
        self.assertEqual(
            self.store.inspect_state("room_01").actors["pc_1"].resources.luck, 46
        )
        self.assertIn(
            "document_truth", self.store.inspect_state("room_01").discovered_facts
        )
        event_types = [
            event.type for event in self.store.inspect_domain_events("room_01")
        ]
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

    async def test_authority_mapping_is_internal_and_covers_all_effect_variants(
        self,
    ) -> None:
        service = self.service()
        async with self.store.transaction("room_01") as transaction:
            runtime = await transaction.load_runtime()
        runtime_state = runtime.game_state.model_copy(
            update={"runtime_entities": {"runtime_npc": {"name": "路人"}}},
            deep=True,
        )
        runtime = runtime.model_copy(update={"game_state": runtime_state}, deep=True)
        effects = (
            NarrativeOnlyEffect(),
            EnsureRuntimeLocationEffect(
                location_id="runtime_inn",
                name="旅店",
                connected_location_id="study",
            ),
            EnsureRuntimeEntityEffect(
                entity_id="runtime_keeper",
                entity_kind="npc",
                name="店主",
                location_id="study",
            ),
            EnterLocationEffect(location_id="study"),
            MoveEntityEffect(entity_id="butler", location_id="study"),
            MoveEntityEffect(entity_id="butler", holder_actor_id="pc_1"),
            AdvanceWorldTimeEffect(),
            RevealInformationEffect(information_id="document_truth"),
            HideInformationEffect(information_id="document_truth"),
            ChangeEntityStateEffect(entity_id="runtime_npc", key="mood", value="calm"),
            ChangeEntityStateEffect(entity_id="butler", key="mood", value="calm"),
            ConsumeEntityEffect(entity_id="butler"),
            SetVisibilityEffect(
                target_kind="information",
                target_id="document_truth",
                visible=True,
            ),
            SetVisibilityEffect(
                target_kind="entity",
                target_id="runtime_npc",
                visible=True,
            ),
            SetVisibilityEffect(
                target_kind="location",
                target_id="study",
                visible=True,
            ),
            MarkCoreResolvedEffect(),
            SetEndingAvailabilityEffect(available=True),
            CommitTerminalEndingEffect(ending_id="ending_document_recovered"),
        )

        level, details = service._classify_effects(
            runtime,
            effects,
            branch="selected",
        )

        self.assertEqual(level, "L5")
        self.assertEqual(
            tuple(detail.authority_level for detail in details),
            (
                "L0",
                "L1",
                "L1",
                "L2",
                "L2",
                "L3",
                "L2",
                "L2",
                "L2",
                "L1",
                "L3",
                "L3",
                "L2",
                "L1",
                "L3",
                "L4",
                "L4",
                "L5",
            ),
        )
        self.assertEqual(
            service._classify_effects(runtime, (), branch="selected")[0], None
        )
        self.assertEqual(
            service._classify_effects(
                runtime,
                (),
                branch="selected",
                check_floor=True,
            )[0],
            "L3",
        )

    async def test_committed_authority_is_stored_outside_player_execution(self) -> None:
        request = SubmitAdjudicationRequest(
            room_id="room_01",
            player_id="player_01",
            adjudication=adjudication(
                "internal-authority",
                "0",
                check=NoAdjudicationCheck(),
            ),
        )

        execution = await self.service().submit(request)
        async with self.store.transaction("room_01") as transaction:
            completed = await transaction.find_adjudication_command(
                request.adjudication.request_id
            )

        assert completed is not None
        assert completed.validation is not None
        self.assertEqual(completed.validation.authority_level, "L2")
        self.assertEqual(completed.committed_authority_level, "L2")
        execution_json = execution.to_json_dict()
        self.assertNotIn("authority_level", execution_json)
        self.assertNotIn("committed_authority_level", execution_json)

    async def test_target_rejections_share_one_safe_projection_and_leave_no_state(
        self,
    ) -> None:
        missing = adjudication(
            "missing-target", "0", check=NoAdjudicationCheck()
        ).model_copy(
            update={"target": ActionTarget(kind="entity", id="not-visible")},
            deep=True,
        )
        with self.assertRaises(AdjudicationValidationError) as missing_error:
            await self.submit(self.service(), missing)

        shadow = ActionAdjudication(
            request_id="canon-shadow",
            source_revision="0",
            actor_id="pc_1",
            summary="创建临时地点",
            target=ActionTarget(kind="world", id=self.module.world_ref),
            method=ActionMethod(family="travel", description="寻找附近地点"),
            check=NoAdjudicationCheck(),
            success_effects=(
                EnsureRuntimeLocationEffect(
                    location_id="study",
                    name="重复书房",
                    connected_location_id="study",
                ),
            ),
        )
        with self.assertRaises(AdjudicationValidationError) as shadow_error:
            await self.submit(self.service(), shadow)

        self.assertEqual(missing_error.exception.result.code, "TARGET_NOT_FOUND")
        self.assertEqual(shadow_error.exception.result.code, "CANON_SHADOW")
        self.assertEqual(
            missing_error.exception.result.to_feedback().code,
            "TARGET_UNAVAILABLE",
        )
        self.assertEqual(
            shadow_error.exception.result.to_feedback().code,
            "TARGET_UNAVAILABLE",
        )
        self.assertNotIn(
            "authority",
            missing_error.exception.result.to_feedback().model_dump_json(),
        )
        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 0)
        self.assertEqual(self.store.inspect_domain_events("room_01"), ())

    async def test_wrong_target_kind_is_normalized_when_id_is_unambiguous(
        self,
    ) -> None:
        # 模型常把 NPC 写成 kind="actor"：`state.actors` 只有玩家角色，NPC 在
        # entity 侧。id 唯一可辨，归一后回合应照常完成。
        mislabeled = adjudication(
            "mislabeled-target", "0", check=NoAdjudicationCheck()
        ).model_copy(
            update={"target": ActionTarget(kind="actor", id="butler")},
            deep=True,
        )

        execution = await self.submit(self.service(), mislabeled)

        async with self.store.transaction("room_01") as transaction:
            completed = await transaction.find_adjudication_command("mislabeled-target")
        assert completed is not None
        # 归一后的 target 贯穿整次提交：范围匹配、效果校验和持久化拿到的是同一份。
        persisted = completed.request.adjudication.target
        self.assertEqual(persisted.kind, "entity")
        self.assertEqual(persisted.id, "butler")

        # 客户端重试会原样重发**未归一**的报文（响应丢失时尤其如此）。归一必须
        # 发生在重放比对之前，否则存下来的是归一后的 request，重试永远比对不上，
        # 恰好在被本特性修复的每一条请求上打破幂等。
        replayed = await self.submit(self.service(), mislabeled)

        self.assertEqual(replayed.request_id, execution.request_id)
        self.assertEqual(replayed.outcome, execution.outcome)
        self.assertEqual(replayed.event_refs, execution.event_refs)
        self.assertEqual(
            self.store.inspect_state("room_01").event_sequence,
            int(execution.view_revision),
        )

    async def test_ambiguous_target_id_is_rejected_instead_of_guessed(self) -> None:
        # butler 同时是 canon entity 和一个 actor id，declared kind 两边都不是：
        # 跨集合撞名时归一等于猜，必须维持拒绝。
        state = self.store.inspect_state("room_01")
        actors = dict(state.actors)
        actors["butler"] = actors["pc_1"].model_copy(deep=True)
        self.store.register_room(
            module_content=self.module,
            initial_state=state.model_copy(
                update={"actors": actors, "room_id": "room_ambiguous"},
                deep=True,
            ),
        )
        ambiguous = adjudication(
            "ambiguous-target", "0", check=NoAdjudicationCheck()
        ).model_copy(
            update={"target": ActionTarget(kind="location", id="butler")},
            deep=True,
        )

        with self.assertRaises(AdjudicationValidationError) as error:
            await self.service().submit(
                SubmitAdjudicationRequest(
                    room_id="room_ambiguous",
                    player_id="player_01",
                    adjudication=ambiguous,
                )
            )

        self.assertEqual(error.exception.result.code, "TARGET_NOT_FOUND")
        self.assertEqual(self.store.inspect_state("room_ambiguous").event_sequence, 0)

    async def test_generic_entity_cannot_acquire_inventory_custody(self) -> None:
        """A visible Canon prop is not portable unless it is an ItemInstance."""

        action = ActionAdjudication(
            request_id="take-fixed-entity",
            source_revision="0",
            actor_id="pc_1",
            summary="把当前陈设放进背包",
            target=ActionTarget(kind="entity", id="butler"),
            method=ActionMethod(family="pick_up", description="拿起当前陈设"),
            persistence_intent="inventory",
            check=NoAdjudicationCheck(),
            success_effects=(
                MoveEntityEffect(entity_id="butler", holder_actor_id="pc_1"),
            ),
        )

        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.submit(self.service(), action)

        self.assertEqual(
            raised.exception.result.code,
            "INVENTORY_TARGET_NOT_PORTABLE",
        )
        state = self.store.inspect_state("room_01")
        self.assertEqual(state.event_sequence, 0)
        self.assertNotIn("holder_actor_id", state.entities.get("butler", {}))

    async def test_l4_can_commit_while_l5_direct_ending_is_rejected(self) -> None:
        core_action = ActionAdjudication(
            request_id="core-resolution",
            source_revision="0",
            actor_id="pc_1",
            summary="完成核心目标",
            target=ActionTarget(kind="world", id=self.module.world_ref),
            method=ActionMethod(family="resolve", description="确认核心目标已完成"),
            check=NoAdjudicationCheck(),
            success_effects=(MarkCoreResolvedEffect(),),
        )
        await self.submit(self.service(), core_action)
        async with self.store.transaction("room_01") as transaction:
            completed = await transaction.find_adjudication_command(
                core_action.request_id
            )
        assert completed is not None
        self.assertEqual(completed.committed_authority_level, "L4")

        terminal_action = ActionAdjudication(
            request_id="direct-ending",
            source_revision=completed.execution.view_revision,
            actor_id="pc_1",
            summary="直接提交终局",
            target=ActionTarget(kind="world", id=self.module.world_ref),
            method=ActionMethod(family="ending", description="直接确认最终结局"),
            check=NoAdjudicationCheck(),
            success_effects=(
                CommitTerminalEndingEffect(ending_id="ending_document_recovered"),
            ),
        )
        with self.assertRaises(AdjudicationValidationError) as error:
            await self.submit(self.service(), terminal_action)
        self.assertEqual(error.exception.result.code, "ENDING_REQUIRES_DRAFT")
        self.assertEqual(self.store.inspect_state("room_01").ending_id, None)

    def test_agent_cannot_supply_authority_fields(self) -> None:
        payload = adjudication(
            "forged-authority",
            "0",
            check=NoAdjudicationCheck(),
        ).to_json_dict()
        payload["authority_level"] = "L0"

        with self.assertRaises(ValidationError):
            ActionAdjudication.model_validate(payload)

    async def test_persistent_intent_rejects_empty_success_effects_before_roll(
        self,
    ) -> None:
        action = adjudication("empty-persistent", "0").model_copy(
            update={
                "summary": "击晕守墓人",
                "target": ActionTarget(kind="entity", id="butler"),
                "method": ActionMethod(family="knock_out", description="用撬棍砸晕他"),
                "persistence_intent": "character_state",
                "success_effects": (),
            },
            deep=True,
        )
        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.submit(self.service(1), action)
        self.assertEqual(raised.exception.result.code, "PERSISTENT_EFFECT_REQUIRED")
        self.assertEqual(raised.exception.result.repairability, "auto_repairable")
        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 0)

    async def test_explicit_none_cannot_bypass_controlled_persistent_family(
        self,
    ) -> None:
        action = ActionAdjudication(
            request_id="explicit-none-persistent",
            source_revision="0",
            actor_id="pc_1",
            summary="击晕守墓人",
            target=ActionTarget(kind="entity", id="butler"),
            method=ActionMethod(family="knock_out", description="用撬棍砸晕他"),
            persistence_intent="none",
            check=NoAdjudicationCheck(),
        )

        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.submit(self.service(), action)

        self.assertEqual(raised.exception.result.code, "PERSISTENT_EFFECT_REQUIRED")
        self.assertEqual(raised.exception.result.repairability, "auto_repairable")
        self.assertEqual(self.store.inspect_state("room_01").event_sequence, 0)

    def test_persistence_intent_explicitness_survives_internal_round_trip(
        self,
    ) -> None:
        omitted = ActionAdjudication(
            request_id="omitted-persistence-intent",
            source_revision="0",
            actor_id="pc_1",
            summary="普通移动",
            target=ActionTarget(kind="location", id="study"),
            method=ActionMethod(family="travel", description="普通移动"),
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="study"),),
        )
        explicit = ActionAdjudication(
            request_id="explicit-persistence-intent",
            source_revision="0",
            actor_id="pc_1",
            summary="普通移动",
            target=ActionTarget(kind="location", id="study"),
            method=ActionMethod(family="travel", description="普通移动"),
            persistence_intent="none",
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id="study"),),
        )

        for value, expected in ((omitted, False), (explicit, True)):
            with self.subTest(expected=expected):
                payload = value.model_dump(
                    mode="json",
                    context={"preserve_persistence_intent_explicit": True},
                )
                with self.assertRaises(ValidationError):
                    ActionAdjudication.model_validate(payload)
                restored = ActionAdjudication.model_validate(
                    payload,
                    context={"allow_persistence_intent_explicit_marker": True},
                )
                self.assertEqual(restored.persistence_intent_explicit, expected)

        # 旧 store 使用普通 model_dump：默认 none 会写进 JSON，但没有 marker。
        # 可信持久化恢复必须把它当作 legacy omitted；相同 JSON 作为公开输入时，
        # 字段确实存在，仍然必须按显式 none 处理。
        legacy_payload = omitted.model_dump(mode="json")
        self.assertEqual(legacy_payload["persistence_intent"], "none")
        self.assertNotIn("persistence_intent_explicit_marker", legacy_payload)
        legacy_restored = ActionAdjudication.model_validate(
            legacy_payload,
            context={"allow_persistence_intent_explicit_marker": True},
        )
        public_restored = ActionAdjudication.model_validate(legacy_payload)
        self.assertFalse(legacy_restored.persistence_intent_explicit)
        self.assertTrue(public_restored.persistence_intent_explicit)

        self.assertNotIn(
            "persistence_intent_explicit_marker",
            explicit.to_json_dict(),
        )
        self.assertNotIn(
            "persistence_intent_explicit_marker",
            str(ActionAdjudication.model_json_schema()),
        )

    async def test_persistent_intent_accepts_unconscious_state_and_publishes_evidence(
        self,
    ) -> None:
        action = adjudication(
            "valid-persistent", "0", check=NoAdjudicationCheck()
        ).model_copy(
            update={
                "summary": "击晕守墓人",
                "target": ActionTarget(kind="entity", id="butler"),
                "method": ActionMethod(family="knock_out", description="用撬棍砸晕他"),
                "persistence_intent": "character_state",
                "success_effects": (
                    ChangeEntityStateEffect(
                        entity_id="butler",
                        key="consciousness",
                        value="unconscious",
                    ),
                ),
            },
            deep=True,
        )
        result = await self.submit(self.service(), action)
        self.assertEqual(result.committed_results[0].state_value, "unconscious")
        self.assertIn(
            "consciousness",
            self.store.inspect_state("room_01").public_entity_state_keys["butler"],
        )


if __name__ == "__main__":
    unittest.main()
