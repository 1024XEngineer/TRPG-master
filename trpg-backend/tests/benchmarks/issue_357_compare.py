"""Aggregate-only go/no-go comparison for Issue #357 real-model reports."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from tests.benchmarks.issue_356_metrics import assert_sanitized_report

MAX_COMPLEX_P95_INCREASE_MS = 1500.0
MAX_COMPLEX_P95_INCREASE_RATIO = 0.25
MAX_SEMANTIC_ONE_ACTION_P95_MS = 6500.0
MAX_TERMINAL_FAILURE_RATE = 0.02
MIN_MULTI_ACCURACY = 0.95
MIN_STRUCTURED_SUCCESS_RATE = 0.99
MAX_FAST_PATH_DROP = 0.05
DEFAULT_TRANSPORT_CALL_CAP = 2500


class ReportCompatibilityError(ValueError):
    """The supplied aggregate reports cannot form one fair comparison."""


_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._:/+-]{1,160}$")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReportCompatibilityError(f"report must be an object: {path.name}")
    assert_sanitized_report(value)
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReportCompatibilityError(message)


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReportCompatibilityError(f"missing numeric aggregate: {label}")
    return float(value)


def _integer(value: object, label: str) -> int:
    number = _number(value, label)
    if not number.is_integer():
        raise ReportCompatibilityError(f"aggregate must be an integer: {label}")
    return int(number)


def _rate(value: object, label: str) -> float:
    number = _number(value, label)
    if not 0 <= number <= 1:
        raise ReportCompatibilityError(f"aggregate rate is outside [0, 1]: {label}")
    return number


def _safe_label(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_LABEL.fullmatch(value) is None:
        raise ReportCompatibilityError(f"unsafe aggregate label: {label}")
    return value


def _nested(report: dict[str, Any], *keys: str) -> Any:
    value: Any = report
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ReportCompatibilityError(f"missing aggregate: {'.'.join(keys)}")
        value = value[key]
    return value


def _count_total(report: dict[str, Any], field: str) -> int:
    value = _nested(report, "overall", field)
    if isinstance(value, dict):
        value = value.get("total")
    return _integer(value, f"overall.{field}")


def _validate_inputs(
    *,
    legacy_corpus: dict[str, Any],
    semantic_corpus: dict[str, Any],
    legacy_e2e: dict[str, Any],
    semantic_e2e: dict[str, Any],
    expected_corpus_samples: int,
    expected_e2e_samples: int,
) -> str:
    _require(legacy_corpus.get("schema_version") == 2, "legacy corpus schema mismatch")
    _require(semantic_corpus.get("schema_version") == 2, "semantic corpus schema mismatch")
    _require(legacy_e2e.get("schema_version") == 1, "legacy E2E schema mismatch")
    _require(semantic_e2e.get("schema_version") == 1, "semantic E2E schema mismatch")
    _require(legacy_corpus.get("issue") == 357, "legacy corpus is not Issue #357")
    _require(semantic_corpus.get("issue") == 357, "semantic corpus is not Issue #357")
    _require(legacy_e2e.get("issue") == 356, "legacy E2E is not Issue #356")
    _require(semantic_e2e.get("issue") == 357, "semantic E2E is not Issue #357")
    _require(legacy_corpus.get("producer") == "legacy", "legacy corpus producer mismatch")
    _require(
        semantic_corpus.get("producer") == "semantic",
        "semantic corpus producer mismatch",
    )
    _require(legacy_e2e.get("producer") == "legacy", "legacy E2E producer mismatch")
    _require(semantic_e2e.get("producer") == "hybrid", "hybrid E2E producer mismatch")
    _require(
        semantic_e2e.get("route_policy") == "eligible_input_gate_v1",
        "hybrid E2E route policy mismatch",
    )
    _require(legacy_e2e.get("mode") == "real", "legacy E2E is not in real mode")

    revisions = {
        str(report.get("subject_revision"))
        for report in (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e)
    }
    _require(None not in revisions and "None" not in revisions, "subject revision is missing")
    _require(len(revisions) == 1, "reports use different subject revisions")

    for label, value in (
        ("legacy provider", legacy_corpus.get("provider")),
        ("legacy model", legacy_corpus.get("model")),
        ("semantic provider", semantic_corpus.get("provider")),
        ("semantic model", semantic_corpus.get("model")),
    ):
        _safe_label(value, label)

    _require(
        legacy_corpus.get("provider") == legacy_e2e.get("provider")
        and legacy_corpus.get("model") == legacy_e2e.get("model"),
        "legacy corpus and E2E Host provider/model differ",
    )
    _require(
        semantic_corpus.get("provider") == semantic_e2e.get("planner_provider")
        and semantic_corpus.get("model") == semantic_e2e.get("planner_model"),
        "semantic corpus and E2E Planner provider/model differ",
    )
    _require(
        legacy_e2e.get("provider") == semantic_e2e.get("host_provider")
        and legacy_e2e.get("model") == semantic_e2e.get("host_model"),
        "legacy and semantic E2E Host provider/model differ",
    )
    runtime_signatures = {
        tuple(
            _nested(report, "runtime", field)
            for field in ("machine", "python", "os", "architecture")
        )
        for report in (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e)
    }
    _require(len(runtime_signatures) == 1, "reports use different runtime environments")

    for name, report in (
        ("legacy corpus", legacy_corpus),
        ("semantic corpus", semantic_corpus),
    ):
        count = _integer(_nested(report, "overall", "sample_count"), f"{name} sample count")
        _require(count == expected_corpus_samples, f"{name} sample count is {count}")
    for name, report in (("legacy E2E", legacy_e2e), ("semantic E2E", semantic_e2e)):
        count = _integer(_nested(report, "overall", "sample_count"), f"{name} sample count")
        _require(count == expected_e2e_samples, f"{name} sample count is {count}")

    required_scenarios = {"real_observation", "real_investigation", "real_multi_step"}
    for name, report in (("legacy E2E", legacy_e2e), ("semantic E2E", semantic_e2e)):
        scenarios = report.get("scenarios")
        if not isinstance(scenarios, dict):
            raise ReportCompatibilityError(f"{name} scenarios are missing")
        _require(required_scenarios <= scenarios.keys(), f"{name} scenarios are incomplete")
        _nested(report, "cohorts", "one_action", "end_to_end_ms", "p95")
    _nested(semantic_corpus, "cohorts", "multi", "step_count_accuracy")
    _nested(semantic_corpus, "cohorts", "multi", "kind_sequence_accuracy")
    return revisions.pop()


def _gate(observed: float, *, threshold: float, comparison: str) -> dict[str, Any]:
    passed = observed <= threshold if comparison == "max" else observed >= threshold
    return {
        "passed": passed,
        "observed": round(observed, 6),
        "threshold": threshold,
        "comparison": comparison,
    }


def compare_smoke(
    *,
    legacy_corpus: dict[str, Any],
    semantic_corpus: dict[str, Any],
    legacy_e2e: dict[str, Any],
    semantic_e2e: dict[str, Any],
    transport_call_cap: int = DEFAULT_TRANSPORT_CALL_CAP,
) -> dict[str, Any]:
    """Require a clean, compatible smoke before any formal samples run."""

    for report in (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e):
        assert_sanitized_report(report)
    revision = _validate_inputs(
        legacy_corpus=legacy_corpus,
        semantic_corpus=semantic_corpus,
        legacy_e2e=legacy_e2e,
        semantic_e2e=semantic_e2e,
        expected_corpus_samples=40,
        expected_e2e_samples=3,
    )
    _require(transport_call_cap >= 1, "transport call cap must be positive")
    reports = (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e)
    transport_calls = sum(_count_total(report, "transport_calls") for report in reports)
    failure_rates = {
        "legacy_corpus": _rate(
            _nested(legacy_corpus, "overall", "terminal_failure_rate"),
            "legacy corpus smoke failure rate",
        ),
        "semantic_corpus": _rate(
            _nested(semantic_corpus, "overall", "terminal_failure_rate"),
            "semantic corpus smoke failure rate",
        ),
        "legacy_e2e": _rate(
            _nested(legacy_e2e, "overall", "failure_rate"),
            "legacy E2E smoke failure rate",
        ),
        "semantic_e2e": _rate(
            _nested(semantic_e2e, "overall", "failure_rate"),
            "semantic E2E smoke failure rate",
        ),
    }
    gates = {
        **{
            f"{name}_clean": _gate(value, threshold=0.0, comparison="max")
            for name, value in failure_rates.items()
        },
        "transport_call_cap": _gate(
            float(transport_calls),
            threshold=float(transport_call_cap),
            comparison="max",
        ),
    }
    report = {
        "schema_version": 1,
        "issue": 357,
        "stage": "smoke",
        "subject_revision": revision,
        "verdict": "go" if all(item["passed"] for item in gates.values()) else "no-go",
        "transport_calls": transport_calls,
        "transport_call_cap": transport_call_cap,
        "failure_rates": failure_rates,
        "gates": gates,
    }
    assert_sanitized_report(report)
    return report


def compare_round(
    *,
    round_number: int,
    legacy_corpus: dict[str, Any],
    semantic_corpus: dict[str, Any],
    legacy_e2e: dict[str, Any],
    semantic_e2e: dict[str, Any],
    expected_corpus_samples: int = 200,
    expected_e2e_samples: int = 60,
    prior_transport_calls: int = 0,
    transport_call_cap: int = DEFAULT_TRANSPORT_CALL_CAP,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
) -> dict[str, Any]:
    for report in (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e):
        assert_sanitized_report(report)
    revision = _validate_inputs(
        legacy_corpus=legacy_corpus,
        semantic_corpus=semantic_corpus,
        legacy_e2e=legacy_e2e,
        semantic_e2e=semantic_e2e,
        expected_corpus_samples=expected_corpus_samples,
        expected_e2e_samples=expected_e2e_samples,
    )
    _require(round_number in {1, 2}, "round number must be 1 or 2")
    _require(prior_transport_calls >= 0, "prior transport calls cannot be negative")
    _require(transport_call_cap >= 1, "transport call cap must be positive")
    _require(
        (input_price_per_million is None) == (output_price_per_million is None),
        "verified input and output prices must be supplied together",
    )
    _require(
        input_price_per_million is None or input_price_per_million >= 0,
        "verified input price cannot be negative",
    )
    _require(
        output_price_per_million is None or output_price_per_million >= 0,
        "verified output price cannot be negative",
    )

    legacy_complex = _number(
        _nested(legacy_e2e, "scenarios", "real_investigation", "end_to_end_ms", "p95"),
        "legacy complex P95",
    )
    semantic_complex = _number(
        _nested(semantic_e2e, "scenarios", "real_investigation", "end_to_end_ms", "p95"),
        "semantic complex P95",
    )
    _require(legacy_complex > 0, "legacy complex P95 must be positive")
    complex_increase_ms = semantic_complex - legacy_complex
    complex_increase_ratio = complex_increase_ms / legacy_complex
    semantic_one_p95 = _number(
        _nested(semantic_e2e, "cohorts", "one_action", "end_to_end_ms", "p95"),
        "semantic one-action P95",
    )
    planner_failure_rate = _rate(
        _nested(semantic_corpus, "overall", "terminal_failure_rate"),
        "Planner failure rate",
    )
    semantic_e2e_failure_rate = _rate(
        _nested(semantic_e2e, "overall", "failure_rate"),
        "semantic E2E failure rate",
    )
    multi_step_accuracy = _rate(
        _nested(semantic_corpus, "cohorts", "multi", "step_count_accuracy"),
        "multi step-count accuracy",
    )
    multi_kind_accuracy = _rate(
        _nested(semantic_corpus, "cohorts", "multi", "kind_sequence_accuracy"),
        "multi kind-sequence accuracy",
    )
    structured_success = _rate(
        _nested(semantic_corpus, "overall", "structured_success_rate"),
        "structured success rate",
    )
    # The legacy producer freezes its first adjudication inside the producer,
    # while semantic runs every current step through the Step Adjudicator. Use
    # only the shared post-first-step cohort for the hard gate; retain the old
    # all-step rates as diagnostics for historical reports.
    legacy_comparable_value = _nested(
        legacy_e2e,
        "overall",
        "comparable_deterministic_rule_first_rate",
    )
    semantic_comparable_value = _nested(
        semantic_e2e,
        "overall",
        "comparable_deterministic_rule_first_rate",
    )
    legacy_fast_value = _nested(legacy_e2e, "overall", "deterministic_rule_first_rate")
    semantic_fast_value = _nested(semantic_e2e, "overall", "deterministic_rule_first_rate")
    comparable_metrics_available = (
        legacy_comparable_value is not None and semantic_comparable_value is not None
    )
    if comparable_metrics_available:
        legacy_fast_value = legacy_comparable_value
        semantic_fast_value = semantic_comparable_value
    legacy_fast_rate = (
        0.0 if legacy_fast_value is None else _rate(legacy_fast_value, "legacy fast rate")
    )
    semantic_fast_rate = (
        0.0 if semantic_fast_value is None else _rate(semantic_fast_value, "semantic fast rate")
    )
    fast_path_drop = legacy_fast_rate - semantic_fast_rate

    reports = (legacy_corpus, semantic_corpus, legacy_e2e, semantic_e2e)
    round_transport_calls = sum(_count_total(report, "transport_calls") for report in reports)
    cumulative_transport_calls = prior_transport_calls + round_transport_calls
    gates = {
        "complex_p95_absolute_increase": _gate(
            complex_increase_ms,
            threshold=MAX_COMPLEX_P95_INCREASE_MS,
            comparison="max",
        ),
        "complex_p95_relative_increase": _gate(
            complex_increase_ratio,
            threshold=MAX_COMPLEX_P95_INCREASE_RATIO,
            comparison="max",
        ),
        "semantic_one_action_p95": _gate(
            semantic_one_p95,
            threshold=MAX_SEMANTIC_ONE_ACTION_P95_MS,
            comparison="max",
        ),
        "planner_terminal_failure_rate": _gate(
            planner_failure_rate,
            threshold=MAX_TERMINAL_FAILURE_RATE,
            comparison="max",
        ),
        "semantic_e2e_terminal_failure_rate": _gate(
            semantic_e2e_failure_rate,
            threshold=MAX_TERMINAL_FAILURE_RATE,
            comparison="max",
        ),
        "multi_step_count_accuracy": _gate(
            multi_step_accuracy,
            threshold=MIN_MULTI_ACCURACY,
            comparison="min",
        ),
        "multi_kind_sequence_accuracy": _gate(
            multi_kind_accuracy,
            threshold=MIN_MULTI_ACCURACY,
            comparison="min",
        ),
        "structured_success_after_retry": _gate(
            structured_success,
            threshold=MIN_STRUCTURED_SUCCESS_RATE,
            comparison="min",
        ),
        "deterministic_rule_first_drop": _gate(
            fast_path_drop,
            threshold=MAX_FAST_PATH_DROP,
            comparison="max",
        ),
        "transport_call_cap": _gate(
            float(cumulative_transport_calls),
            threshold=float(transport_call_cap),
            comparison="max",
        ),
    }

    totals = {
        "model_calls": sum(_count_total(report, "model_calls") for report in reports),
        "transport_calls": round_transport_calls,
        "cumulative_transport_calls": cumulative_transport_calls,
        "input_tokens": sum(_count_total(report, "input_tokens") for report in reports),
        "output_tokens": sum(_count_total(report, "output_tokens") for report in reports),
        "transport_retries": sum(
            _count_total(report, "transport_retries")
            if "transport_retries" in report["overall"]
            else _count_total(report, "model_transport_retries")
            for report in reports
        ),
        "structured_retries": sum(_count_total(report, "structured_retries") for report in reports),
    }
    if input_price_per_million is None:
        cost = {"availability": "unavailable", "estimated_total": None}
    else:
        assert output_price_per_million is not None
        estimated = (
            totals["input_tokens"] * input_price_per_million
            + totals["output_tokens"] * output_price_per_million
        ) / 1_000_000
        cost = {"availability": "verified_prices_supplied", "estimated_total": round(estimated, 6)}

    report = {
        "schema_version": 1,
        "issue": 357,
        "round": round_number,
        "subject_revision": revision,
        "verdict": "go" if all(item["passed"] for item in gates.values()) else "no-go",
        "providers": {
            "legacy": {"provider": legacy_corpus["provider"], "model": legacy_corpus["model"]},
            "semantic": {
                "provider": semantic_corpus["provider"],
                "model": semantic_corpus["model"],
            },
        },
        "latency_ms": {
            "legacy_complex_p95": legacy_complex,
            "semantic_complex_p95": semantic_complex,
            "complex_absolute_increase": round(complex_increase_ms, 3),
            "complex_relative_increase": round(complex_increase_ratio, 6),
            "semantic_one_action": _nested(semantic_e2e, "cohorts", "one_action", "end_to_end_ms"),
            "legacy_overall": _nested(legacy_e2e, "overall", "end_to_end_ms"),
            "semantic_overall": _nested(semantic_e2e, "overall", "end_to_end_ms"),
        },
        "quality": {
            "planner_terminal_failure_rate": planner_failure_rate,
            "semantic_e2e_terminal_failure_rate": semantic_e2e_failure_rate,
            "first_structure_success_rate": _nested(
                semantic_corpus, "overall", "first_structure_success_rate"
            ),
            "structured_success_rate": structured_success,
            "multi_step_count_accuracy": multi_step_accuracy,
            "multi_kind_sequence_accuracy": multi_kind_accuracy,
            "legacy_deterministic_rule_first_rate": legacy_fast_rate,
            "semantic_deterministic_rule_first_rate": semantic_fast_rate,
            "legacy_all_step_deterministic_rule_first_rate": (
                0.0
                if _nested(legacy_e2e, "overall", "deterministic_rule_first_rate") is None
                else _rate(
                    _nested(legacy_e2e, "overall", "deterministic_rule_first_rate"),
                    "legacy all-step fast rate",
                )
            ),
            "semantic_all_step_deterministic_rule_first_rate": (
                0.0
                if _nested(semantic_e2e, "overall", "deterministic_rule_first_rate") is None
                else _rate(
                    _nested(semantic_e2e, "overall", "deterministic_rule_first_rate"),
                    "semantic all-step fast rate",
                )
            ),
            "comparable_fast_path_metrics_available": comparable_metrics_available,
            "deterministic_rule_first_drop": round(fast_path_drop, 6),
        },
        "scenario_step_counts": {
            "legacy": {
                name: value["step_counts"] for name, value in legacy_e2e["scenarios"].items()
            },
            "semantic": {
                name: value["step_counts"] for name, value in semantic_e2e["scenarios"].items()
            },
        },
        "scenario_step_count_distributions": {
            "legacy": {
                name: value.get("step_count_distribution", {})
                for name, value in legacy_e2e["scenarios"].items()
            },
            "semantic": {
                name: value.get("step_count_distribution", {})
                for name, value in semantic_e2e["scenarios"].items()
            },
        },
        "scenario_adjudicator_paths": {
            "legacy": {
                name: value.get("step_adjudicator_paths", {})
                for name, value in legacy_e2e["scenarios"].items()
            },
            "semantic": {
                name: value.get("step_adjudicator_paths", {})
                for name, value in semantic_e2e["scenarios"].items()
            },
        },
        "totals": totals,
        "cost": cost,
        "gates": gates,
    }
    assert_sanitized_report(report)
    return report


def summarize_rounds(
    round_1: dict[str, Any],
    round_2: dict[str, Any],
    *,
    transport_call_cap: int = DEFAULT_TRANSPORT_CALL_CAP,
) -> dict[str, Any]:
    assert_sanitized_report(round_1)
    assert_sanitized_report(round_2)
    _require(round_1.get("round") == 1, "first comparison is not Round 1")
    _require(round_2.get("round") == 2, "second comparison is not Round 2")
    _require(
        round_1.get("subject_revision") == round_2.get("subject_revision"),
        "rounds use different subject revisions",
    )
    round_1_cumulative = _integer(
        _nested(round_1, "totals", "cumulative_transport_calls"),
        "Round 1 cumulative transport calls",
    )
    round_2_calls = _integer(
        _nested(round_2, "totals", "transport_calls"), "Round 2 transport calls"
    )
    total_calls = _integer(
        _nested(round_2, "totals", "cumulative_transport_calls"),
        "Round 2 cumulative transport calls",
    )
    _require(
        total_calls == round_1_cumulative + round_2_calls,
        "Round 2 cumulative transport count is inconsistent",
    )
    rounds_passed = round_1.get("verdict") == "go" and round_2.get("verdict") == "go"
    budget_passed = total_calls <= transport_call_cap
    report = {
        "schema_version": 1,
        "issue": 357,
        "subject_revision": round_1["subject_revision"],
        "verdict": "go" if rounds_passed and budget_passed else "no-go",
        "rounds": [
            {"round": 1, "verdict": round_1.get("verdict")},
            {"round": 2, "verdict": round_2.get("verdict")},
        ],
        "transport_calls": total_calls,
        "transport_call_cap": transport_call_cap,
        "transport_call_cap_passed": budget_passed,
        "independent_rounds_passed": rounds_passed,
        "risk_note": "连续测试不覆盖长时间生产流量波动。",
    }
    assert_sanitized_report(report)
    return report


def render_round_markdown(report: dict[str, Any]) -> str:
    assert_sanitized_report(report)
    semantic_step_distributions = report["scenario_step_count_distributions"]["semantic"]
    semantic_adjudicator_paths = report["scenario_adjudicator_paths"]["semantic"]
    rows = [
        "| Gate | Observed | Threshold | Result |",
        "| --- | ---: | ---: | :---: |",
    ]
    for name, gate in report["gates"].items():
        comparator = "<=" if gate["comparison"] == "max" else ">="
        rows.append(
            f"| `{name}` | {gate['observed']} | {comparator} {gate['threshold']} | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    return "\n".join(
        [
            f"# Issue #357 Real-model Round {report['round']}",
            "",
            f"- Revision: `{report['subject_revision']}`",
            f"- Verdict: **{report['verdict'].upper()}**",
            f"- Model calls: {report['totals']['model_calls']}",
            f"- Transport calls: {report['totals']['transport_calls']}",
            f"- Input/output tokens: {report['totals']['input_tokens']} / "
            f"{report['totals']['output_tokens']}",
            f"- Semantic step-count distributions: `{semantic_step_distributions}`",
            f"- Semantic adjudicator paths: `{semantic_adjudicator_paths}`",
            "",
            *rows,
            "",
        ]
    )


def render_smoke_markdown(report: dict[str, Any]) -> str:
    assert_sanitized_report(report)
    rows = [
        "| Smoke path | Failure rate | Result |",
        "| --- | ---: | :---: |",
    ]
    for name, rate in report["failure_rates"].items():
        rows.append(f"| `{name}` | {rate} | {'PASS' if rate == 0 else 'FAIL'} |")
    return "\n".join(
        [
            "# Issue #357 Real-model Smoke",
            "",
            f"- Revision: `{report['subject_revision']}`",
            f"- Verdict: **{report['verdict'].upper()}**",
            f"- Transport calls: {report['transport_calls']} / {report['transport_call_cap']}",
            "",
            *rows,
            "",
        ]
    )


def render_summary_markdown(report: dict[str, Any]) -> str:
    assert_sanitized_report(report)
    round_lines = [
        f"| {item['round']} | {str(item['verdict']).upper()} |" for item in report["rounds"]
    ]
    return "\n".join(
        [
            "# Issue #357 PR1/PR2 连续真实模型验证",
            "",
            f"- Revision: `{report['subject_revision']}`",
            f"- Final verdict: **{report['verdict'].upper()}**",
            f"- Transport calls: {report['transport_calls']} / {report['transport_call_cap']}",
            "- Observation: 连续两轮，无人为等待；不覆盖长时间生产流量波动。",
            "",
            "| Round | Verdict |",
            "| ---: | :---: |",
            *round_lines,
            "",
        ]
    )


def _write(
    report: dict[str, Any], *, json_output: Path, markdown_output: Path, markdown: str
) -> None:
    assert_sanitized_report(report)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(markdown, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    smoke_parser = commands.add_parser("smoke")
    smoke_parser.add_argument("--legacy-corpus", type=Path, required=True)
    smoke_parser.add_argument("--semantic-corpus", type=Path, required=True)
    smoke_parser.add_argument("--legacy-e2e", type=Path, required=True)
    smoke_parser.add_argument("--semantic-e2e", type=Path, required=True)
    smoke_parser.add_argument("--json-output", type=Path, required=True)
    smoke_parser.add_argument("--markdown-output", type=Path, required=True)
    smoke_parser.add_argument("--transport-call-cap", type=int, default=DEFAULT_TRANSPORT_CALL_CAP)
    round_parser = commands.add_parser("round")
    round_parser.add_argument("--round", type=int, choices=(1, 2), required=True)
    round_parser.add_argument("--legacy-corpus", type=Path, required=True)
    round_parser.add_argument("--semantic-corpus", type=Path, required=True)
    round_parser.add_argument("--legacy-e2e", type=Path, required=True)
    round_parser.add_argument("--semantic-e2e", type=Path, required=True)
    round_parser.add_argument("--json-output", type=Path, required=True)
    round_parser.add_argument("--markdown-output", type=Path, required=True)
    round_parser.add_argument("--expected-corpus-samples", type=int, default=200)
    round_parser.add_argument("--expected-e2e-samples", type=int, default=60)
    round_parser.add_argument("--prior-transport-calls", type=int, default=0)
    round_parser.add_argument("--transport-call-cap", type=int, default=DEFAULT_TRANSPORT_CALL_CAP)
    round_parser.add_argument("--input-price-per-million", type=float)
    round_parser.add_argument("--output-price-per-million", type=float)

    summary_parser = commands.add_parser("summary")
    summary_parser.add_argument("--round-1", type=Path, required=True)
    summary_parser.add_argument("--round-2", type=Path, required=True)
    summary_parser.add_argument("--json-output", type=Path, required=True)
    summary_parser.add_argument("--markdown-output", type=Path, required=True)
    summary_parser.add_argument(
        "--transport-call-cap", type=int, default=DEFAULT_TRANSPORT_CALL_CAP
    )
    args = parser.parse_args()

    if args.command == "smoke":
        report = compare_smoke(
            legacy_corpus=_load(args.legacy_corpus),
            semantic_corpus=_load(args.semantic_corpus),
            legacy_e2e=_load(args.legacy_e2e),
            semantic_e2e=_load(args.semantic_e2e),
            transport_call_cap=args.transport_call_cap,
        )
        markdown = render_smoke_markdown(report)
    elif args.command == "round":
        report = compare_round(
            round_number=args.round,
            legacy_corpus=_load(args.legacy_corpus),
            semantic_corpus=_load(args.semantic_corpus),
            legacy_e2e=_load(args.legacy_e2e),
            semantic_e2e=_load(args.semantic_e2e),
            expected_corpus_samples=args.expected_corpus_samples,
            expected_e2e_samples=args.expected_e2e_samples,
            prior_transport_calls=args.prior_transport_calls,
            transport_call_cap=args.transport_call_cap,
            input_price_per_million=args.input_price_per_million,
            output_price_per_million=args.output_price_per_million,
        )
        markdown = render_round_markdown(report)
    else:
        report = summarize_rounds(
            _load(args.round_1),
            _load(args.round_2),
            transport_call_cap=args.transport_call_cap,
        )
        markdown = render_summary_markdown(report)
    _write(
        report,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
        markdown=markdown,
    )
    raise SystemExit(0 if report["verdict"] == "go" else 1)


if __name__ == "__main__":
    main()
