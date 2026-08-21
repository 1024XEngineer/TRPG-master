"""Sanitized metrics helpers for the Issue #356 TurnRun validation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

SENSITIVE_FIELD_FRAGMENTS = frozenset(
    {
        "api_key",
        "api_token",
        "access_token",
        "capabilit",
        "context",
        "message_text",
        "model_output",
        "narration_text",
        "player_input",
        "prompt",
        "raw",
        "secret",
        "utterance",
    }
)


def nearest_rank_percentile(values: Iterable[float], percentile: float) -> float | None:
    """Return the nearest-rank percentile, rounded to three decimal places."""

    samples = sorted(float(value) for value in values)
    if not samples:
        return None
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    rank = max(1, math.ceil(percentile / 100 * len(samples)))
    return round(samples[rank - 1], 3)


def latency_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    samples = [round(float(value), 3) for value in values]
    return {
        "samples": len(samples),
        "min": min(samples) if samples else None,
        "p50": nearest_rank_percentile(samples, 50),
        "p95": nearest_rank_percentile(samples, 95),
        "p99": nearest_rank_percentile(samples, 99),
        "max": max(samples) if samples else None,
    }


def count_summary(values: Iterable[int]) -> dict[str, float | int | None]:
    samples = [int(value) for value in values]
    return {
        "total": sum(samples),
        "per_sample_min": min(samples) if samples else None,
        "per_sample_mean": round(sum(samples) / len(samples), 3) if samples else None,
        "per_sample_max": max(samples) if samples else None,
    }


def assert_sanitized_report(value: object, *, path: str = "report") -> None:
    """Reject fields that could expose player/model input or credentials."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS):
                raise ValueError(f"sensitive report field at {path}.{key}")
            assert_sanitized_report(nested, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            assert_sanitized_report(nested, path=f"{path}[{index}]")
        return
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError(f"unsupported report value at {path}: {type(value).__name__}")


def aggregate_scenario(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate already-sanitized samples without retaining per-turn identifiers."""

    count_fields = (
        "model_calls",
        "transport_calls",
        "planner_calls",
        "step_adjudicator_calls",
        "narrator_calls",
        "engine_submit_calls",
        "engine_status_calls",
        "plan_create_calls",
        "plan_cas_calls",
        "repair_calls",
        "model_transport_retries",
        "structured_retries",
        "input_tokens",
        "output_tokens",
        "deterministic_hits",
        "rule_first_hits",
    )
    result: dict[str, Any] = {
        "sample_count": len(samples),
        "successes": sum(sample["failure_code"] is None for sample in samples),
        "failures": sum(sample["failure_code"] is not None for sample in samples),
        "failure_rate": (
            round(
                sum(sample["failure_code"] is not None for sample in samples) / len(samples),
                4,
            )
            if samples
            else None
        ),
        "failure_codes": sorted(
            {
                str(sample["failure_code"])
                for sample in samples
                if sample["failure_code"] is not None
            }
        ),
        "step_counts": sorted({int(sample["step_count"]) for sample in samples}),
        "end_to_end_ms": latency_summary(
            sample["end_to_end_ms"] for sample in samples if sample["end_to_end_ms"] is not None
        ),
        "first_narration_completion_ms": latency_summary(
            sample.get("first_narration_ms", sample["end_to_end_ms"])
            for sample in samples
            if sample["failure_code"] is None and sample["end_to_end_ms"] is not None
        ),
        "final_narration_completion_ms": latency_summary(
            sample.get("final_narration_ms", sample["end_to_end_ms"])
            for sample in samples
            if sample["failure_code"] is None and sample["end_to_end_ms"] is not None
        ),
        "first_pending_ms": latency_summary(
            sample["first_pending_ms"]
            for sample in samples
            if sample["first_pending_ms"] is not None
        ),
    }
    for field in count_fields:
        result[field] = count_summary(sample.get(field, 0) for sample in samples)
    adjudicated = sum(sample.get("step_adjudicator_calls", 0) for sample in samples)
    fast_path = sum(
        sample.get("deterministic_hits", 0) + sample.get("rule_first_hits", 0) for sample in samples
    )
    result["deterministic_rule_first_rate"] = (
        round(fast_path / adjudicated, 4) if adjudicated else None
    )
    assert_sanitized_report(result)
    return result
