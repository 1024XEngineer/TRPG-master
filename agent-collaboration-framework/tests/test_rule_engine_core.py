from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ConditionSpec,
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    ModuleContent,
    NoCheck,
    PlayerInput,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    RuleKernel,
    SequenceDiceSource,
    audit_runtime_capabilities,
    require_runtime_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]


def load_paper_chase() -> ModuleContent:
    examples = (
        ROOT / "docs" / "module-parser" / "examples" / "module-content-validation"
    )
    for path in examples.rglob("module-content-draft.json"):
        payload = path.read_text(encoding="utf-8")
        if '"module_id": "paper-chase-zh-coc7"' in payload:
            return ModuleContent.model_validate_json(payload)
    raise AssertionError("Paper Chase ModuleContent fixture was not found")


def paper_chase_state(module: ModuleContent, *, scene_id: str) -> GameState:
    return GameState(
        room_id="room_paper_chase",
        scene_id=scene_id,
        actors={
            "pc_1": ActorState(
                player_id="player_1",
                name="Investigator",
                source_character_id="character_1",
                source_character_version=1,
                state={
                    "attributes": {"STR": 55, "LUCK": 45},
                    "derived_stats": {"HP": 11, "SAN": 60, "MP": 12},
                    "skills": {
                        "charm": 40,
                        "fast-talk": 60,
                        "fighting-brawl": 50,
                        "persuade": 50,
                    },
                },
                resources=ActorResources(
                    hp=11,
                    san=60,
                    mp=12,
                    luck=45,
                ),
            )
        },
        entities={entity.id: dict(entity.state) for entity in module.entities},
    )


def checkpoint_request(
    *,
    request_id: str,
    revision: str,
    verb: str,
    target_id: str,
    checkpoint_id: str,
    skills: tuple[str, ...] = (),
    declarations: tuple[str, ...] = (),
    roll_value: int | None = None,
) -> ActionRequest:
    return ActionRequest(
        request_id=request_id,
        room_id="room_paper_chase",
        player_id="player_1",
        actor_id="pc_1",
        source_view_revision=revision,
        intent=Intent(
            kind="action",
            verb=verb,
            target=MatchedTarget(id=target_id),
            check=ModuleCheck(
                checkpoint_id=checkpoint_id,
                proposed_skills=skills,
            ),
            declarations=declarations,
            summary=f"{verb} {target_id}",
        ),
        roll_value=roll_value,
    )


def direct_request(
    *,
    request_id: str,
    revision: str,
    verb: str,
    target_id: str,
    declarations: tuple[str, ...] = (),
) -> ActionRequest:
    return ActionRequest(
        request_id=request_id,
        room_id="room_paper_chase",
        player_id="player_1",
        actor_id="pc_1",
        source_view_revision=revision,
        intent=Intent(
            kind="action",
            verb=verb,
            target=MatchedTarget(id=target_id),
            check=NoCheck(),
            declarations=declarations,
            summary=f"{verb} {target_id}",
        ),
    )


