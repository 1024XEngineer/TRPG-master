"""Scripted 9-utterance probe over ONE evolving game state (issue #334).

Not part of CI. Runs only when ``RUN_UTTERANCE_PROBE=1``: every turn drives the
provider configured in ``.env`` through the production composition of
``ActionPlanTurnApplication``.

Why a scripted probe instead of the ``test_play_sim_real_model`` simulation:
the utterances under test are **ordered** — later ones ("把桌上杂志装进背包",
"把旅店老板装进背包") only mean anything after the earlier ones have moved the
investigator into a runtime-created inn. So the whole list has to run against a
single, continuously advancing game state, with a model-authored player replaced
by a fixed script.

Dice are pinned to a constant low roll so a failed percentile can never be
confused with the system mishandling an utterance — every check that is legally
raised succeeds.

One process = one game state = one run (conftest builds a per-process throwaway
SQLite file), so N parallel runs are N parallel pytest processes. The transcript
goes to ``PROBE_OUT`` as a single JSON document.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from collaboration_framework.engine import AdjudicationEngineService, RuleEngineService
from collaboration_framework.engine.dice import DiceRoller
from starlette.testclient import TestClient

from app.adapters import (
    SqlAlchemyActionPlanRunStore,
    SqlAlchemyEngineStore,
    SqlAlchemyRecentHistorySource,
)
from app.controller import ws as ws_controller
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.main import app
from tests.test_ws import (
    advance_to_building,
    complete_character,
    create_room,
    receive_json,
    receive_replayed_opening,
    register_and_login,
    start_game,
)

RUN_PROBE = os.getenv("RUN_UTTERANCE_PROBE") == "1"
OUT_PATH = Path(os.getenv("PROBE_OUT", "/tmp/trpg-utterance-probe.json"))
RUN_LABEL = os.getenv("PROBE_LABEL", "run")
# One compound utterance can be three steps, each a provider round trip plus a
# check handshake; 8 minutes is slack, not an expectation.
TURN_TIMEOUT_SECONDS = float(os.getenv("PROBE_TURN_TIMEOUT", "480"))

pytestmark = pytest.mark.skipif(
    not RUN_PROBE,
    reason="set RUN_UTTERANCE_PROBE=1 to call the configured provider",
)


UTTERANCES = (
    "接下委托。",
    "去墓地找守墓人。",
    "仔细观察。",
    "用禁酒令的事威胁他，询问他道格拉斯常去的地方有哪里，然后去他说的地方看看。",
    "去旅馆休息，睡到第二天早上。",
    "仔细观察周围环境",
    "把桌上杂志装进背包",
    "把旅店老板装进背包",
    "掏出炸弹炸掉旅馆",
)


class ConstantDiceSource:
    """Always roll 2: never a fumble, and an extreme success at any target ≥ 10.

    Pinning the die is what makes the run readable — the question under test is
    whether the utterance is understood and legally resolved, not whether a d100
    happened to land.
    """

    def randint(self, minimum: int, maximum: int) -> int:
        return min(max(2, minimum), maximum)


@pytest.fixture
def probe_settings() -> Settings:
    settings = Settings()
    assert settings.host_model_provider != "fake", (
        "utterance probe 需要 .env 里配置 HOST_MODEL_PROVIDER 为远程 provider"
    )
    return settings


@pytest.fixture
def traced_ws(monkeypatch: pytest.MonkeyPatch, probe_settings: Settings) -> list[dict[str, Any]]:
    """Bind the WS controller to the real model + fixed dice, and record internals.

    The orchestrator deliberately reduces an Engine rejection to an opaque,
    player-safe code, so the probe traces the planner's ActionPlan, each step
    proposal and each Engine rejection: that is the difference between "the
    model proposed something illegal" and "the Engine wrongly refused".
    """

    trace: list[dict[str, Any]] = []
    session_factory = ws_controller.async_session_factory
    store = SqlAlchemyEngineStore(session_factory)
    adjudication_engine = AdjudicationEngineService(store, dice=DiceRoller(ConstantDiceSource()))
    application = build_action_plan_turn_application(
        store=store,
        engine=RuleEngineService(store),
        adjudication_engine=adjudication_engine,
        plan_store=SqlAlchemyActionPlanRunStore(session_factory),
        settings=probe_settings,
        recent_history_source=SqlAlchemyRecentHistorySource(session_factory),
    )

    planner = application._planner
    original_generate = planner.generate

    async def traced_generate(context):
        plan = await original_generate(context)
        trace.append(
            {
                "kind": "plan",
                "decision": type(plan).__name__,
                "utterance": context.player_input.utterance,
                "steps": [
                    {"kind": step.kind, "semantic_goal": step.semantic_goal}
                    for step in getattr(plan, "steps", ())
                ],
                "payload": json.loads(plan.model_dump_json(by_alias=True)),
            }
        )
        return plan

    monkeypatch.setattr(planner, "generate", traced_generate)

    adjudicator = application._orchestrator._adjudicator
    original_adjudicate = adjudicator.adjudicate

    async def traced_adjudicate(context):
        try:
            proposal = await original_adjudicate(context)
        except Exception as exc:
            trace.append(
                {
                    "kind": "adjudicator_failed",
                    "step_index": context.step_index,
                    "semantic_goal": context.step.semantic_goal,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
            )
            raise
        trace.append(
            {
                "kind": "proposal",
                "step_index": context.step_index,
                "semantic_goal": context.step.semantic_goal,
                "proposal": json.loads(proposal.model_dump_json(by_alias=True)),
            }
        )
        return proposal

    monkeypatch.setattr(adjudicator, "adjudicate", traced_adjudicate)

    original_submit = adjudication_engine.submit

    async def traced_submit(request):
        try:
            return await original_submit(request)
        except Exception as exc:
            trace.append(
                {
                    "kind": "engine_rejected",
                    "summary": request.adjudication.summary,
                    "error": f"{type(exc).__name__}: {exc}"[:800],
                }
            )
            raise

    monkeypatch.setattr(adjudication_engine, "submit", traced_submit)

    monkeypatch.setattr(ws_controller, "action_plan_turn_application", application)
    monkeypatch.setattr(ws_controller, "adjudication_engine_service", adjudication_engine)
    return trace


def _receive(ws) -> dict[str, Any]:
    """A frame, or a readable failure — never an indefinite hang."""

    return receive_json(ws, timeout=TURN_TIMEOUT_SECONDS)


STOP_TYPES = {"turn.completed", "adjudication.pending", "turn.failed", "error"}


def _drain_until_stop(ws, seen: list[dict[str, Any]], limit: int = 200) -> dict[str, Any]:
    for _ in range(limit):
        message = _receive(ws)
        seen.append(message)
        message_type = message.get("type") or message.get("message_type")
        if message_type in STOP_TYPES:
            return message
    raise AssertionError("turn never reached a stop point")


def _send(ws, player_id: str, event_type: str, payload: dict[str, Any]) -> None:
    ws.send_json({"type": event_type, "playerId": player_id, "payload": payload})


def _request_id() -> str:
    return f"probe-req-{uuid.uuid4().hex[:12]}"


def _settle(ws, player_id: str, stop: dict[str, Any], seen: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer every check the turn raises: take the first skill, accept the roll."""

    for _ in range(12):
        if (stop.get("type") or stop.get("message_type")) != "adjudication.pending":
            return stop
        payload = stop["payload"]
        if payload["status"] == "awaiting_skill_choice":
            decision = payload["pendingDecision"]
            _send(
                ws,
                player_id,
                "adjudication.select",
                {
                    "clientActionId": payload["correlationId"],
                    "requestId": _request_id(),
                    "sourceRevision": payload["sourceRevision"],
                    "decisionId": decision["decision_id"],
                    "decisionVersion": decision["decision_version"],
                    "candidateId": decision["options"][0]["candidate_id"],
                },
            )
        elif payload["status"] == "awaiting_post_roll_decision":
            check_run = payload["checkRun"]
            accept = next(
                option
                for option in check_run["post_roll_options"]
                if option["kind"] == "accept_result"
            )
            _send(
                ws,
                player_id,
                "adjudication.post_roll",
                {
                    "clientActionId": payload["correlationId"],
                    "requestId": _request_id(),
                    "sourceRevision": payload["sourceRevision"],
                    "checkId": check_run["check_id"],
                    "checkVersion": check_run["version"],
                    "optionId": accept["option_id"],
                },
            )
        else:
            raise AssertionError(f"unexpected pending status {payload['status']!r}")
        stop = _drain_until_stop(ws, seen)
    raise AssertionError("turn kept asking for check decisions past the budget")


