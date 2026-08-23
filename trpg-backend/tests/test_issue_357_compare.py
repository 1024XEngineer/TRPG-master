from __future__ import annotations

from copy import deepcopy

import pytest

from tests.benchmarks.issue_357_compare import (
    ReportCompatibilityError,
    compare_round,
    compare_smoke,
    render_round_markdown,
    summarize_rounds,
)


def _counts(total: int) -> dict[str, int | float | None]:
    return {
        "total": total,
        "per_sample_min": 0,
        "per_sample_mean": round(total / 60, 3),
        "per_sample_max": total,
    }


def _corpus(producer: str) -> dict:
    return {
        "schema_version": 2,
        "issue": 357,
        "subject_revision": "revision-357",
        "benchmark_tool_revision": "tool-revision",
        "producer": producer,
        "runtime": {
            "machine": "benchmark-machine",
            "python": "3.13.0",
            "os": "Darwin",
            "architecture": "arm64",
        },
        "provider": "deepseek",
        "model": "legacy-model" if producer == "legacy" else "semantic-model",
        "overall": {
            "sample_count": 200,
            "terminal_failure_rate": 0.0,
            "first_structure_success_rate": 1.0,
            "structured_success_rate": 1.0,
            "model_calls": 200,
            "transport_calls": 200,
            "input_tokens": 2000,
            "output_tokens": 1000,
            "transport_retries": 0,
            "structured_retries": 0,
        },
        "cohorts": {
            "multi": {
                "step_count_accuracy": 1.0,
                "kind_sequence_accuracy": 1.0,
            }
        },
    }


def _scenario(p95: float, *, steps: list[int]) -> dict:
    return {
        "sample_count": 20,
        "failure_rate": 0.0,
        "step_counts": steps,
        "end_to_end_ms": {"samples": 20, "p50": p95 - 500, "p95": p95, "p99": p95},
    }


def _e2e(producer: str) -> dict:
    legacy = producer == "legacy"
    return {
        "schema_version": 1,
        "issue": 356 if legacy else 357,
        "subject_revision": "revision-357",
        "benchmark_tool_revision": "tool-revision",
        "producer": producer,
        "mode": "real" if legacy else None,
        "runtime": {
            "machine": "benchmark-machine",
            "python": "3.13.0",
            "os": "Darwin",
            "architecture": "arm64",
        },
        **(
            {"provider": "deepseek", "model": "legacy-model"}
            if legacy
            else {
                "planner_provider": "deepseek",
                "planner_model": "semantic-model",
                "host_provider": "deepseek",
                "host_model": "legacy-model",
            }
        ),
        "overall": {
            "sample_count": 60,
            "failure_rate": 0.0,
            "end_to_end_ms": {
                "samples": 60,
                "p50": 4000.0,
                "p95": 5500.0,
                "p99": 6000.0,
            },
            "deterministic_rule_first_rate": 0.5,
            "model_calls": _counts(120),
            "transport_calls": _counts(120),
            "input_tokens": _counts(1200),
            "output_tokens": _counts(600),
            "model_transport_retries": _counts(0),
            "structured_retries": _counts(0),
            "comparable_deterministic_rule_first_rate": 0.5,
        },
        "cohorts": {
            "one_action": {
                "end_to_end_ms": {
                    "samples": 40,
                    "p50": 4000.0,
                    "p95": 6000.0,
                    "p99": 6200.0,
                }
            }
        },
        "scenarios": {
            "real_observation": _scenario(4500.0, steps=[1]),
            "real_investigation": _scenario(5000.0 if legacy else 6000.0, steps=[1]),
            "real_multi_step": _scenario(6000.0, steps=[2]),
        },
    }


def _inputs() -> dict:
    return {
        "legacy_corpus": _corpus("legacy"),
        "semantic_corpus": _corpus("semantic"),
        "legacy_e2e": _e2e("legacy"),
        "semantic_e2e": _e2e("semantic"),
    }


def test_compare_round_passes_every_gate_and_keeps_aggregate_only_output() -> None:
    report = compare_round(round_number=1, **_inputs())

    assert report["verdict"] == "go"
    assert all(gate["passed"] for gate in report["gates"].values())
    assert report["cost"] == {"availability": "unavailable", "estimated_total": None}
    assert "cases" not in report


def test_compare_smoke_requires_all_four_paths_to_be_clean() -> None:
    reports = _inputs()
    for report in reports.values():
        report["overall"]["sample_count"] = (
            40
            if report["producer"] in {"legacy", "semantic"}
            and "cohorts" in report
            and "multi" in report["cohorts"]
            else 3
        )

    passed = compare_smoke(**reports)
    reports["semantic_corpus"]["overall"]["terminal_failure_rate"] = 0.025
    failed = compare_smoke(**reports)

    assert passed["verdict"] == "go"
    assert failed["verdict"] == "no-go"
    assert failed["gates"]["semantic_corpus_clean"]["passed"] is False


