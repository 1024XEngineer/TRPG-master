"""ModuleContent v3 contract and semantic validation (#212 §13.1).

The fixture below is a miniature but complete module: two locations joined by a
gated edge, a keeper-only Information reachable through an adaptive source, a
knowledge goal feeding the core resolution, an `agent_match` rule whose options
route to real branches, and an `event` rule chaining off the effect the first one
commits. Every negative test mutates exactly one thing in it, so a failure names
the rule that broke rather than the fixture.
"""

from __future__ import annotations

import copy
import unittest
from typing import Any

from pydantic import ValidationError

from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.module import validate_module_v3, validate_module_v3_json


def module_payload() -> dict[str, Any]:
    return {
        "module_id": "paper_chase_v3",
        "version": "3.0.0",
        "world_ref": "coc-7e",
        "background": "禁酒令时期的阿诺兹堡。",
        "information": [
            {
                "id": "cemetery_dance_report",
                "kind": "clue",
                "title": "墓地旧闻",
                "keeper_content": "报道与地下食尸鬼活动有关。",
                "player_content": "旧报报道有人在墓地看见怪异舞蹈和脚印。",
                "criticality": "essential",
                "recovery": {
                    "policy": "adaptive",
                    "allowed_source_types": ["public_record", "runtime_entity"],
                },
            }
        ],
        "knowledge_goals": [
            {
                "id": "learn_cemetery_connection",
                "target_information_ids": ["cemetery_dance_report"],
                "completion": "all",
                "required_for_core_resolution": True,
            }
        ],
        "entities": [
            {
                "id": "newspaper_archive",
                "kind": "object",
                "name": "墓地旧闻档案",
                "located_in": "library",
            },
            {
                "id": "library_door",
                "kind": "object",
                "name": "图书馆大门",
                "located_in": "library",
            },
        ],
        "locations": [
            {"id": "arnoldsburg", "kind": "region", "name": "阿诺兹堡"},
            {
                "id": "library",
                "kind": "site",
                "name": "阿诺兹堡图书馆",
                "parent_location_id": "arnoldsburg",
                "region_id": "arnoldsburg",
            },
        ],
        "location_edges": [
            {
                "id": "edge_region_to_library",
                "from_location_id": "arnoldsburg",
                "to_location_id": "library",
                "traversal": "gated",
                "access_point_id": "library_door",
                "conditions": [
                    {
                        "op": "predicate",
                        "predicate": "entity_state_is",
                        "args": {
                            "entity_id": "library_door",
                            "key": "unlocked",
                            "value": True,
                        },
                    }
                ],
                "travel_cost": {"minutes": 10},
            }
        ],
        "rules": [
            {
                "id": "research_library_archive",
                "trigger": {
                    "kind": "agent_match",
                    "scope": {
                        "action_families": ["research"],
                        "location_ids": ["library"],
                        "target_kinds": ["entity"],
                        "target_ids": ["newspaper_archive"],
                    },
                    "question": {
                        "kind": "method",
                        "semantic_hints": ["查阅旧报", "翻找档案"],
                    },
                    "options": [
                        {"id": "by_date", "semantic_hints": ["按年份检索"]},
                        {"id": "by_keyword", "semantic_hints": ["按关键词检索"]},
                    ],
                },
                "execution": {
                    "branches": [
                        {"id": "by_date", "entry_step_id": "roll_library"},
                        {"id": "by_keyword", "entry_step_id": "roll_library"},
                    ],
                    "steps": [
                        {
                            "id": "roll_library",
                            "kind": "check",
                            "check": {
                                "profile_id": "coc7.skill",
                                "actor_binding": "actor",
                                "initiation_kind": "active_action",
                                "difficulty": "regular",
                            },
                            "result_routes": {
                                "critical_success": "reveal",
                                "extreme_success": "reveal",
                                "hard_success": "reveal",
                                "regular_success": "reveal",
                                "failure": "done",
                                "fumble": "done",
                            },
                        },
                        {
                            "id": "reveal",
                            "kind": "effect",
                            "effect": {
                                "type": "reveal_information",
                                "information_id": "cemetery_dance_report",
                                "scope": "party",
                            },
                            "next_step_id": "done",
                        },
                        {"id": "done", "kind": "finish"},
                    ],
                },
            },
            {
                "id": "archive_marks_searched",
                "trigger": {
                    "kind": "event",
                    "event_type": "information.revealed",
                    "when": {
                        "op": "predicate",
                        "predicate": "information_is",
                        "args": {"id": "cemetery_dance_report"},
                    },
                    "entry_branch_id": "default",
                },
                "execution": {
                    "branches": [{"id": "default", "entry_step_id": "mark"}],
                    "steps": [
                        {
                            "id": "mark",
                            "kind": "effect",
                            "effect": {
                                "type": "change_entity_state",
                                "entity_id": "newspaper_archive",
                                "key": "searched",
                                "value": True,
                            },
                            "next_step_id": "end",
                        },
                        {"id": "end", "kind": "finish"},
                    ],
                },
            },
        ],
        "core_resolution": {
            "required_goal_ids": ["learn_cemetery_connection"],
            "completion": "all",
        },
        "ending_policy": {
            "allow_continue_after_core_resolution": True,
            "facets": ["case_outcome"],
        },
        "ending_anchors": [
            {
                "id": "report_the_truth",
                "tone": "somber",
                "required_fact_refs": ["cemetery_dance_report"],
            }
        ],
        "presentation": {
            "title": "追书人",
            "synopsis": "五本失窃的旧书，和一位失踪一年的叔叔。",
            "players_min": 1,
            "players_max": 4,
            "difficulty": 2,
            "estimated_duration": "4-6 小时",
            "player_intro_pages": [
                {"title": "委托", "content": "托马斯请你找回叔叔的藏书。"}
            ],
        },
        "initial_state": {
            "start_location_id": "arnoldsburg",
            "start_time_point_id": "hour_12",
        },
        "world_profile": {"era": "1920s", "region": "美国密歇根"},
    }