class Coc7RuleKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_paper_chase()

    def test_paper_chase_passes_runtime_capability_audit(self) -> None:
        self.assertEqual(audit_runtime_capabilities(self.module), ())

    def test_capability_audit_rejects_unsafe_expression_before_runtime(self) -> None:
        original = self.module.module_rules[0]
        unsafe_rule = original.model_copy(
            update={"when": ConditionSpec(expr="keeper.read_secret()")}
        )
        unsafe_module = self.module.model_copy(
            update={
                "module_rules": (
                    unsafe_rule,
                    *self.module.module_rules[1:],
                )
            }
        )

        issues = audit_runtime_capabilities(unsafe_module)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].owner, f"rule:{original.id}")
        self.assertIn("expression:", issues[0].capability)
        with self.assertRaises(ContractError):
            require_runtime_capabilities(unsafe_module)

    def test_percentile_check_records_authoritative_success_level(self) -> None:
        state = paper_chase_state(self.module, scene_id="neighborhood")
        kernel = RuleKernel(
            dice_source=SequenceDiceSource([30]),
            allow_legacy_missing_skill=False,
        )

        execution, updated = kernel.execute(
            request=checkpoint_request(
                request_id="check_success",
                revision="0",
                verb="interview",
                target_id="lyla",
                checkpoint_id="question_neighbors",
                skills=("fast-talk",),
            ),
            module_content=self.module,
            game_state=state,
        )

        check = execution.action_result.check_result
        self.assertIsNotNone(check)
        assert check is not None
        self.assertEqual(check.roll_value, 30)
        self.assertEqual(check.target_value, 60)
        self.assertEqual(check.success_level, "hard")
        self.assertTrue(check.passed)
        self.assertEqual(execution.action_result.outcome, "success")
        self.assertTrue(updated.entities["lyla"]["interviewed"])
        self.assertIn("lyla_cemetery_sighting", updated.discovered_facts)

    def test_percentile_check_uses_player_submitted_roll_value(self) -> None:
        state = paper_chase_state(self.module, scene_id="neighborhood")
        kernel = RuleKernel(
            dice_source=SequenceDiceSource([99]),
            allow_legacy_missing_skill=False,
        )

        execution, _ = kernel.execute(
            request=checkpoint_request(
                request_id="submitted_roll",
                revision="0",
                verb="interview",
                target_id="lyla",
                checkpoint_id="question_neighbors",
                skills=("fast-talk",),
                roll_value=12,
            ),
            module_content=self.module,
            game_state=state,
        )

        check = execution.action_result.check_result
        self.assertIsNotNone(check)
        assert check is not None
        self.assertEqual(check.roll_value, 12)
        self.assertEqual(check.success_level, "extreme")

    def test_fumble_uses_checkpoint_failure_without_state_write(self) -> None:
        state = paper_chase_state(self.module, scene_id="neighborhood")
        kernel = RuleKernel(
            dice_source=SequenceDiceSource([99]),
            allow_legacy_missing_skill=False,
        )

        execution, updated = kernel.execute(
            request=checkpoint_request(
                request_id="check_fumble",
                revision="0",
                verb="interview",
                target_id="lyla",
                checkpoint_id="question_neighbors",
                skills=("charm",),
            ),
            module_content=self.module,
            game_state=state,
        )

        check = execution.action_result.check_result
        self.assertIsNotNone(check)
        assert check is not None
        self.assertEqual(check.success_level, "fumble")
        self.assertFalse(check.passed)
        self.assertEqual(execution.action_result.outcome, "failure")
        self.assertFalse(updated.entities["lyla"]["interviewed"])
        self.assertEqual(updated.event_sequence, 0)

    def test_attack_without_stat_block_is_blocked_after_recording_check(self) -> None:
        state = paper_chase_state(self.module, scene_id="client_briefing")
        before_target = state.entities["thomas"].copy()

        execution, updated = RuleKernel(
            dice_source=SequenceDiceSource([1]),
            allow_legacy_missing_skill=False,
        ).execute(
            request=direct_request(
                request_id="attack_thomas_without_stats",
                revision="0",
                verb="attack",
                target_id="thomas",
            ),
            module_content=self.module,
            game_state=state,
        )

        self.assertEqual(execution.action_result.resolution, "blocked")
        self.assertEqual(execution.action_result.outcome, "not_applicable")
        self.assertIsNotNone(execution.action_result.check_result)
        self.assertEqual(execution.events, ())
        self.assertEqual(updated.event_sequence, state.event_sequence)
        self.assertEqual(updated.entities["thomas"], before_target)
        self.assertIn(
            "战斗数据",
            "".join(item.text for item in execution.action_result.visible_facts),
        )

    def test_attack_with_missing_hp_is_blocked_without_state_change(self) -> None:
        module = self.module.model_copy(
            update={
                "entities": tuple(
                    entity.model_copy(
                        update={
                            "stat_block": entity.stat_block.model_copy(
                                update={"HP": None}
                            )
                        }
                    )
                    if entity.id == "cemetery_figure"
                    else entity
                    for entity in self.module.entities
                )
            }
        )
        state = paper_chase_state(module, scene_id="night_surveillance")
        state.entities["cemetery_figure"]["sighted"] = True
        before_target = state.entities["cemetery_figure"].copy()

        execution, updated = RuleKernel(
            dice_source=SequenceDiceSource([1]),
            allow_legacy_missing_skill=False,
        ).execute(
            request=direct_request(
                request_id="attack_cemetery_figure_without_hp",
                revision="0",
                verb="attack",
                target_id="cemetery_figure",
            ),
            module_content=module,
            game_state=state,
        )

        self.assertEqual(execution.action_result.resolution, "blocked")
        self.assertEqual(execution.action_result.outcome, "not_applicable")
        self.assertEqual(execution.events, ())
        self.assertEqual(updated.event_sequence, state.event_sequence)
        self.assertEqual(updated.entities["cemetery_figure"], before_target)

    def test_state_change_hook_resolves_first_sight_sanity_check(self) -> None:
        state = paper_chase_state(self.module, scene_id="night_surveillance")
        state.entities["cemetery_figure"]["visit_observed"] = True
        state.entities["cemetery_figure"]["sighted"] = True
        kernel = RuleKernel(
            dice_source=SequenceDiceSource([30]),
            allow_legacy_missing_skill=False,
        )

        execution, updated = kernel.execute(
            request=checkpoint_request(
                request_id="call_figure",
                revision="0",
                verb="call_name",
                target_id="cemetery_figure",
                checkpoint_id="call_to_figure",
            ),
            module_content=self.module,
            game_state=state,
        )

        self.assertEqual(execution.action_result.outcome, "success")
        self.assertEqual(updated.scene_id, "conversation")
        self.assertTrue(updated.entities["cemetery_figure"]["true_form_seen"])
        self.assertTrue(updated.entities["case_tracker"]["first_ghoul_sight_resolved"])
        self.assertEqual(updated.actors["pc_1"].resources.san, 60)

    def test_interaction_override_and_attack_override_are_authoritative(self) -> None:
        crypt_state = paper_chase_state(self.module, scene_id="crypt")
        crypt_state.entities["crypt_entrance"]["discovered"] = True
        kernel = RuleKernel(allow_legacy_missing_skill=False)
        crypt_execution, after_crypt = kernel.execute(
            request=direct_request(
                request_id="enter_crypt",
                revision="0",
                verb="enter",
                target_id="crypt_entrance",
            ),
            module_content=self.module,
            game_state=crypt_state,
        )

        self.assertEqual(crypt_execution.action_result.outcome, "success")
        self.assertEqual(after_crypt.scene_id, "conversation")
        self.assertIn(
            "unconscious_until_night",
            after_crypt.actors["pc_1"].conditions,
        )

        prepared_state = paper_chase_state(self.module, scene_id="crypt")
        prepared_state.entities["crypt_entrance"].update(
            {
                "discovered": True,
                "slab_moved": True,
            }
        )
        prepared_execution, after_prepared_entry = kernel.execute(
            request=checkpoint_request(
                request_id="enter_crypt_prepared",
                revision="0",
                verb="enter",
                target_id="crypt_entrance",
                checkpoint_id="enter_crypt",
                declarations=("hold_breath",),
            ),
            module_content=self.module,
            game_state=prepared_state,
        )

        self.assertEqual(prepared_execution.action_result.outcome, "success")
        self.assertEqual(after_prepared_entry.scene_id, "conversation")
        self.assertNotIn(
            "unconscious_until_night",
            after_prepared_entry.actors["pc_1"].conditions,
        )

        unauthorized_state = paper_chase_state(self.module, scene_id="crypt")
        unauthorized_state.entities["crypt_entrance"].update(
            {
                "discovered": True,
                "slab_moved": True,
            }
        )
        with self.assertRaisesRegex(
            ContractError,
            "outside the checkpoint catalog",
        ):
            kernel.execute(
                request=checkpoint_request(
                    request_id="enter_crypt_unauthorized",
                    revision="0",
                    verb="enter",
                    target_id="crypt_entrance",
                    checkpoint_id="enter_crypt",
                    declarations=("cover_nose",),
                ),
                module_content=self.module,
                game_state=unauthorized_state,
            )

        crowd_state = paper_chase_state(
            self.module,
            scene_id="ghoul_confrontation",
        )
        crowd_state.entities["ghoul_crowd"]["revealed"] = True
        crowd_execution, after_crowd = kernel.execute(
            request=direct_request(
                request_id="attack_crowd",
                revision="0",
                verb="attack",
                target_id="ghoul_crowd",
            ),
            module_content=self.module,
            game_state=crowd_state,
        )

        self.assertEqual(crowd_execution.action_result.outcome, "success")
        self.assertTrue(after_crowd.entities["ghoul_crowd"]["hostile"])
        self.assertTrue(
            after_crowd.entities["case_tracker"]["investigator_disappeared"]
        )
        self.assertIn("unconscious", after_crowd.actors["pc_1"].conditions)
        self.assertEqual(after_crowd.ending_id, "ending_followed_underground")

    def test_wait_until_night_dispatches_time_hook(self) -> None:
        state = paper_chase_state(self.module, scene_id="client_briefing")
        execution, updated = RuleKernel(
            allow_legacy_missing_skill=False,
        ).execute(
            request=direct_request(
                request_id="wait_for_night",
                revision="0",
                verb="wait_until_night",
                target_id="thomas",
            ),
            module_content=self.module,
            game_state=state,
        )

        self.assertEqual(execution.action_result.outcome, "success")
        self.assertEqual(updated.clock.elapsed_minutes, 60)
        self.assertEqual(updated.clock.time_of_day, "night")
        self.assertTrue(updated.entities["case_tracker"]["surveillance_available"])


class PaperChaseRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_attack_is_idempotently_persisted_without_state_change(
        self,
    ) -> None:
        module = load_paper_chase()
        state = paper_chase_state(module, scene_id="client_briefing")
        store = InMemoryEngineStore()
        store.register_room(module_content=module, initial_state=state)
        service = RuleEngineService(
            store,
            kernel=RuleKernel(
                dice_source=SequenceDiceSource([1]),
                allow_legacy_missing_skill=False,
            ),
        )
        request = direct_request(
            request_id="persisted_blocked_attack",
            revision="0",
            verb="attack",
            target_id="thomas",
        )

        first = await service.execute(request)
        replay = await service.execute(request)

        self.assertEqual(first.resolution, "blocked")
        self.assertEqual(first.outcome, "not_applicable")
        self.assertEqual(replay, first)
        self.assertIsNotNone(
            store.inspect_completed_action(state.room_id, request.request_id)
        )
        self.assertEqual(store.inspect_state(state.room_id).event_sequence, 0)

    async def test_conversation_updates_resources_projection_and_ending(self) -> None:
        module = load_paper_chase()
        state = paper_chase_state(module, scene_id="conversation")
        state.entities["cemetery_figure"]["willing_to_talk"] = True
        store = InMemoryEngineStore()
        store.register_room(module_content=module, initial_state=state)
        service = RuleEngineService(
            store,
            kernel=RuleKernel(
                dice_source=SequenceDiceSource([4, 2]),
                allow_legacy_missing_skill=False,
            ),
        )
        player_input = PlayerInput(
            room_id=state.room_id,
            player_id="player_1",
            actor_id="pc_1",
            client_action_id="read",
            utterance="和道格拉斯谈谈",
        )

        before = await service.read(player_input)
        self.assertEqual(
            {option.id for option in before.checkpoint_options},
            {"talk_to_figure"},
        )

        talk_request = checkpoint_request(
            request_id="talk",
            revision=before.revision,
            verb="talk",
            target_id="cemetery_figure",
            checkpoint_id="talk_to_figure",
        )
        talk = await service.execute(talk_request)
        after_talk = store.inspect_state(state.room_id)
        self.assertEqual(after_talk.actors["pc_1"].resources.san, 58)
        self.assertEqual(after_talk.actors["pc_1"].resources.mythos, 3)
        self.assertTrue(after_talk.entities["cemetery_figure"]["truth_told"])
        self.assertTrue(after_talk.entities["case_tracker"]["investigation_resolved"])
        self.assertIn("douglas_true_nature", after_talk.discovered_facts)
        self.assertTrue(talk.visible_facts)

        replay = await service.execute(talk_request)
        self.assertEqual(replay.event_refs, talk.event_refs)
        self.assertEqual(
            store.inspect_state(state.room_id).event_sequence,
            after_talk.event_sequence,
        )

        projected = await service.read(player_input)
        self.assertEqual(
            {option.id for option in projected.checkpoint_options},
            {
                "talk_to_figure",
                "let_douglas_leave",
                "follow_douglas_underground",
            },
        )
        self.assertEqual(
            {fact.id for fact in projected.visible_facts},
            {"douglas_true_nature", "douglas_confession"},
        )

        ending = await service.execute(
            checkpoint_request(
                request_id="leave",
                revision=projected.revision,
                verb="let_leave",
                target_id="cemetery_figure",
                checkpoint_id="let_douglas_leave",
            )
        )
        final_state = store.inspect_state(state.room_id)
        self.assertEqual(ending.outcome, "success")
        self.assertEqual(final_state.phase, "ended")
        self.assertEqual(final_state.ending_id, "ending_douglas_departs")


if __name__ == "__main__":
    unittest.main()
