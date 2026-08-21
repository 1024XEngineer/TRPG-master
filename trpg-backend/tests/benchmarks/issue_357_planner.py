"""Explicit real-provider semantic Planner benchmark for Issue #357.

This module is intentionally not named ``test_*.py``. It incurs provider cost
only when invoked directly with the command documented in
``docs/issue-357-validation.md``. Reports never retain prompts, player text,
model output, or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
import uuid
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import Any

import anyio
from collaboration_framework.contracts import ActionPlanPolicy, PlayerInput
from collaboration_framework.host.prompts import TURN_PLANNER_PROMPT_VERSION
from collaboration_framework.host.schemas import (
    RecentTurnContext,
    TurnPlanningContext,
    TurnPlanningReference,
    TurnPlanningView,
)
from structlog.testing import capture_logs

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import OpenAIResponsesJsonClient, PromptTurnPlanner
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.core.config import Settings, secret_value, turn_planner_retry_policy
from tests.benchmarks.issue_356_metrics import (
    assert_sanitized_report,
    latency_summary,
)
from tests.benchmarks.issue_357_corpus import CASES, PlannerCorpusCase


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _context(case: PlannerCorpusCase, *, run_number: int) -> TurnPlanningContext:
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{case.name}:{run_number}").hex[:12]
    player_input = PlayerInput(
        room_id="benchmark-room",
        player_id="benchmark-player",
        actor_id="benchmark-actor",
        client_action_id=f"i357-{suffix}",
        utterance=case.utterance,
    )
    view = TurnPlanningView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        revision="benchmark-revision-1",
        self_name="调查员",
        current_scene_name="会客室",
        visible_entities=(
            TurnPlanningReference(kind="person", name="托马斯", aliases=("Thomas",)),
            TurnPlanningReference(kind="object", name="旧书桌"),
        ),
        available_destinations=(
            TurnPlanningReference(kind="location", name="图书馆"),
            TurnPlanningReference(kind="location", name="墓地"),
        ),
        known_locations=(
            TurnPlanningReference(kind="location", name="办公室"),
            TurnPlanningReference(kind="location", name="旅馆"),
        ),
        inventory_items=(TurnPlanningReference(kind="item", name="钥匙"),),
        known_information=(TurnPlanningReference(kind="information", name="旧报纸"),),
    )
    return TurnPlanningContext(
        player_input=player_input,
        planning_view=view,
        recent_history=RecentTurnContext(
            room_id=view.room_id,
            viewer_player_id=view.player_id,
            as_of_revision=view.revision,
        ),
        policy=ActionPlanPolicy(),
    )


def _planner(settings: Settings) -> PromptTurnPlanner:
    provider = settings.turn_planner_provider
    if provider not in {"openai", "qwen", "deepseek"}:
        raise ValueError("TURN_PLANNER_PROVIDER must be openai, qwen, or deepseek")
    if (
        settings.turn_planner_api_key is None
        or settings.turn_planner_base_url is None
        or settings.turn_planner_model is None
    ):
        raise ValueError(
            "TURN_PLANNER_API_KEY, TURN_PLANNER_BASE_URL, and TURN_PLANNER_MODEL are required"
        )
    client_types = {
        "openai": OpenAIResponsesJsonClient,
        "qwen": QwenChatCompletionsJsonClient,
        "deepseek": DeepSeekChatCompletionsJsonClient,
    }
    client = client_types[provider](
        api_key=secret_value(settings.turn_planner_api_key),
        base_url=settings.turn_planner_base_url,
        model=settings.turn_planner_model,
        timeout_seconds=settings.turn_planner_timeout_seconds,
        retry_policy=turn_planner_retry_policy(settings),
    )
    return PromptTurnPlanner(client)


async def _sample(
    planner: PromptTurnPlanner,
    case: PlannerCorpusCase,
    *,
    run_number: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    with capture_logs() as logs:
        try:
            plan = await planner.generate(_context(case, run_number=run_number))
            failure_code = None
            actual_kinds = tuple(step.kind for step in plan.steps)
        except Exception as exc:  # noqa: BLE001 - benchmark must aggregate terminal failures
            failure_code = getattr(exc, "code", type(exc).__name__)
            actual_kinds = ()
    calls = [
        item
        for item in logs
        if item.get("event") in {"structured_model_call_completed", "structured_model_call_failed"}
    ]
    return {
        "case": case.name,
        "cohort": case.cohort,
        "failure_code": failure_code,
        "duration_ms": round((time.monotonic() - started_at) * 1000, 3),
        "expected_step_count": len(case.expected_kinds),
        "actual_step_count": len(actual_kinds),
        "step_count_correct": bool(actual_kinds) and len(actual_kinds) == len(case.expected_kinds),
        "kind_sequence_correct": actual_kinds == case.expected_kinds,
        "first_structure_success": failure_code is None
        and not any(item.get("event") == "turn_planner_rejected" for item in logs),
        "model_calls": len(calls),
        "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in calls),
        "output_tokens": sum(int(item.get("completion_tokens") or 0) for item in calls),
        "transport_retries": sum(
            item.get("event") == "structured_json_request_retry" for item in logs
        ),
        "structured_retries": sum(item.get("event") == "turn_planner_rejected" for item in logs),
    }


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["failure_code"] is None]
    return {
        "sample_count": len(samples),
        "success_count": len(successful),
        "terminal_failure_rate": round(1 - len(successful) / len(samples), 4),
        "failure_codes": sorted(
            {str(sample["failure_code"]) for sample in samples if sample["failure_code"]}
        ),
        "latency_ms": latency_summary(sample["duration_ms"] for sample in samples),
        "model_calls": sum(sample["model_calls"] for sample in samples),
        "input_tokens": sum(sample["input_tokens"] for sample in samples),
        "output_tokens": sum(sample["output_tokens"] for sample in samples),
        "transport_retries": sum(sample["transport_retries"] for sample in samples),
        "structured_retries": sum(sample["structured_retries"] for sample in samples),
        "first_structure_success_rate": round(
            sum(sample["first_structure_success"] for sample in samples) / len(samples), 4
        ),
        "step_count_accuracy": round(
            sum(bool(sample["step_count_correct"]) for sample in samples) / len(samples), 4
        ),
        "kind_sequence_accuracy": round(
            sum(sample["kind_sequence_correct"] for sample in samples) / len(samples), 4
        ),
    }


async def run(*, repetitions: int, output: Path) -> None:
    settings = Settings()
    planner = _planner(settings)
    samples = [
        await _sample(planner, case, run_number=run_number)
        for run_number in range(repetitions)
        for case in CASES
    ]
    by_cohort: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_cohort[sample["cohort"]].append(sample)
        by_case[sample["case"]].append(sample)

    report = {
        "issue": 357,
        "benchmark_revision": _git_revision(),
        "planner_instruction_version": TURN_PLANNER_PROMPT_VERSION,
        "machine": platform.platform(),
        "python": platform.python_version(),
        "provider": settings.turn_planner_provider,
        "model": settings.turn_planner_model,
        "configuration": {
            "timeout_seconds": settings.turn_planner_timeout_seconds,
            "max_attempts": settings.turn_planner_max_attempts,
            "retry_backoff_seconds": settings.turn_planner_retry_backoff_seconds,
            "repetitions": repetitions,
        },
        "overall": _aggregate(samples),
        "cohorts": {name: _aggregate(items) for name, items in sorted(by_cohort.items())},
        "cases": {name: _aggregate(items) for name, items in sorted(by_case.items())},
    }
    assert_sanitized_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Issue #357 sanitized Planner report: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("ISSUE_357_BENCHMARK_OUTPUT", "/tmp/issue-357-planner.json")),
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    anyio.run(partial(run, repetitions=args.repetitions, output=args.output))


if __name__ == "__main__":
    main()
