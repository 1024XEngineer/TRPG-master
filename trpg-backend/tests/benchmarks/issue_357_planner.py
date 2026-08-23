"""Explicit real-provider legacy/semantic Planner benchmark for Issue #357.

This module is intentionally not named ``test_*.py``. It incurs provider cost
only when invoked directly. Reports contain aggregate measurements only: no
prompt, player text, model output, Keeper payload, credentials, or sample IDs.
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
from typing import Any, Literal

import anyio
from collaboration_framework.contracts import (
    ActionPlan,
    ActionPlanPolicy,
    AvailableExitView,
    ExitDestinationView,
    HostTurnDecision,
    InventoryItemView,
    KeeperCapabilityView,
    KeeperEntityCapability,
    KeeperLocationCapability,
    KnownInformationView,
    KnownLocationView,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    SingleActionDecision,
    VisibleEntity,
)
from collaboration_framework.host.prompts import TURN_PLANNER_PROMPT_VERSION
from collaboration_framework.host.schemas import (
    HostAgentContext,
    RecentTurnContext,
    TurnPlanningContext,
    TurnPlanningView,
)
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import (
    OpenAIResponsesJsonClient,
    PromptHostTurnDecisionModel,
    PromptTurnPlanner,
)
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.core.config import (
    Settings,
    model_client_retry_policy,
    secret_value,
    turn_planner_retry_policy,
)
from tests.benchmarks.issue_356_metrics import assert_sanitized_report, latency_summary
from tests.benchmarks.issue_357_corpus import CASES, PlannerCorpusCase

Producer = Literal["legacy", "semantic"]


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _benchmark_view(*, player_input: PlayerInput) -> PlayerView:
    return PlayerView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        background="1920 年代，一名调查员正在一座安静小镇调查公开线索。",
        scene_id="drawing-room",
        phase="playing",
        revision="benchmark-revision-1",
        self_actor=SelfActorView(id=player_input.actor_id, name="调查员"),
        scene=SceneView(
            id="drawing-room",
            name="会客室",
            description="一间用于安全基准测试的普通会客室。",
            visible_entities=(
                VisibleEntity(
                    id="thomas",
                    kind="npc",
                    name="托马斯",
                    aliases=("Thomas",),
                    description="一名正在会客室中的普通居民。",
                ),
                VisibleEntity(
                    id="old-desk",
                    kind="object",
                    name="旧书桌",
                    description="一张普通旧书桌。",
                ),
            ),
            available_exits=(
                AvailableExitView(
                    id="exit-library",
                    name="通往图书馆的道路",
                    destination=ExitDestinationView(scene_id="library", name="图书馆"),
                ),
                AvailableExitView(
                    id="exit-cemetery",
                    name="通往墓地的道路",
                    destination=ExitDestinationView(scene_id="cemetery", name="墓地"),
                ),
            ),
        ),
        known_locations=(
            KnownLocationView(
                id="office",
                kind="room",
                name="办公室",
                existence="known",
                localization="located",
                access="reachable",
            ),
            KnownLocationView(
                id="inn",
                kind="site",
                name="旅馆",
                existence="known",
                localization="located",
                access="reachable",
            ),
        ),
        inventory=(
            InventoryItemView(
                id="key",
                name="钥匙",
                quantity=1,
                condition="完好",
                version=1,
            ),
        ),
        known_information=(
            KnownInformationView(
                id="old-newspaper",
                title="旧报纸",
                summary="一份已经公开的旧报纸。",
                content="报纸内容仅包含用于基准测试的公开信息。",
                scope="actor",
            ),
        ),
    )


def _contexts(
    case: PlannerCorpusCase,
    *,
    run_number: int,
) -> tuple[HostAgentContext, TurnPlanningContext]:
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{case.name}:{run_number}").hex[:12]
    player_input = PlayerInput(
        room_id="benchmark-room",
        player_id="benchmark-player",
        actor_id="benchmark-actor",
        client_action_id=f"i357-{suffix}",
        utterance=case.utterance,
    )
    player_view = _benchmark_view(player_input=player_input)
    recent_history = RecentTurnContext.empty(
        player_input=player_input,
        player_view=player_view,
    )
    capabilities = KeeperCapabilityView(
        room_id=player_input.room_id,
        actor_id=player_input.actor_id,
        revision=player_view.revision,
        locations=(
            KeeperLocationCapability(
                id="drawing-room", name="会客室", origin="canon", is_current=True
            ),
            KeeperLocationCapability(id="library", name="图书馆", origin="canon"),
            KeeperLocationCapability(id="cemetery", name="墓地", origin="canon"),
            KeeperLocationCapability(id="office", name="办公室", origin="canon"),
            KeeperLocationCapability(id="inn", name="旅馆", origin="runtime"),
        ),
        entities=(
            KeeperEntityCapability(
                id="thomas",
                name="托马斯",
                kind="npc",
                origin="canon",
                location_id="drawing-room",
            ),
            KeeperEntityCapability(
                id="old-desk",
                name="旧书桌",
                kind="object",
                origin="canon",
                location_id="drawing-room",
            ),
        ),
    )
    return (
        HostAgentContext(
            player_input=player_input,
            player_view=player_view,
            recent_history=recent_history,
            keeper_capabilities=capabilities,
        ),
        TurnPlanningContext(
            player_input=player_input,
            planning_view=TurnPlanningView.from_player_view(player_view),
            recent_history=recent_history,
            policy=ActionPlanPolicy(),
        ),
    )


def _host_provider(settings: Settings) -> tuple[str, str, str, SecretStr, float]:
    provider = settings.host_model_provider
    if provider == "deepseek":
        values = (
            settings.deepseek_model,
            settings.deepseek_base_url,
            settings.deepseek_api_key,
            settings.deepseek_timeout_seconds,
        )
    elif provider == "qwen":
        values = (
            settings.qwen_model,
            settings.qwen_base_url,
            settings.qwen_api_key,
            settings.qwen_timeout_seconds,
        )
    elif provider == "openai":
        values = (
            settings.openai_model,
            settings.openai_base_url,
            settings.openai_api_key,
            settings.openai_timeout_seconds,
        )
    else:
        raise ValueError("HOST_MODEL_PROVIDER must be openai, qwen, or deepseek")
    model, base_url, api_key, timeout = values
    if api_key is None:
        raise ValueError(f"{provider} Host API key is required")
    return provider, model, base_url, api_key, timeout


def _planner(
    settings: Settings, *, producer: Producer
) -> tuple[PromptHostTurnDecisionModel | PromptTurnPlanner, str, str]:
    client_types = {
        "openai": OpenAIResponsesJsonClient,
        "qwen": QwenChatCompletionsJsonClient,
        "deepseek": DeepSeekChatCompletionsJsonClient,
    }
    if producer == "legacy":
        provider, model, base_url, api_key, timeout = _host_provider(settings)
        client = client_types[provider](
            api_key=secret_value(api_key),
            base_url=base_url,
            model=model,
            timeout_seconds=timeout,
            retry_policy=model_client_retry_policy(settings),
        )
        return PromptHostTurnDecisionModel(client), provider, model

    missing_planner_env = [
        name
        for name in (
            "TURN_PLANNER_PROVIDER",
            "TURN_PLANNER_API_KEY",
            "TURN_PLANNER_BASE_URL",
            "TURN_PLANNER_MODEL",
        )
        if not os.environ.get(name, "").strip()
    ]
    if missing_planner_env:
        raise ValueError(
            "semantic Planner benchmark requires explicit configuration: "
            + ", ".join(missing_planner_env)
        )
    provider = settings.turn_planner_provider
    if provider not in client_types:
        raise ValueError("TURN_PLANNER_PROVIDER must be openai, qwen, or deepseek")
    if (
        settings.turn_planner_api_key is None
        or settings.turn_planner_base_url is None
        or settings.turn_planner_model is None
    ):
        raise ValueError(
            "TURN_PLANNER_API_KEY, TURN_PLANNER_BASE_URL, and TURN_PLANNER_MODEL are required"
        )
    client = client_types[provider](
        api_key=secret_value(settings.turn_planner_api_key),
        base_url=settings.turn_planner_base_url,
        model=settings.turn_planner_model,
        timeout_seconds=settings.turn_planner_timeout_seconds,
        retry_policy=turn_planner_retry_policy(settings),
    )
    return PromptTurnPlanner(client), provider, settings.turn_planner_model


def _single_action_kind(decision: SingleActionDecision) -> str:
    family = decision.adjudication.method.family.casefold()
    if family == "travel":
        return "travel"
    if family == "wait":
        return "wait"
    if family in {"rest", "sleep"}:
        return "rest"
    if family in {"ask", "dialogue", "speak", "talk"}:
        return "dialogue"
    return "action"


def _decision_kinds(decision: HostTurnDecision | ActionPlan) -> tuple[str, ...]:
    if isinstance(decision, ActionPlan):
        return tuple(step.kind for step in decision.steps)
    return (_single_action_kind(decision),)


async def _sample(
    planner: PromptHostTurnDecisionModel | PromptTurnPlanner,
    case: PlannerCorpusCase,
    *,
    producer: Producer,
    run_number: int,
) -> dict[str, Any]:
    legacy_context, semantic_context = _contexts(case, run_number=run_number)
    rejection_event = (
        "host_turn_decision_rejected" if producer == "legacy" else "turn_planner_rejected"
    )
    started_at = time.monotonic()
    with capture_logs() as logs:
        try:
            if producer == "legacy":
                if not isinstance(planner, PromptHostTurnDecisionModel):
                    raise TypeError("legacy benchmark requires legacy Planner")
                decision = await planner.generate(legacy_context)
            else:
                if not isinstance(planner, PromptTurnPlanner):
                    raise TypeError("semantic benchmark requires semantic Planner")
                decision = await planner.generate(semantic_context)
            failure_code = None
            actual_kinds = _decision_kinds(decision)
        except Exception as exc:  # noqa: BLE001 - benchmark aggregates terminal failures
            failure_code = getattr(exc, "code", type(exc).__name__)
            actual_kinds = ()
    calls = [
        item
        for item in logs
        if item.get("event") in {"structured_model_call_completed", "structured_model_call_failed"}
    ]
    transport_calls = sum(max(1, int(item.get("transport_attempts") or 1)) for item in calls)
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
        and not any(item.get("event") == rejection_event for item in logs),
        "model_calls": len(calls),
        "transport_calls": transport_calls,
        "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in calls),
        "output_tokens": sum(int(item.get("completion_tokens") or 0) for item in calls),
        "transport_retries": max(0, transport_calls - len(calls)),
        "structured_retries": sum(item.get("event") == rejection_event for item in logs),
    }


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["failure_code"] is None]
    unreadable = sum(sample["failure_code"] == "MODEL_OUTPUT_UNREADABLE" for sample in samples)
    return {
        "sample_count": len(samples),
        "success_count": len(successful),
        "terminal_failure_rate": round(1 - len(successful) / len(samples), 4),
        "failure_codes": sorted(
            {str(sample["failure_code"]) for sample in samples if sample["failure_code"]}
        ),
        "latency_ms": latency_summary(sample["duration_ms"] for sample in samples),
        "model_calls": sum(sample["model_calls"] for sample in samples),
        "transport_calls": sum(sample["transport_calls"] for sample in samples),
        "input_tokens": sum(sample["input_tokens"] for sample in samples),
        "output_tokens": sum(sample["output_tokens"] for sample in samples),
        "transport_retries": sum(sample["transport_retries"] for sample in samples),
        "structured_retries": sum(sample["structured_retries"] for sample in samples),
        "first_structure_success_rate": round(
            sum(sample["first_structure_success"] for sample in samples) / len(samples), 4
        ),
        "structured_success_rate": round(1 - unreadable / len(samples), 4),
        "step_count_accuracy": round(
            sum(bool(sample["step_count_correct"]) for sample in samples) / len(samples), 4
        ),
        "kind_sequence_accuracy": round(
            sum(sample["kind_sequence_correct"] for sample in samples) / len(samples), 4
        ),
    }


async def run(
    *,
    producer: Producer,
    repetitions: int,
    output: Path,
    transport_call_budget: int | None,
) -> None:
    settings = Settings()
    planner, provider, model = _planner(settings, producer=producer)
    samples: list[dict[str, Any]] = []
    for run_number in range(repetitions):
        for case in CASES:
            samples.append(
                await _sample(
                    planner,
                    case,
                    producer=producer,
                    run_number=run_number,
                )
            )
            used = sum(sample["transport_calls"] for sample in samples)
            if transport_call_budget is not None and used > transport_call_budget:
                raise RuntimeError(
                    f"transport call budget exceeded: {used} > {transport_call_budget}"
                )

    by_cohort: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_cohort[sample["cohort"]].append(sample)
        by_case[sample["case"]].append(sample)

    report = {
        "schema_version": 2,
        "issue": 357,
        "subject_revision": os.getenv("ISSUE_357_SUBJECT_REVISION", _git_revision()),
        "benchmark_tool_revision": _git_revision(),
        "producer": producer,
        "planner_instruction_version": (
            TURN_PLANNER_PROMPT_VERSION if producer == "semantic" else "legacy-host-decision"
        ),
        "runtime": {
            "machine": platform.node(),
            "python": platform.python_version(),
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "provider": provider,
        "model": model,
        "configuration": {
            "repetitions": repetitions,
            "transport_call_budget": transport_call_budget,
            "timeout_seconds": (
                settings.turn_planner_timeout_seconds
                if producer == "semantic"
                else _host_provider(settings)[4]
            ),
            "max_attempts": (
                settings.turn_planner_max_attempts
                if producer == "semantic"
                else settings.model_client_max_attempts
            ),
            "retry_backoff_seconds": (
                settings.turn_planner_retry_backoff_seconds
                if producer == "semantic"
                else settings.model_client_retry_backoff_seconds
            ),
        },
        "overall": _aggregate(samples),
        "cohorts": {name: _aggregate(items) for name, items in sorted(by_cohort.items())},
        "cases": {name: _aggregate(items) for name, items in sorted(by_case.items())},
    }
    assert_sanitized_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Issue #357 sanitized {producer} Planner report: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer", choices=("legacy", "semantic"), required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--transport-call-budget", type=int)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("ISSUE_357_BENCHMARK_OUTPUT", "/tmp/issue-357-planner.json")),
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.transport_call_budget is not None and args.transport_call_budget < 1:
        parser.error("--transport-call-budget must be at least 1")
    anyio.run(
        partial(
            run,
            producer=args.producer,
            repetitions=args.repetitions,
            output=args.output,
            transport_call_budget=args.transport_call_budget,
        )
    )


if __name__ == "__main__":
    main()