def mutate(**changes: Any) -> dict[str, Any]:
    payload = copy.deepcopy(module_payload())
    payload.update(changes)
    return payload


class ModuleContentV3ContractTests(unittest.TestCase):
    def test_voice_profile_is_supported_for_npc(self) -> None:
        payload = module_payload()
        payload["entities"][0]["kind"] = "npc"
        payload["entities"][0]["voice"] = {
            "provider": "doubao",
            "resource_id": "seed-tts-2.0",
            "voice_type": "voice-a",
        }
        content = ModuleContentV3.model_validate(payload)
        self.assertEqual(content.entities[0].voice.voice_type, "voice-a")

    def test_voice_profile_is_rejected_for_object(self) -> None:
        payload = module_payload()
        payload["entities"][0]["kind"] = "object"
        payload["entities"][0]["voice"] = {
            "provider": "doubao",
            "resource_id": "seed-tts-2.0",
            "voice_type": "voice-a",
        }
        with self.assertRaises(ValidationError):
            ModuleContentV3.model_validate(payload)

    def test_reference_module_validates(self) -> None:
        report = validate_module_v3(module_payload())
        self.assertEqual(report.status, "pass", report.errors)
        self.assertTrue(report.is_valid)

    def test_json_entry_point_matches(self) -> None:
        import json

        report = validate_module_v3_json(json.dumps(module_payload(), ensure_ascii=False))
        self.assertEqual(report.status, "pass", report.errors)

    def test_v3_root_matches_the_frozen_field_list(self) -> None:
        # #212 §3.1 names these; drifting from them silently would desync every
        # downstream consumer.
        self.assertLessEqual(
            {
                "information",
                "entities",
                "locations",
                "rules",
                "core_resolution",
                "ending_policy",
                "ending_anchors",
                "presentation",
                "initial_state",
                "world_profile",
            },
            set(ModuleContentV3.model_fields),
        )
        self.assertEqual(ModuleContentV3.model_config.get("extra"), "forbid")

    def test_unknown_root_field_is_rejected(self) -> None:
        report = validate_module_v3(mutate(checkpoints=[]))
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.errors[0].code, "MODULE_V3_SCHEMA_INVALID")