@pytest.mark.parametrize(
    ("gate", "mutate"),
    [
        (
            "complex_p95_absolute_increase",
            lambda reports: (
                reports["legacy_e2e"]["scenarios"]["real_investigation"]["end_to_end_ms"].update(
                    p95=7000.0
                )
                or reports["semantic_e2e"]["scenarios"]["real_investigation"][
                    "end_to_end_ms"
                ].update(p95=8501.0)
            ),
        ),
        (
            "complex_p95_relative_increase",
            lambda reports: (
                reports["legacy_e2e"]["scenarios"]["real_investigation"]["end_to_end_ms"].update(
                    p95=1000.0
                )
                or reports["semantic_e2e"]["scenarios"]["real_investigation"][
                    "end_to_end_ms"
                ].update(p95=1300.0)
            ),
        ),
        (
            "semantic_one_action_p95",
            lambda reports: reports["semantic_e2e"]["cohorts"]["one_action"][
                "end_to_end_ms"
            ].update(p95=6501.0),
        ),
        (
            "planner_terminal_failure_rate",
            lambda reports: reports["semantic_corpus"]["overall"].update(
                terminal_failure_rate=0.021
            ),
        ),
        (
            "semantic_e2e_terminal_failure_rate",
            lambda reports: reports["semantic_e2e"]["overall"].update(failure_rate=0.021),
        ),
        (
            "multi_step_count_accuracy",
            lambda reports: reports["semantic_corpus"]["cohorts"]["multi"].update(
                step_count_accuracy=0.949
            ),
        ),
        (
            "multi_kind_sequence_accuracy",
            lambda reports: reports["semantic_corpus"]["cohorts"]["multi"].update(
                kind_sequence_accuracy=0.949
            ),
        ),
        (
            "structured_success_after_retry",
            lambda reports: reports["semantic_corpus"]["overall"].update(
                structured_success_rate=0.989
            ),
        ),
        (
            "deterministic_rule_first_drop",
            lambda reports: reports["semantic_e2e"]["overall"].update(
                comparable_deterministic_rule_first_rate=0.449
            ),
        ),
        (
            "transport_call_cap",
            lambda reports: reports["semantic_e2e"]["overall"]["transport_calls"].update(
                total=2501
            ),
        ),
    ],
)
def test_compare_round_fails_each_hard_gate_independently(gate: str, mutate) -> None:  # noqa: ANN001
    reports = _inputs()
    mutate(reports)

    result = compare_round(round_number=1, **reports)

    assert result["verdict"] == "no-go"
    assert result["gates"][gate]["passed"] is False


def test_summary_requires_both_rounds_independently() -> None:
    round_1 = compare_round(round_number=1, **_inputs())
    failed_inputs = _inputs()
    failed_inputs["semantic_corpus"]["overall"]["terminal_failure_rate"] = 0.03
    round_2 = compare_round(
        round_number=2,
        prior_transport_calls=round_1["totals"]["cumulative_transport_calls"],
        **failed_inputs,
    )

    summary = summarize_rounds(round_1, round_2)

    assert summary["verdict"] == "no-go"
    assert summary["independent_rounds_passed"] is False


def test_compare_rejects_missing_incompatible_and_sensitive_reports() -> None:
    reports = _inputs()
    reports["semantic_e2e"]["subject_revision"] = "different"
    with pytest.raises(ReportCompatibilityError, match="different subject revisions"):
        compare_round(round_number=1, **reports)

    reports = _inputs()
    reports["semantic_corpus"]["schema_version"] = 99
    with pytest.raises(ReportCompatibilityError, match="schema mismatch"):
        compare_round(round_number=1, **reports)

    reports = _inputs()
    del reports["semantic_e2e"]["cohorts"]
    with pytest.raises(ReportCompatibilityError, match="missing aggregate"):
        compare_round(round_number=1, **reports)

    reports = _inputs()
    reports["semantic_corpus"]["raw_model_output"] = "must never survive"
    with pytest.raises(ValueError, match="sensitive report field"):
        compare_round(round_number=1, **reports)

    reports = _inputs()
    reports["semantic_corpus"]["model"] = "unsafe\nmodel output"
    with pytest.raises(ReportCompatibilityError, match="unsafe aggregate label"):
        compare_round(round_number=1, **reports)


def test_markdown_renders_only_allowlisted_aggregates() -> None:
    report = compare_round(round_number=1, **deepcopy(_inputs()))

    markdown = render_round_markdown(report)

    assert "revision-357" in markdown
    assert "must never survive" not in markdown
    assert "player utterance" not in markdown.lower()
    assert "keeper" not in markdown.lower()
