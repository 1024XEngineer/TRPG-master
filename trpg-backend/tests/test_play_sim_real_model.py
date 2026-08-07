"""Real-model play simulation for the issue #246 ActionPlan turn path.

Not part of CI: the whole module is skipped unless ``RUN_REAL_MODEL_PLAY_SIM=1``
is set, because every scenario drives the provider configured in ``.env``
(currently DeepSeek) through the production composition of
``ActionPlanTurnApplication``.

What it covers, end to end over the real WebSocket protocol:

* a single-intent utterance settles in one ``turn.completed``;
* a multi-intent utterance runs as an ``ActionPlan`` and settles once;
* a check that reaches ``awaiting_skill_choice`` can be cancelled by the player
  (the "cancel at the dice roll" button) for both a standalone single action and
  a plan step;
* ``action.plan.cancel`` stops the remaining steps of a multi-intent plan.

The simulated player is itself the configured model: given the last player-safe
narration it writes the next utterance. Scenario shape (single vs. compound) is
requested in the prompt so the run still exercises both branches deterministically
enough to assert on, while the exact wording stays model-authored.

Every WebSocket frame is appended to ``SIM_LOG_PATH`` (default
``/tmp/trpg-play-sim.jsonl``) so a failing run can be diffed against the server
logs.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from collaboration_framework.engine import AdjudicationEngineService, RuleEngineService
from starlette.testclient import TestClient

from app.adapters import (
    DeepSeekChatCompletionsJsonClient,
    QwenChatCompletionsJsonClient,
    SqlAlchemyActionPlanRunStore,
    SqlAlchemyEngineStore,
    SqlAlchemyRecentHistorySource,
)
from app.controller import ws as ws_controller
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings, secret_value
from app.main import app
from tests.test_ws import (
    advance_to_building,
    complete_character,
    create_room,
    receive_replayed_opening,
    register_and_login,
    start_game,
)

RUN_SIM = os.getenv("RUN_REAL_MODEL_PLAY_SIM") == "1"
SIM_LOG_PATH = Path(os.getenv("SIM_LOG_PATH", "/tmp/trpg-play-sim.jsonl"))

pytestmark = pytest.mark.skipif(
    not RUN_SIM,
    reason="set RUN_REAL_MODEL_PLAY_SIM=1 to run the real-model play simulation",
)


# --------------------------------------------------------------------------- #
# transcript
# --------------------------------------------------------------------------- #


class Transcript:
    """Append-only JSONL record of everything the simulation saw."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")
        self._started = time.monotonic()

    def write(self, kind: str, **fields: Any) -> None:
        record = {
            "t": round(time.monotonic() - self._started, 3),
            "kind": kind,
            **fields,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[sim {record['t']:>7.2f}s] {kind}: {json.dumps(fields, ensure_ascii=False)[:400]}")


@pytest.fixture(scope="module")
def transcript() -> Transcript:
    return Transcript(SIM_LOG_PATH)


# --------------------------------------------------------------------------- #
# real-model composition
# --------------------------------------------------------------------------- #


def _structured_client(settings: Settings):
    if settings.host_model_provider == "deepseek":
        assert settings.deepseek_api_key is not None, ".env 缺少 DEEPSEEK_API_KEY"
        return DeepSeekChatCompletionsJsonClient(
            api_key=secret_value(settings.deepseek_api_key),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )
    if settings.host_model_provider == "qwen":
        assert settings.qwen_api_key is not None, ".env 缺少 QWEN_API_KEY"
        return QwenChatCompletionsJsonClient(
            api_key=secret_value(settings.qwen_api_key),
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            timeout_seconds=settings.qwen_timeout_seconds,
        )
    raise AssertionError(
        f"real-model sim 需要远程 provider，当前 .env 是 {settings.host_model_provider!r}"
    )


@pytest.fixture(scope="module")
def sim_settings() -> Settings:
    settings = Settings()
    assert settings.host_model_provider != "fake", (
        "real-model sim 需要 .env 里配置 HOST_MODEL_PROVIDER 为远程 provider"
    )
    return settings


@pytest.fixture
def real_model_ws(
    monkeypatch: pytest.MonkeyPatch,
    sim_settings: Settings,
    transcript: Transcript,
) -> None:
    """Swap the fake ActionPlan application for one bound to the configured model.

    The session factory is read back off ``ws_controller`` because conftest has
    already rebound it to the throwaway test database; re-importing conftest to
    get at it would build a second engine against a second file.
    """

    session_factory = ws_controller.async_session_factory
    store = SqlAlchemyEngineStore(session_factory)
    adjudication_engine = AdjudicationEngineService(store)
    application = build_action_plan_turn_application(
        store=store,
        engine=RuleEngineService(store),
        adjudication_engine=adjudication_engine,
        plan_store=SqlAlchemyActionPlanRunStore(session_factory),
        settings=sim_settings,
        recent_history_source=SqlAlchemyRecentHistorySource(session_factory),
    )
    _trace_adjudications(application, adjudication_engine, transcript, monkeypatch)
    monkeypatch.setattr(ws_controller, "action_plan_turn_application", application)
    monkeypatch.setattr(ws_controller, "adjudication_engine_service", adjudication_engine)


def _trace_adjudications(
    application,
    adjudication_engine: AdjudicationEngineService,
    transcript: Transcript,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record what the model proposed and why the Engine accepted or rejected it.

    The orchestrator deliberately turns an Engine rejection into an opaque,
    player-safe ``STEP_ADJUDICATION_REJECTED``; the simulation needs the real
    reason to be able to tell a model mistake from an Engine defect.
    """

    adjudicator = application._orchestrator._adjudicator

    original_adjudicate = adjudicator.adjudicate

    async def traced_adjudicate(context):
        try:
            proposal = await original_adjudicate(context)
        except Exception as exc:
            transcript.write(
                "adjudicator_failed",
                step_index=context.step_index,
                semantic_goal=context.step.semantic_goal,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            raise
        transcript.write(
            "adjudicator_proposal",
            step_index=context.step_index,
            semantic_goal=context.step.semantic_goal,
            proposal=json.loads(proposal.model_dump_json(by_alias=True)),
        )
        return proposal

    monkeypatch.setattr(adjudicator, "adjudicate", traced_adjudicate)

    original_submit = adjudication_engine.submit

    async def traced_submit(request):
        try:
            return await original_submit(request)
        except Exception as exc:
            transcript.write(
                "engine_submit_rejected",
                request_id=request.adjudication.request_id,
                summary=request.adjudication.summary,
                error_type=type(exc).__name__,
                error=str(exc)[:800],
                adjudication=json.loads(request.adjudication.model_dump_json(by_alias=True)),
            )
            raise

    monkeypatch.setattr(adjudication_engine, "submit", traced_submit)


# --------------------------------------------------------------------------- #
# simulated player
# --------------------------------------------------------------------------- #

_PLAYER_INSTRUCTIONS = """\
你在扮演一名《克苏鲁的呼唤》7 版跑团的**玩家**（不是主持人）。
根据给出的最近场景描述，用第一人称写出你下一步想做的事。

严格要求：
- 只输出一句自然语言行动，像真人玩家在聊天框里打字，不要写规则术语、不要写骰子、
  不要写技能名，不要替主持人描述结果。
- 遵守 shape 字段：
  - "single"：只做一件事，一个动作。
  - "compound"：一句话里包含两到三个先后进行的动作，用"先……然后……"这种连接。
- 遵守 intent 字段给出的具体意图提示。
- 20 到 60 个汉字。
"""


class SimulatedPlayer:
    """Uses the configured model to author the next player utterance."""

    def __init__(self, client, transcript: Transcript) -> None:
        self._client = client
        self._transcript = transcript

    async def next_utterance(self, *, shape: str, intent: str, last_narration: str) -> str:
        raw = await self._client.generate(
            schema_name="trpg_sim_player_utterance",
            schema={
                "type": "object",
                "properties": {"utterance": {"type": "string"}},
                "required": ["utterance"],
                "additionalProperties": False,
            },
            instructions=_PLAYER_INSTRUCTIONS,
            input_payload={
                "shape": shape,
                "intent": intent,
                "last_narration": last_narration,
            },
        )
        utterance = str(raw["utterance"]).strip()
        assert utterance, "simulated player returned an empty utterance"
        self._transcript.write(
            "player_utterance",
            shape=shape,
            intent=intent,
            utterance=utterance,
        )
        return utterance


@pytest.fixture
def simulated_player(sim_settings: Settings, transcript: Transcript) -> SimulatedPlayer:
    return SimulatedPlayer(_structured_client(sim_settings), transcript)


# --------------------------------------------------------------------------- #
# websocket driver
# --------------------------------------------------------------------------- #

TERMINAL_TYPES = {"turn.failed", "error"}


@dataclass
class TurnOutcome:
    """Everything one submitted utterance produced, up to the next stop point."""

    stop: dict[str, Any]
    seen: list[dict[str, Any]] = field(default_factory=list)

    @property
    def kind(self) -> str:
        if self.stop.get("message_type") == "turn.completed":
            return "completed"
        return str(self.stop.get("type"))

    @property
    def narration_text(self) -> str:
        if self.kind != "completed":
            return ""
        return str(self.stop["payload"]["narration"]["text"])

    def of_type(self, message_type: str) -> list[dict[str, Any]]:
        return [
            message
            for message in self.seen
            if message.get("type") == message_type or message.get("message_type") == message_type
        ]


class PlaySession:
    """One joined, in-game player socket with transcript-backed helpers."""

    def __init__(self, ws, player_id: str, transcript: Transcript) -> None:
        self._ws = ws
        self.player_id = player_id
        self._transcript = transcript

    def send(self, event_type: str, payload: dict[str, Any]) -> None:
        self._transcript.write("send", event_type=event_type, payload=payload)
        self._ws.send_json({"type": event_type, "playerId": self.player_id, "payload": payload})

    def receive(self) -> dict[str, Any]:
        message = self._ws.receive_json()
        self._transcript.write(
            "recv",
            type=message.get("type") or message.get("message_type"),
            correlation_id=message.get("correlation_id")
            or message.get("payload", {}).get("correlationId"),
            payload=_summarize(message),
        )
        return message

    def drain_until_stop(self, *, limit: int = 60) -> TurnOutcome:
        """Read until the turn reaches a point where the player must act again.

        Stop points are the ones the UI actually reacts to: an authoritative
        ``turn.completed``, a pending check the player has to answer, or a
        failure/error envelope.
        """

        seen: list[dict[str, Any]] = []
        for _ in range(limit):
            message = self.receive()
            seen.append(message)
            message_type = message.get("type") or message.get("message_type")
            if message_type in {"turn.completed", "adjudication.pending", *TERMINAL_TYPES}:
                return TurnOutcome(stop=message, seen=seen)
        raise AssertionError(f"turn never reached a stop point; seen={_summarize_all(seen)}")

    def submit(self, utterance: str, *, client_action_id: str) -> TurnOutcome:
        self.send(
            "action.plan.submit",
            {"clientActionId": client_action_id, "utterance": utterance},
        )
        return self.drain_until_stop()

    def cancel_check(self, pending: dict[str, Any]) -> TurnOutcome:
        payload = pending["payload"]
        decision = payload["pendingDecision"]
        self.send(
            "adjudication.select",
            {
                "clientActionId": payload["correlationId"],
                "requestId": _request_id(),
                "sourceRevision": payload["sourceRevision"],
                "decisionId": decision["decision_id"],
                "decisionVersion": decision["decision_version"],
                "cancel": True,
            },
        )
        return self.drain_until_stop()

    def settle(self, outcome: TurnOutcome, *, limit: int = 6) -> TurnOutcome:
        """Answer every check the turn raises until it reaches a narration.

        A real player has to get through both halves of the check workflow: the
        skill choice, and — whenever the server roll fails — the post-roll
        decision. The simulated player always takes the first skill and then
        accepts the result, which is the one option every failed roll offers.
        """

        seen = list(outcome.seen)
        for _ in range(limit):
            if outcome.kind != "adjudication.pending":
                return TurnOutcome(stop=outcome.stop, seen=seen)
            status = outcome.stop["payload"]["status"]
            if status == "awaiting_skill_choice":
                outcome = self.select_skill(outcome.stop)
            elif status == "awaiting_post_roll_decision":
                outcome = self.accept_roll(outcome.stop)
            else:
                raise AssertionError(f"unexpected pending status {status!r}")
            seen += outcome.seen
        raise AssertionError("turn kept asking for check decisions past the scenario budget")

    def accept_roll(self, pending: dict[str, Any]) -> TurnOutcome:
        payload = pending["payload"]
        check_run = payload["checkRun"]
        accept = next(
            option for option in check_run["post_roll_options"] if option["kind"] == "accept_result"
        )
        self.send(
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
        return self.drain_until_stop()

    def select_skill(self, pending: dict[str, Any], index: int = 0) -> TurnOutcome:
        payload = pending["payload"]
        decision = payload["pendingDecision"]
        self.send(
            "adjudication.select",
            {
                "clientActionId": payload["correlationId"],
                "requestId": _request_id(),
                "sourceRevision": payload["sourceRevision"],
                "decisionId": decision["decision_id"],
                "decisionVersion": decision["decision_version"],
                "candidateId": decision["options"][index]["candidate_id"],
            },
        )
        return self.drain_until_stop()

    def cancel_plan(self, client_action_id: str) -> TurnOutcome:
        self.send(
            "action.plan.cancel",
            {"clientActionId": client_action_id, "requestId": _request_id()},
        )
        return self.drain_until_stop()


def _request_id() -> str:
    return f"sim-req-{uuid.uuid4().hex[:12]}"


def _action_id(label: str) -> str:
    return f"sim-{label}-{uuid.uuid4().hex[:8]}"


def _summarize(message: dict[str, Any]) -> Any:
    """Keep the transcript readable without dropping anything diagnostic."""

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return payload
    trimmed = dict(payload)
    view = trimmed.pop("player_view", None)
    if isinstance(view, dict):
        trimmed["player_view_revision"] = view.get("revision")
        trimmed["player_view_scene"] = view.get("scene_id")
    return trimmed


def _summarize_all(messages: list[dict[str, Any]]) -> list[Any]:
    return [(message.get("type") or message.get("message_type")) for message in messages]


@pytest.fixture
def play_session(transcript: Transcript, real_model_ws: None):
    """Register, build a character, start the game, and hand back a live socket."""

    client = TestClient(app)
    account = f"sim_{uuid.uuid4().hex[:8]}"
    token = register_and_login(client, account)
    room = create_room(client, token)
    advance_to_building(client, room)
    complete_character(client, room["roomId"], room["reconnectToken"])
    start_game(client, room, token)
    transcript.write("room_ready", room_id=room["roomId"], player_id=room["playerId"])

    with client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        session = PlaySession(ws, room["playerId"], transcript)
        session.send("room.join", {"reconnectToken": room["reconnectToken"]})
        session.receive()  # session.bound
        session.receive()  # view.updated
        opening = receive_replayed_opening(ws)
        session.opening_text = opening["payload"]["text"]  # type: ignore[attr-defined]
        yield session


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #


async def test_single_intent_plays_through(
    play_session: PlaySession,
    simulated_player: SimulatedPlayer,
    transcript: Transcript,
) -> None:
    utterance = await simulated_player.next_utterance(
        shape="single",
        intent="向面前的委托人打听一个具体细节",
        last_narration=play_session.opening_text,  # type: ignore[attr-defined]
    )
    action_id = _action_id("single")
    outcome = play_session.submit(utterance, client_action_id=action_id)

    # A single intent may still need one check; answer it so the turn settles.
    outcome = play_session.settle(outcome)

    assert outcome.kind == "completed", _summarize_all(outcome.seen)
    assert outcome.stop["correlation_id"] == action_id
    assert outcome.narration_text.strip()
    assert not outcome.of_type("turn.failed")
    transcript.write("scenario_ok", scenario="single_intent", narration=outcome.narration_text)


async def test_multi_intent_runs_as_one_plan(
    play_session: PlaySession,
    simulated_player: SimulatedPlayer,
    transcript: Transcript,
) -> None:
    """A compound utterance must run every step of one plan and settle once.

    The planner is free to read a compound sentence as a single action, so the
    scenario retries a few phrasings until it actually gets a plan; only then is
    the multi-step path under test.
    """

    action_id = ""
    outcome: TurnOutcome | None = None
    progress: list[dict[str, Any]] = []
    for attempt in range(3):
        utterance = await simulated_player.next_utterance(
            shape="compound",
            intent="先在会客室里观察一样眼前确实存在的东西，然后就它向委托人提问",
            last_narration=play_session.opening_text,  # type: ignore[attr-defined]
        )
        action_id = _action_id(f"multi{attempt}")
        outcome = play_session.submit(utterance, client_action_id=action_id)
        outcome = play_session.settle(outcome)
        progress = outcome.seen

        assert outcome.kind == "completed", _summarize_all(outcome.seen)
        if any(message.get("type") == "plan.started" for message in progress):
            break
        transcript.write("note", detail=f"attempt {attempt} was planned as a single action")

    assert outcome is not None
    started = [message for message in progress if message.get("type") == "plan.started"]
    assert started, "planner never produced an ActionPlan for a compound utterance"
    total_steps = started[0]["payload"]["totalSteps"]
    stopped = [message for message in progress if message.get("type") == "plan.stopped"]
    completed_steps = [
        message
        for message in progress
        if message.get("type") == "plan.step_changed" and message["payload"]["phase"] == "completed"
    ]

    assert not stopped, f"plan stopped early: {[m['payload']['safeReason'] for m in stopped]}"
    assert len(completed_steps) == total_steps
    assert outcome.stop["correlation_id"] == action_id
    assert outcome.narration_text.strip()
    assert not outcome.of_type("turn.failed")
    transcript.write(
        "scenario_ok",
        scenario="multi_intent",
        total_steps=total_steps,
        narration=outcome.narration_text,
    )


async def test_player_can_cancel_a_check_before_the_roll(
    play_session: PlaySession,
    simulated_player: SimulatedPlayer,
    transcript: Transcript,
) -> None:
    """The "cancel" button on the dice/skill panel must settle the turn."""

    pending: dict[str, Any] | None = None
    action_id = ""
    for attempt in range(3):
        utterance = await simulated_player.next_utterance(
            shape="single",
            intent=(
                "尝试一件明显有难度、需要靠本事才能成功的事，比如强行说服、撬开、翻找隐藏的东西"
            ),
            last_narration=play_session.opening_text,  # type: ignore[attr-defined]
        )
        action_id = _action_id(f"cancelcheck{attempt}")
        outcome = play_session.submit(utterance, client_action_id=action_id)
        if outcome.kind == "adjudication.pending":
            pending = outcome.stop
            break
        assert outcome.kind == "completed", _summarize_all(outcome.seen)
        transcript.write("note", detail=f"attempt {attempt} produced no check; retrying")

    if pending is None:
        pytest.skip("model never proposed a check in 3 attempts; cancel path not exercised")

    assert pending["payload"]["status"] == "awaiting_skill_choice"
    cancelled = play_session.cancel_check(pending)

    assert cancelled.kind == "completed", _summarize_all(cancelled.seen)
    assert cancelled.stop["correlation_id"] == action_id
    assert cancelled.narration_text.strip()
    assert not cancelled.of_type("turn.failed")
    transcript.write(
        "scenario_ok",
        scenario="cancel_check",
        plan_id=pending["payload"].get("planId"),
        narration=cancelled.narration_text,
    )

    # The room must accept a fresh action immediately after a cancel.
    follow_up = await simulated_player.next_utterance(
        shape="single",
        intent="换一个更简单的做法继续调查",
        last_narration=cancelled.narration_text,
    )
    resumed = play_session.settle(
        play_session.submit(follow_up, client_action_id=_action_id("aftercancel"))
    )
    assert resumed.kind == "completed", _summarize_all(resumed.seen)
    transcript.write("scenario_ok", scenario="action_after_cancel")


async def test_player_can_cancel_the_remaining_plan_steps(
    play_session: PlaySession,
    simulated_player: SimulatedPlayer,
    transcript: Transcript,
) -> None:
    """`action.plan.cancel` at a waiting boundary keeps committed steps and stops."""

    utterance = await simulated_player.next_utterance(
        shape="compound",
        intent=(
            "先做一件需要靠本事才能成功的难事（比如强行说服或翻找隐藏的东西），"
            "然后再去另一个地方查线索"
        ),
        last_narration=play_session.opening_text,  # type: ignore[attr-defined]
    )
    action_id = _action_id("plancancel")
    outcome = play_session.submit(utterance, client_action_id=action_id)

    if outcome.kind == "adjudication.pending":
        assert outcome.stop["payload"].get("planId"), (
            "expected the pending check to belong to the plan run"
        )
        cancelled = play_session.cancel_plan(action_id)
    elif outcome.kind == "completed":
        pytest.skip("plan settled without a waiting boundary; nothing to cancel")
    else:
        pytest.fail(f"unexpected stop {outcome.kind}: {_summarize_all(outcome.seen)}")

    assert cancelled.kind == "completed", _summarize_all(cancelled.seen)
    assert cancelled.stop["correlation_id"] == action_id
    assert cancelled.narration_text.strip()
    assert not cancelled.of_type("turn.failed")
    transcript.write(
        "scenario_ok",
        scenario="cancel_plan",
        narration=cancelled.narration_text,
    )

    follow_up = await simulated_player.next_utterance(
        shape="single",
        intent="放弃刚才的计划，换一件简单的事做",
        last_narration=cancelled.narration_text,
    )
    resumed = play_session.settle(
        play_session.submit(follow_up, client_action_id=_action_id("afterplancancel"))
    )
    assert resumed.kind == "completed", _summarize_all(resumed.seen)
    transcript.write("scenario_ok", scenario="action_after_plan_cancel")
