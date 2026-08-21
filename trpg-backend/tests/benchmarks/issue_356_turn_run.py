"""Explicit WebSocket benchmark for Issue #356.

This file deliberately does not match pytest's default ``test_*.py`` pattern.
Run it explicitly as documented in ``docs/issue-356-validation.md``. The JSON
output contains counts, durations, failure codes, and provider metadata only.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanStep,
    ActionTarget,
    JsonObject,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    RequiredAdjudicationCheck,
    SingleActionDecision,
    SkillCheckCandidate,
)
from collaboration_framework.host.application import ActionPlanNarrator
from starlette.testclient import TestClient

from app.adapters import structured_http
from app.controller import ws as ws_controller
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.main import app
from tests.benchmarks.issue_356_metrics import aggregate_scenario, assert_sanitized_report
from tests.test_ws import (
    advance_to_building,
    complete_character,
    create_room,
    receive_replayed_opening,
    receive_until,
    register_and_login,
    start_game,
)

COUNT_FIELDS = (
    "planner_calls",
    "step_adjudicator_calls",
    "narrator_calls",
    "engine_submit_calls",
    "engine_status_calls",
    "plan_create_calls",
    "plan_cas_calls",
    "repair_calls",
    "model_transport_retries",
)


class _SingleNoCheckPlanner:
    async def generate(self, context) -> SingleActionDecision:  # noqa: ANN001
        text = context.player_input.utterance
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=text,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="action", description=text),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        )


class _SinglePendingPlanner:
    async def generate(self, context) -> SingleActionDecision:  # noqa: ANN001
        text = context.player_input.utterance
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=text,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="investigate", description=text),
                check=RequiredAdjudicationCheck(
                    candidates=(
                        SkillCheckCandidate(
                            candidate_id="library-use",
                            skill_id="library-use",
                            difficulty="regular",
                            method_summary="inspect records",
                            player_safe_reason="a check is required",
                        ),
                    )
                ),
                success_effects=(NarrativeOnlyEffect(),),
            )
        )


class _InvalidTargetPlanner:
    async def generate(self, context) -> SingleActionDecision:  # noqa: ANN001
        text = context.player_input.utterance
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=text,
                target=ActionTarget(kind="entity", id="missing-visible-target"),
                method=ActionMethod(family="observe", description=text),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        )


class _TwoStepPlanner:
    async def generate(self, context) -> ActionPlan:  # noqa: ANN001
        return ActionPlan(
            goal=context.player_input.utterance,
            steps=(
                ActionPlanStep(kind="action", semantic_goal="observe the current scene"),
                ActionPlanStep(kind="action", semantic_goal="review the visible details"),
            ),
        )


class _NarrativeStepAdjudicator:
    async def adjudicate(self, context) -> ActionAdjudication:  # noqa: ANN001
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="location", id=context.player_view.scene.id),
            method=ActionMethod(family="action", description=context.step.semantic_goal),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class _RepairAdjudicator:
    async def adjudicate(self, context) -> ActionAdjudication:  # noqa: ANN001
        visible = context.player_view.scene.visible_entities
        if not visible:
            raise AssertionError("repair benchmark requires one visible entity")
        target = next(
            (entity for entity in visible if entity.name in context.player_input.utterance),
            None,
        )
        if target is None:
            raise AssertionError("repair benchmark input must name one visible entity")
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.player_input.utterance,
            target=ActionTarget(kind="entity", id=target.id),
            method=ActionMethod(
                family="observe",
                description=context.player_input.utterance,
            ),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class _FixedNarrationModel:
    async def generate(self, context) -> JsonObject:  # noqa: ANN001
        del context
        return {
            "kind": "narration",
            "text": "The turn reached a stable public result.",
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class _FailOnceNarrator:
    def __init__(self, delegate) -> None:  # noqa: ANN001
        self._delegate = delegate
        self._failed = False

    async def narrate(self, context):  # noqa: ANN001, ANN201
        if not self._failed:
            self._failed = True
            raise RuntimeError("synthetic narrator outage")
        return await self._delegate.narrate(context)


class _Probe:
    def __init__(self, application, *, lose_first_commit_response: bool = False) -> None:  # noqa: ANN001
        self.application = application
        self.counts: defaultdict[str, int] = defaultdict(int)
        self._lose_first_commit_response = lose_first_commit_response
        self._commit_response_lost = False
        self._restores: list[tuple[object, str, object]] = []

    def __enter__(self) -> _Probe:
        self._wrap_async(self.application._planner, "generate", "planner_calls")
        adjudicator = self.application._orchestrator._adjudicator
        self._wrap_async(
            adjudicator,
            "adjudicate",
            "step_adjudicator_calls",
            count_repair=True,
        )
        self._wrap_async(self.application._narrator, "narrate", "narrator_calls")
        executor = self.application._orchestrator._executor
        self._wrap_async(
            executor,
            "submit",
            "engine_submit_calls",
            lose_commit_response=self._lose_first_commit_response,
        )
        self._wrap_async(executor, "get_status", "engine_status_calls")
        store = self.application._orchestrator._store
        self._wrap_async(store, "create", "plan_create_calls")
        self._wrap_async(store, "compare_and_swap", "plan_cas_calls")
        original_warning = structured_http.logger.warning

        def measured_warning(event: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            if event == "structured_json_request_retry":
                self.counts["model_transport_retries"] += 1
            return original_warning(event, *args, **kwargs)

        self._restores.append((structured_http.logger, "warning", original_warning))
        structured_http.logger.warning = measured_warning
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        del exc_type, exc, traceback
        for target, name, original in reversed(self._restores):
            setattr(target, name, original)

    def _wrap_async(
        self,
        target: object,
        name: str,
        counter: str,
        *,
        count_repair: bool = False,
        lose_commit_response: bool = False,
    ) -> None:
        original = getattr(target, name)

        async def measured(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            self.counts[counter] += 1
            if count_repair:
                context = args[0] if args else kwargs.get("context")
                if getattr(context, "previous_rejection", None) is not None:
                    self.counts["repair_calls"] += 1
            result = await original(*args, **kwargs)
            if lose_commit_response and not self._commit_response_lost:
                self._commit_response_lost = True
                raise TimeoutError("synthetic response loss after authoritative commit")
            return result

        self._restores.append((target, name, original))
        setattr(target, name, measured)


@contextmanager
def _application_components(application) -> Iterator[None]:  # noqa: ANN001
    original = (
        application._planner,
        application._narrator,
        application._orchestrator._adjudicator,
        getattr(application._dispatcher, "_repair_adjudicator", None),
    )
    try:
        yield
    finally:
        application._planner = original[0]
        application._narrator = original[1]
        application._orchestrator._adjudicator = original[2]
        if hasattr(application._dispatcher, "_repair_adjudicator"):
            application._dispatcher._repair_adjudicator = original[3]


@contextmanager
def _mute_content_logs() -> Iterator[None]:
    names = (
        "log_check_result",
        "log_narration_output",
        "log_player_input",
        "log_state_changes",
        "log_turn_completed",
        "log_turn_failed",
    )
    originals = {
        name: getattr(ws_controller, name) for name in names if hasattr(ws_controller, name)
    }

    def discard(**kwargs) -> None:  # noqa: ANN003
        del kwargs

    try:
        for name in originals:
            setattr(ws_controller, name, discard)
        yield
    finally:
        for name, original in originals.items():
            setattr(ws_controller, name, original)


def _configure_fake(application, scenario: str) -> bool:  # noqa: ANN001
    application._narrator = ActionPlanNarrator(_FixedNarrationModel())
    lose_response = False
    if scenario in {"single_no_check", "single_narrator_retry", "commit_response_loss"}:
        application._planner = _SingleNoCheckPlanner()
        lose_response = scenario == "commit_response_loss"
    elif scenario == "single_pending_cancel":
        application._planner = _SinglePendingPlanner()
    elif scenario == "single_validation_repair":
        application._planner = _InvalidTargetPlanner()
        repair = _RepairAdjudicator()
        application._orchestrator._adjudicator = repair
        if hasattr(application._dispatcher, "_repair_adjudicator"):
            application._dispatcher._repair_adjudicator = repair
    elif scenario == "multi_step":
        application._planner = _TwoStepPlanner()
        application._orchestrator._adjudicator = _NarrativeStepAdjudicator()
    else:
        raise ValueError(f"unknown fake scenario: {scenario}")
    if scenario == "single_narrator_retry":
        application._narrator = _FailOnceNarrator(application._narrator)
    return lose_response


def _prepare_room(client: TestClient, label: str) -> tuple[str, dict[str, Any]]:
    account = f"i356{label}{uuid.uuid4().hex[:8]}"[:24]
    token = register_and_login(client, account)
    room = create_room(client, token)
    advance_to_building(client, room)
    complete_character(client, room["roomId"], room["reconnectToken"])
    start_game(client, room, token)
    return token, room


def _join(client: TestClient, token: str, room: dict[str, Any]):
    socket = client.websocket_connect(f"/ws/{room['roomId']}?token={token}")
    ws = socket.__enter__()
    ws.send_json(
        {
            "type": "room.join",
            "playerId": room["playerId"],
            "payload": {"reconnectToken": room["reconnectToken"]},
        }
    )
    ws.receive_json()
    ws.receive_json()
    receive_replayed_opening(ws)
    return socket, ws


def _submit(ws, room: dict[str, Any], action_id: str, label: str) -> None:  # noqa: ANN001
    inputs = {
        "single_validation_repair": "查看托马斯·金博尔",
        "real_observation": "观察当前房间",
        "real_investigation": "仔细检查书架上的文件",
        "real_multi_step": "先观察房间，然后询问眼前的人",
    }
    ws.send_json(
        {
            "type": "action.plan.submit",
            "playerId": room["playerId"],
            "payload": {
                "clientActionId": action_id,
                "utterance": inputs.get(label, f"benchmark-{label}"),
            },
        }
    )


def _is_completed(message: dict[str, Any]) -> bool:
    return (
        message.get("type") == "turn.completed" or message.get("message_type") == "turn.completed"
    )


def _settle_pending(ws, room: dict[str, Any], pending: dict[str, Any]) -> tuple[dict, list[dict]]:  # noqa: ANN001
    all_seen: list[dict] = []
    current = pending
    for decision_number in range(6):
        payload = current["payload"]
        status = payload["status"]
        if status == "awaiting_skill_choice":
            decision = payload["pendingDecision"]
            ws.send_json(
                {
                    "type": "adjudication.select",
                    "playerId": room["playerId"],
                    "payload": {
                        "clientActionId": payload["correlationId"],
                        "requestId": f"bench-select-{decision_number}-{uuid.uuid4().hex[:8]}",
                        "sourceRevision": payload["sourceRevision"],
                        "decisionId": decision["decision_id"],
                        "decisionVersion": decision["decision_version"],
                        "candidateId": decision["options"][0]["candidate_id"],
                    },
                }
            )
        elif status == "awaiting_post_roll_decision":
            check_run = payload["checkRun"]
            accept = next(
                option
                for option in check_run["post_roll_options"]
                if option["kind"] == "accept_result"
            )
            ws.send_json(
                {
                    "type": "adjudication.post_roll",
                    "playerId": room["playerId"],
                    "payload": {
                        "clientActionId": payload["correlationId"],
                        "requestId": f"bench-accept-{decision_number}-{uuid.uuid4().hex[:8]}",
                        "sourceRevision": payload["sourceRevision"],
                        "checkId": check_run["check_id"],
                        "checkVersion": check_run["version"],
                        "optionId": accept["option_id"],
                    },
                }
            )
        else:
            raise AssertionError(f"unsupported pending status: {status}")
        stop, seen = receive_until(
            ws,
            lambda message: (
                _is_completed(message)
                or message.get("type") in {"adjudication.pending", "turn.failed"}
            ),
            limit=60,
        )
        all_seen.extend(seen)
        if _is_completed(stop) or stop.get("type") == "turn.failed":
            return stop, all_seen
        current = stop
    raise AssertionError("pending workflow exceeded decision budget")


def _run_sample(
    client: TestClient,
    application,
    *,
    scenario: str,
    sample_number: int,
    real_mode: bool,
) -> dict[str, Any]:
    token, room = _prepare_room(client, f"{sample_number:x}")
    action_id = f"issue356-{scenario}-{sample_number}-{uuid.uuid4().hex[:8]}"
    expected_steps = 0 if real_mode else (2 if scenario == "multi_step" else 1)
    failure_code: str | None = None
    first_pending_ms: float | None = None
    start = 0.0
    end_to_end_ms = 0.0
    with _application_components(application), _mute_content_logs():
        lose_response = False if real_mode else _configure_fake(application, scenario)
        with _Probe(application, lose_first_commit_response=lose_response) as probe:
            socket, ws = _join(client, token, room)
            try:
                start = time.perf_counter()
                try:
                    _submit(ws, room, action_id, scenario)
                    stop, _ = receive_until(
                        ws,
                        lambda message: (
                            _is_completed(message)
                            or message.get("type") in {"adjudication.pending", "turn.failed"}
                        ),
                        limit=60,
                    )
                    if stop.get("type") == "adjudication.pending":
                        first_pending_ms = (time.perf_counter() - start) * 1000
                        if scenario == "single_pending_cancel" and not real_mode:
                            payload = stop["payload"]
                            decision = payload["pendingDecision"]
                            ws.send_json(
                                {
                                    "type": "adjudication.select",
                                    "playerId": room["playerId"],
                                    "payload": {
                                        "clientActionId": action_id,
                                        "requestId": f"bench-cancel-{uuid.uuid4().hex[:8]}",
                                        "sourceRevision": payload["sourceRevision"],
                                        "decisionId": decision["decision_id"],
                                        "decisionVersion": decision["decision_version"],
                                        "cancel": True,
                                    },
                                }
                            )
                            stop, _ = receive_until(ws, _is_completed, limit=60)
                        else:
                            stop, _ = _settle_pending(ws, room, stop)
                    if stop.get("type") == "turn.failed":
                        failure_code = str(stop.get("payload", {}).get("code", "TURN_FAILED"))
                    if scenario == "single_narrator_retry" and not real_mode:
                        if failure_code != "PLAN_NARRATOR_FAILED":
                            raise AssertionError(f"expected narrator failure, got {failure_code}")
                        failure_code = None
                        _submit(ws, room, action_id, scenario)
                        stop, _ = receive_until(ws, _is_completed, limit=60)
                except AssertionError:
                    if not real_mode:
                        raise
                    failure_code = "BENCHMARK_TIMEOUT"
                end_to_end_ms = (time.perf_counter() - start) * 1000
            finally:
                socket.__exit__(None, None, None)
        counts = {field: probe.counts[field] for field in COUNT_FIELDS}

    run = None
    if hasattr(application, "get_plan"):
        import anyio

        run = anyio.run(application.get_plan, room["roomId"], action_id)
    step_count = len(run.steps) if run is not None else expected_steps
    sample = {
        "failure_code": failure_code,
        "step_count": step_count,
        "end_to_end_ms": end_to_end_ms,
        "first_pending_ms": first_pending_ms,
        **counts,
    }
    assert_sanitized_report(sample)
    return sample


def _provider_model(settings: Settings) -> tuple[str, str | None]:
    provider = settings.host_model_provider
    if provider == "deepseek":
        return provider, settings.deepseek_model
    if provider == "qwen":
        return provider, settings.qwen_model
    if provider == "openai":
        return provider, settings.openai_model
    return provider, None


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_issue_356_turn_run_benchmark(
    action_plan_store_factory: Callable,
) -> None:
    mode = os.getenv("ISSUE_356_BENCHMARK_MODE", "fake")
    if mode not in {"fake", "real"}:
        raise ValueError("ISSUE_356_BENCHMARK_MODE must be fake or real")
    repeats = int(os.getenv("ISSUE_356_BENCHMARK_REPEATS", "3" if mode == "fake" else "2"))
    if repeats < 1:
        raise ValueError("ISSUE_356_BENCHMARK_REPEATS must be >= 1")
    output_path = Path(
        os.getenv("ISSUE_356_BENCHMARK_OUTPUT", f"/tmp/issue-356-{mode}-benchmark.json")
    )

    original_application = ws_controller.action_plan_turn_application
    settings = Settings(host_model_provider="fake")
    application = original_application
    if mode == "real":
        settings = Settings()
        if settings.host_model_provider == "fake":
            raise RuntimeError("real mode requires a configured non-fake HOST_MODEL_PROVIDER")
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

    provider, model = _provider_model(settings)
    sync_client = TestClient(app)
    scenarios = (
        (
            "single_no_check",
            "single_pending_cancel",
            "single_validation_repair",
            "single_narrator_retry",
            "commit_response_loss",
            "multi_step",
        )
        if mode == "fake"
        else ("real_observation", "real_investigation", "real_multi_step")
    )
    sample_results: dict[str, list[dict[str, Any]]] = {scenario: [] for scenario in scenarios}
    try:
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
                        real_mode=mode == "real",
                    )
                )
    finally:
        ws_controller.action_plan_turn_application = original_application

    all_samples = [sample for samples in sample_results.values() for sample in samples]
    report = {
        "schema_version": 1,
        "issue": 356,
        "subject_revision": os.getenv("ISSUE_356_SUBJECT_REVISION", _git_revision()),
        "benchmark_tool_revision": _git_revision(),
        "mode": mode,
        "provider": provider,
        "model": model,
        "runtime": {
            "python": platform.python_version(),
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "percentile_method": "nearest-rank",
        "scenario_repeats": repeats,
        "overall": aggregate_scenario(all_samples),
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
    print(f"Issue #356 sanitized benchmark report: {output_path}")