class ReferenceIntegrityTests(unittest.TestCase):
    def assert_single_error(self, payload: dict[str, Any], code: str) -> None:
        report = validate_module_v3(payload)
        self.assertEqual(report.status, "needs_revision")
        self.assertEqual([issue.code for issue in report.errors], [code], report.errors)

    def test_goal_pointing_at_missing_information(self) -> None:
        payload = mutate()
        payload["knowledge_goals"][0]["target_information_ids"] = ["nope"]
        self.assert_single_error(payload, "MODULE_V3_INFORMATION_NOT_FOUND")

    def test_entity_in_missing_location(self) -> None:
        payload = mutate()
        payload["entities"][0]["located_in"] = "nowhere"
        self.assert_single_error(payload, "MODULE_V3_LOCATION_NOT_FOUND")

    def test_edge_access_point_must_be_an_entity(self) -> None:
        payload = mutate()
        payload["location_edges"][0]["access_point_id"] = "not_an_entity"
        self.assert_single_error(payload, "MODULE_V3_ENTITY_NOT_FOUND")

    def test_effect_revealing_missing_information(self) -> None:
        payload = mutate()
        payload["rules"][0]["execution"]["steps"][1]["effect"]["information_id"] = "ghost"
        self.assert_single_error(payload, "MODULE_V3_INFORMATION_NOT_FOUND")

    def test_core_resolution_pointing_at_missing_goal(self) -> None:
        payload = mutate()
        payload["core_resolution"]["required_goal_ids"] = ["missing_goal"]
        self.assert_single_error(payload, "MODULE_V3_GOAL_NOT_FOUND")

    def test_initial_state_start_location_must_exist(self) -> None:
        payload = mutate()
        payload["initial_state"]["start_location_id"] = "elsewhere"
        self.assert_single_error(payload, "MODULE_V3_LOCATION_NOT_FOUND")

    def test_initial_time_point_must_exist(self) -> None:
        payload = mutate()
        payload["initial_state"]["start_time_point_id"] = "hour_99"
        self.assert_single_error(payload, "MODULE_V3_TIME_POINT_NOT_FOUND")

    def test_location_parent_cycle_is_rejected(self) -> None:
        payload = mutate()
        payload["locations"][0]["parent_location_id"] = "library"
        self.assert_single_error(payload, "MODULE_V3_LOCATION_CYCLE")

    def test_every_problem_is_reported_together(self) -> None:
        # The whole point of collecting instead of raising.
        payload = mutate()
        payload["knowledge_goals"][0]["target_information_ids"] = ["nope"]
        payload["entities"][0]["located_in"] = "nowhere"
        payload["initial_state"]["start_location_id"] = "elsewhere"
        report = validate_module_v3(payload)
        self.assertEqual(len(report.errors), 3, report.errors)