def _view_digest(view: dict[str, Any]) -> dict[str, Any]:
    scene = view.get("scene", {})
    return {
        "scene_id": view.get("scene_id"),
        "scene_name": scene.get("name"),
        "world": view.get("world"),
        "inventory": [item.get("name") for item in (view.get("inventory") or [])],
        "loose_items": [item.get("name") for item in (scene.get("loose_items") or [])],
        "visible_entities": [
            f"{entity.get('id')}:{entity.get('name')}"
            for entity in scene.get("visible_entities", [])
        ],
        "visible_actors": [actor.get("name") for actor in scene.get("visible_actors", [])],
        "exits": [exit_.get("name") for exit_ in scene.get("available_exits", [])],
        "known_information": [item.get("id") for item in view.get("known_information", [])],
        "known_locations": [
            f"{loc.get('id')}:{loc.get('name')}" for loc in (view.get("known_locations") or [])
        ],
    }


def _checks(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rolled = []
    for message in seen:
        if message.get("type") != "adjudication.pending":
            continue
        check_run = message["payload"].get("checkRun")
        if not check_run:
            continue
        roll = check_run.get("final_result") or check_run.get("roll") or {}
        rolled.append(
            {
                "skill": check_run.get("selected_skill_name"),
                "difficulty": check_run.get("difficulty"),
                "target": check_run.get("target_value"),
                "roll": roll.get("value") or roll.get("roll"),
                "level": roll.get("level") or roll.get("outcome"),
            }
        )
    return rolled


def test_scripted_utterances_over_one_game_state(traced_ws: list[dict[str, Any]]) -> None:
    client = TestClient(app)
    account = f"probe_{uuid.uuid4().hex[:8]}"
    token = register_and_login(client, account)
    room = create_room(client, token)
    advance_to_building(client, room)
    complete_character(client, room["roomId"], room["reconnectToken"])
    start_game(client, room, token)

    player_id = room["playerId"]
    turns: list[dict[str, Any]] = []
    started = time.monotonic()

    with client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _send(ws, player_id, "room.join", {"reconnectToken": room["reconnectToken"]})
        _receive(ws)  # session.bound
        opening_view = _receive(ws)  # view.updated
        opening = receive_replayed_opening(ws)

        limit = int(os.getenv("PROBE_LIMIT", str(len(UTTERANCES))))
        for index, utterance in enumerate(UTTERANCES[:limit], start=1):
            action_id = f"probe-{index}-{uuid.uuid4().hex[:8]}"
            trace_mark = len(traced_ws)
            turn_started = time.monotonic()
            seen: list[dict[str, Any]] = []
            record: dict[str, Any] = {"index": index, "utterance": utterance}
            try:
                _send(
                    ws,
                    player_id,
                    "action.plan.submit",
                    {"clientActionId": action_id, "utterance": utterance},
                )
                stop = _drain_until_stop(ws, seen)
                stop = _settle(ws, player_id, stop, seen)
            except Exception as exc:  # noqa: BLE001 — a broken turn must not end the run
                record["outcome"] = "harness_error"
                record["error"] = f"{type(exc).__name__}: {exc}"[:800]
                turns.append(record | {"trace": traced_ws[trace_mark:]})
                break

            stop_type = stop.get("type") or stop.get("message_type")
            record["outcome"] = stop_type
            record["seconds"] = round(time.monotonic() - turn_started, 1)
            record["event_types"] = [
                message.get("type") or message.get("message_type") for message in seen
            ]
            record["checks"] = _checks(seen)
            plan_started = next(
                (message for message in seen if message.get("type") == "plan.started"), None
            )
            if plan_started:
                record["plan_total_steps"] = plan_started["payload"]["totalSteps"]
            plan_stopped = next(
                (message for message in seen if message.get("type") == "plan.stopped"), None
            )
            if plan_stopped:
                record["plan_stopped"] = plan_stopped["payload"]
            if stop_type == "turn.completed":
                record["narration"] = stop["payload"]["narration"]["text"]
                record["view"] = _view_digest(stop["payload"]["player_view"])
            else:
                record["failure"] = stop.get("payload")
            record["trace"] = traced_ws[trace_mark:]
            turns.append(record)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "label": RUN_LABEL,
                "room_id": room["roomId"],
                "seconds": round(time.monotonic() - started, 1),
                "opening_view": _view_digest(opening_view["payload"]["playerView"]),
                "opening": opening["payload"]["text"],
                "turns": turns,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert turns, "probe produced no turns"
