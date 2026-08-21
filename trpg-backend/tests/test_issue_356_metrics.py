from __future__ import annotations

import pytest

from tests.benchmarks.issue_356_metrics import (
    aggregate_scenario,
    assert_sanitized_report,
    nearest_rank_percentile,
)


def test_nearest_rank_percentile_uses_a_documented_deterministic_method() -> None:
    assert nearest_rank_percentile([], 50) is None
    assert nearest_rank_percentile([40, 10, 30, 20], 50) == 20
    assert nearest_rank_percentile([40, 10, 30, 20], 95) == 40
    with pytest.raises(ValueError, match="percentile"):
        nearest_rank_percentile([1], 0)


def test_sanitized_report_rejects_sensitive_field_names_recursively() -> None:
    assert_sanitized_report({"provider": "fake", "scenarios": [{"duration_ms": 1.2}]})
    with pytest.raises(ValueError, match="sensitive report field"):
        assert_sanitized_report({"scenarios": {"sample": {"raw_prompt": "hidden"}}})


def test_aggregate_scenario_keeps_counts_and_percentiles_but_not_sample_data() -> None:
    samples = [
        {
            "failure_code": None,
            "step_count": 1,
            "end_to_end_ms": duration,
            "first_pending_ms": None,
            "planner_calls": 1,
            "step_adjudicator_calls": 0,
            "narrator_calls": 1,
            "engine_submit_calls": 1,
            "engine_status_calls": 0,
            "plan_create_calls": 1,
            "plan_cas_calls": 6,
            "repair_calls": 0,
            "model_transport_retries": 0,
        }
        for duration in (10.0, 30.0, 20.0)
    ]

    summary = aggregate_scenario(samples)

    assert summary["successes"] == 3
    assert summary["failure_rate"] == 0.0
    assert summary["end_to_end_ms"]["p50"] == 20.0
    assert summary["first_narration_completion_ms"]["p95"] == 30.0
    assert summary["end_to_end_ms"]["p95"] == 30.0
    assert summary["planner_calls"]["per_sample_mean"] == 1.0
    assert summary["model_calls"]["total"] == 0
    assert summary["input_tokens"]["total"] == 0
    assert summary["deterministic_rule_first_rate"] is None
    assert "samples" not in summary