class RuleGraphTests(unittest.TestCase):
    def test_agent_match_hint_equal_to_family_is_rejected(self) -> None:
        payload = mutate()
        payload["rules"][0]["trigger"]["question"]["semantic_hints"] = [
            " Research "
        ]
        report = validate_module_v3(payload)
        self.assertEqual(
            [issue.code for issue in report.errors],
            ["MODULE_V3_AGENT_MATCH_HINT_EQUALS_ACTION_FAMILY"],
        )
        self.assertEqual(
            report.errors[0].path,
            "rules.0.trigger.question.semantic_hints.0",
        )

    def test_agent_match_hint_equal_to_option_id_is_rejected(self) -> None:
        payload = mutate()
        payload["rules"][0]["trigger"]["question"]["semantic_hints"] = [
            " by_date "
        ]
        report = validate_module_v3(payload)
        self.assertEqual(
            [issue.code for issue in report.errors],
            ["MODULE_V3_AGENT_MATCH_HINT_EQUALS_OPTION_ID"],
        )

    def test_agent_match_duplicate_hints_are_rejected_after_normalization(self) -> None:
        payload = mutate()
        payload["rules"][0]["trigger"]["question"]["semantic_hints"] = [
            "查阅旧报",
            " 查阅旧报 ",
        ]
        report = validate_module_v3(payload)
        self.assertEqual(
            [issue.code for issue in report.errors],
            ["MODULE_V3_AGENT_MATCH_HINT_DUPLICATE"],
        )

    def test_agent_match_option_without_a_branch_is_rejected(self) -> None:
        payload = mutate()
        payload["rules"][0]["trigger"]["options"].append(
            {"id": "by_author", "semantic_hints": ["按作者检索"]}
        )
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("候选没有对应分支", str(raised.exception))

    def test_event_rule_entry_branch_must_exist(self) -> None:
        payload = mutate()
        payload["rules"][1]["trigger"]["entry_branch_id"] = "ghost_branch"
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("entry_branch_id 不存在", str(raised.exception))

    def test_step_pointing_at_a_missing_step_is_rejected(self) -> None:
        payload = mutate()
        payload["rules"][0]["execution"]["steps"][1]["next_step_id"] = "nowhere"
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("指向不存在的步骤", str(raised.exception))

    def test_unreachable_step_is_reported(self) -> None:
        payload = mutate()
        payload["rules"][1]["execution"]["steps"].append(
            {"id": "orphan", "kind": "finish"},
        )
        report = validate_module_v3(payload)
        self.assertEqual(
            [issue.code for issue in report.errors],
            ["MODULE_V3_RULE_STEP_UNREACHABLE"],
            report.errors,
        )

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        payload = mutate()
        payload["rules"][1]["id"] = payload["rules"][0]["id"]
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("Rule id 必须唯一", str(raised.exception))


class DomainRuleTests(unittest.TestCase):
    def test_rule_cannot_bypass_ending_draft_confirmation(self) -> None:
        payload = mutate()
        payload["rules"][0]["execution"]["steps"][1]["effect"] = {
            "type": "commit_terminal_ending",
            "ending_id": payload["ending_anchors"][0]["id"],
        }
        report = validate_module_v3(payload)
        self.assertEqual(
            [issue.code for issue in report.errors],
            ["MODULE_V3_DIRECT_ENDING_FORBIDDEN"],
            report.errors,
        )

    def test_strict_information_must_declare_its_sources(self) -> None:
        payload = mutate()
        payload["information"][0]["recovery"] = {"policy": "strict", "allowed_source_types": []}
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("strict Information 必须声明 allowed_source_types", str(raised.exception))

    def test_time_points_must_be_ordered_and_contiguous(self) -> None:
        payload = mutate()
        payload["time_policy"] = {
            "default_points": [
                {"id": "hour_12", "hour_of_day": 12, "order": 0},
                {"id": "hour_06", "hour_of_day": 6, "order": 1},
            ]
        }
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("hour_of_day 必须随 order 严格递增", str(raised.exception))

    def test_default_time_policy_is_the_frozen_four_points(self) -> None:
        content = ModuleContentV3.model_validate(module_payload())
        self.assertEqual(
            [point.id for point in content.time_policy.default_points],
            ["hour_00", "hour_06", "hour_12", "hour_18"],
        )

    def test_authored_entities_cannot_claim_runtime_origin(self) -> None:
        # Runtime content is created by the Engine after an Agent proposal and
        # must never be smuggled in through the module file (#212 §8.2).
        payload = mutate()
        payload["entities"][0]["origin"] = "runtime"
        with self.assertRaises(ValidationError):
            ModuleContentV3.model_validate(payload)

    def test_self_parenting_location_is_rejected(self) -> None:
        payload = mutate()
        payload["locations"][1]["parent_location_id"] = "library"
        with self.assertRaises(ValidationError) as raised:
            ModuleContentV3.model_validate(payload)
        self.assertIn("不能以自己为父地点", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
