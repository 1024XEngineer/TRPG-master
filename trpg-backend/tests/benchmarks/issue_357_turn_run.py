"""Explicit semantic-producer WebSocket benchmark for Issue #357.

This file is not collected by the default test suite. It uses the configured
real Host Adjudicator/Narrator plus the independent semantic Planner at 100%,
and writes aggregate-only metrics.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from app.controller import ws as ws_controller
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.main import app
from tests.benchmarks.issue_356_metrics import aggregate_scenario, assert_sanitized_report
from tests.benchmarks.issue_356_turn_run import (
    _disable_background_summary,
    _git_revision,
    _run_sample,
)


def test_issue_357_semantic_turn_run_benchmark(
    action_plan_store_factory: Callable,
) -> None:
    repeats = int(os.getenv("ISSUE_357_TURN_BENCHMARK_REPEATS", "20"))
    if repeats < 1:
        raise ValueError("ISSUE_357_TURN_BENCHMARK_REPEATS must be >= 1")
    transport_call_budget = int(os.getenv("ISSUE_357_TRANSPORT_CALL_BUDGET", "0")) or None
    if transport_call_budget is not None and transport_call_budget < 1:
        raise ValueError("ISSUE_357_TRANSPORT_CALL_BUDGET must be >= 1")
    output_path = Path(
        os.getenv(
            "ISSUE_357_TURN_BENCHMARK_OUTPUT",
            "/tmp/issue-357-semantic-turn-benchmark.json",
        )
    )
    settings = Settings()
    if settings.host_model_provider == "fake":
        raise RuntimeError("semantic E2E benchmark requires a real HOST_MODEL_PROVIDER")
    if settings.turn_planner_provider == "fake" or settings.turn_planner_provider is None:
        raise RuntimeError("semantic E2E benchmark requires a real TURN_PLANNER_PROVIDER")
    settings = settings.model_copy(update={"turn_planner_rollout_percent": 100})

    original_application = ws_controller.action_plan_turn_application
    application = build_action_plan_turn_application(
        store=original_application._store,
        engine=original_application._engine,
        adjudication_engine=ws_controller.adjudication_engine_service,
        plan_store=action_plan_store_factory(),
        settings=settings,
        recent_history_source=original_application._recent_history_source,
        memory_source=getattr(original_application, "_memory_source", None),
    )
    ws_controller.action_plan_turn_application = application
    scenarios = ("real_observation", "real_investigation", "real_multi_step")
    sample_results: dict[str, list[dict[str, Any]]] = {name: [] for name in scenarios}
    sync_client = TestClient(app)
    try:
        with _disable_background_summary():
            sample_number = 0
            for scenario in scenarios:
                for _ in range(repeats):
                    sample_number += 1
                    sample_results[scenario].append(
                        _run_sample(
                            sync_client,
                            application,
                            scenario=scenario,
                            sample_number=sample_number,
                            real_mode=True,
                        )
                    )
                    used = sum(
                        sample["transport_calls"]
                        for samples in sample_results.values()
                        for sample in samples
                    )
                    if transport_call_budget is not None and used > transport_call_budget:
                        raise RuntimeError(
                            f"transport call budget exceeded: {used} > {transport_call_budget}"
                        )
    finally:
        ws_controller.action_plan_turn_application = original_application

    all_samples = [sample for samples in sample_results.values() for sample in samples]
    report = {
        "schema_version": 1,
        "issue": 357,
        "subject_revision": os.getenv("ISSUE_357_SUBJECT_REVISION", _git_revision()),
        "benchmark_tool_revision": _git_revision(),
        "producer": "semantic",
        "planner_provider": settings.turn_planner_provider,
        "planner_model": settings.turn_planner_model,
        "host_provider": settings.host_model_provider,
        "host_model": (
            settings.deepseek_model
            if settings.host_model_provider == "deepseek"
            else settings.qwen_model
            if settings.host_model_provider == "qwen"
            else settings.openai_model
        ),
        "runtime": {
            "machine": platform.node(),
            "python": platform.python_version(),
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "percentile_method": "nearest-rank",
        "scenario_repeats": repeats,
        "configuration": {
            "planner_timeout_seconds": settings.turn_planner_timeout_seconds,
            "planner_max_attempts": settings.turn_planner_max_attempts,
            "planner_retry_backoff_seconds": (settings.turn_planner_retry_backoff_seconds),
            "rollout_percent": 100,
            "transport_call_budget": transport_call_budget,
            "host_max_attempts": settings.model_client_max_attempts,
            "host_retry_backoff_seconds": settings.model_client_retry_backoff_seconds,
        },
        "overall": aggregate_scenario(all_samples),
        "cohorts": {
            "one_action": aggregate_scenario(
                sample_results["real_observation"] + sample_results["real_investigation"]
            ),
            "multi_target": aggregate_scenario(sample_results["real_multi_step"]),
        },
        "scenarios": {
            scenario: aggregate_scenario(samples) for scenario, samples in sample_results.items()
        },
    }
    assert_sanitized_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Issue #357 sanitized semantic turn report: {output_path}")
