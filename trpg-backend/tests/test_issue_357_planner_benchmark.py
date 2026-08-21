from __future__ import annotations

from tests.benchmarks.issue_357_corpus import CASES
from tests.benchmarks.issue_357_planner import _aggregate, _contexts


def test_legacy_and_semantic_corpus_contexts_share_player_visible_facts() -> None:
    legacy, semantic = _contexts(CASES[0], run_number=0)

    assert legacy.player_input == semantic.player_input
    assert legacy.player_view.revision == semantic.planning_view.revision
    assert legacy.player_view.scene.name == semantic.planning_view.current_scene_name
    assert {item.name for item in legacy.player_view.scene.visible_entities} == {
        item.name for item in semantic.planning_view.visible_entities
    }
    assert {
        item.destination.name
        for item in legacy.player_view.scene.available_exits
        if item.destination is not None
    } == {item.name for item in semantic.planning_view.available_destinations}


def test_semantic_corpus_context_excludes_keeper_and_adjudication_fields() -> None:
    legacy, semantic = _contexts(CASES[0], run_number=0)

    assert legacy.keeper_capabilities is not None
    serialized = semantic.model_dump(mode="json")
    assert "keeper_capabilities" not in serialized
    assert "checkpoint_options" not in serialized["planning_view"]
    assert "target_id" not in serialized["planning_view"]


def test_planner_aggregate_discards_case_and_failure_details() -> None:
    aggregate = _aggregate(
        [
            {
                "case": "safe-case",
                "cohort": "multi",
                "failure_code": None,
                "duration_ms": 100.0,
                "expected_step_count": 2,
                "actual_step_count": 2,
                "step_count_correct": True,
                "kind_sequence_correct": True,
                "first_structure_success": True,
                "model_calls": 1,
                "transport_calls": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "transport_retries": 0,
                "structured_retries": 0,
            }
        ]
    )

    assert aggregate["step_count_accuracy"] == 1.0
    assert aggregate["kind_sequence_accuracy"] == 1.0
    assert "case" not in aggregate
    assert "cohort" not in aggregate
