from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from collaboration_framework.contracts import ContractError, player_input_fingerprint
from collaboration_framework.engine import InMemoryEngineStore, RuleEngineService
from collaboration_framework.host.adapters.fakes import FakeNarrationModel
from collaboration_framework.host.application import TurnExecutionError
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentUsage,
    NarrationContext,
)
from structlog.testing import capture_logs

from app.core.turn import build_turn_application
from tests.test_openai_models import conversation_state, load_paper_chase

SECRET_SENTINEL = "SECRET_SENTINEL_DO_NOT_LEAK"


class CountingHostAgent:
    def __init__(self, *, target_id: str | None = None) -> None:
        self.calls = 0
        self.target_id = target_id

    async def astream(
        self,
        context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]:
        self.calls += 1
        target_id = self.target_id or context.player_view.scene.visible_entities[0].id
        yield HostAgentCompleted(
            type="agent.completed",
            raw_output={
                "kind": "dialogue",
                "verb": "talk",
                "target": {"matched": True, "id": target_id},
                "check": {"route": "none"},
                "summary": context.player_input.utterance,
            },
            usage=HostAgentUsage(
                model_rounds=1,
                tool_calls=0,
                input_tokens=12,
                output_tokens=4,
                duration_ms=3,
                termination_reason="completed",
            ),
        )


class FailOnceNarration:
    def __init__(self) -> None:
        self.calls = 0
        self._fake = FakeNarrationModel()

    async def generate(self, context: NarrationContext):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("provider timeout")
        return await self._fake.generate(context)


class CountingEngine(RuleEngineService):
    def __init__(self, store: InMemoryEngineStore) -> None:
        super().__init__(store)
        self.read_calls = 0
        self.execute_calls = 0

    async def read(self, player_input):
        self.read_calls += 1
        return await super().read(player_input)

    async def execute(self, request):
        self.execute_calls += 1
        return await super().execute(request)


class InvalidThenSafeNarration:
    leaked_text = "托马斯看着你。 claimed_fact_ids: [],"

    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[NarrationContext] = []
        self._fake = FakeNarrationModel()

    async def generate(self, context: NarrationContext):
        self.calls += 1
        self.contexts.append(context)
        if self.calls == 1:
            return {
                "kind": "narration",
                "text": self.leaked_text,
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        return await self._fake.generate(context)


class InvalidTwiceThenSafeNarration(InvalidThenSafeNarration):
    async def generate(self, context: NarrationContext):
        self.calls += 1
        self.contexts.append(context)
        if self.calls <= 2:
            return {
                "kind": "narration",
                "text": self.leaked_text,
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        return await self._fake.generate(context)


class InvalidThenTimeoutNarration(InvalidThenSafeNarration):
    async def generate(self, context: NarrationContext):
        self.calls += 1
        self.contexts.append(context)
        if self.calls == 1:
            return {
                "kind": "narration",
                "text": self.leaked_text,
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        raise TimeoutError("provider timeout")


def application(host_agent, narration_model):
    module = load_paper_chase()
    state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = CountingEngine(store)
    app = build_turn_application(
        store,
        engine,
        host_agent=host_agent,
        narration_model=narration_model,
    )
    return app, store, state, engine


@pytest.mark.asyncio
async def test_narrator_failure_retries_without_rerunning_host_or_state_change() -> None:
    host = CountingHostAgent()
    narration = FailOnceNarration()
    app, store, state, engine = application(host, narration)

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narrator-retry",
        utterance="我询问托马斯藏书的情况",
    )
    with pytest.raises(TurnExecutionError) as failed:
        await app.complete(prepared)
    assert failed.value.code == "NARRATOR_FAILED"
    assert store.inspect_completed_action(state.room_id, "narrator-retry") is not None

    replayed = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narrator-retry",
        utterance="我询问托马斯藏书的情况",
    )
    output = await app.complete(replayed)

    assert output.player_input.client_action_id == "narrator-retry"
    assert host.calls == 1
    assert narration.calls == 2
    assert engine.execute_calls == 1
    assert store.inspect_state(state.room_id).event_sequence == 0


@pytest.mark.asyncio
async def test_invalid_narration_is_retried_once_with_same_safe_context() -> None:
    host = CountingHostAgent()
    narration = InvalidThenSafeNarration()
    app, _, state, engine = application(host, narration)

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narration-auto-retry",
        utterance="我询问托马斯藏书的情况",
    )
    with capture_logs() as logs:
        output = await app.complete(prepared)

    assert output.narration.text != narration.leaked_text
    assert narration.calls == 2
    assert narration.contexts[0] is narration.contexts[1]
    assert host.calls == 1
    assert engine.execute_calls == 1
    encoded = json.dumps(logs, ensure_ascii=False)
    assert narration.leaked_text not in encoded
    assert "narration_validation_rejected" in encoded
    assert '"attempt": 1' in encoded
    assert '"will_retry": true' in encoded


@pytest.mark.asyncio
async def test_two_invalid_narrations_fail_closed_and_manual_retry_skips_executor() -> None:
    host = CountingHostAgent()
    narration = InvalidTwiceThenSafeNarration()
    app, store, state, engine = application(host, narration)
    action_result_calls = 0

    async def record_action_result(_):
        nonlocal action_result_calls
        action_result_calls += 1

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narration-manual-retry",
        utterance="我询问托马斯藏书的情况",
    )
    with capture_logs() as logs, pytest.raises(TurnExecutionError) as failed:
        await app.complete(prepared, on_action_result=record_action_result)

    assert failed.value.code == "NARRATION_INVALID"
    assert failed.value.retryable is True
    assert narration.calls == 2
    assert host.calls == 1
    assert engine.execute_calls == 1
    assert action_result_calls == 1
    assert store.inspect_completed_action(state.room_id, "narration-manual-retry") is not None
    encoded = json.dumps(logs, ensure_ascii=False)
    assert narration.leaked_text not in encoded
    assert '"attempt": 2' in encoded
    assert '"will_retry": false' in encoded

    replayed = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narration-manual-retry",
        utterance="我询问托马斯藏书的情况",
    )
    output = await app.complete(replayed, on_action_result=record_action_result)

    assert output.player_input.client_action_id == "narration-manual-retry"
    assert narration.calls == 3
    assert host.calls == 1
    assert engine.execute_calls == 1
    assert action_result_calls == 1


@pytest.mark.asyncio
async def test_completed_action_rejects_same_id_with_different_player_input() -> None:
    host = CountingHostAgent()
    narration = InvalidTwiceThenSafeNarration()
    app, store, state, engine = application(host, narration)

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narration-conflicting-retry",
        utterance="我询问托马斯藏书的情况",
    )
    with pytest.raises(TurnExecutionError, match="叙事未通过安全校验"):
        await app.complete(prepared)

    completed = store.inspect_completed_action(
        state.room_id,
        "narration-conflicting-retry",
    )
    assert completed.request.input_fingerprint == player_input_fingerprint(prepared.player_input)

    with pytest.raises(ContractError, match="request_id 已用于不同"):
        await app.prepare(
            room_id=state.room_id,
            player_id="player_1",
            client_action_id="narration-conflicting-retry",
            utterance="我攻击托马斯",
        )

    assert host.calls == 1
    assert engine.execute_calls == 1
    assert narration.calls == 2


@pytest.mark.asyncio
async def test_provider_failure_after_invalid_retry_maps_to_narrator_failed() -> None:
    host = CountingHostAgent()
    narration = InvalidThenTimeoutNarration()
    app, _, state, engine = application(host, narration)

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="narration-invalid-then-timeout",
        utterance="我询问托马斯藏书的情况",
    )
    with pytest.raises(TurnExecutionError) as failed:
        await app.complete(prepared)

    assert failed.value.code == "NARRATOR_FAILED"
    assert narration.calls == 2
    assert host.calls == 1
    assert engine.execute_calls == 1


@pytest.mark.asyncio
async def test_invisible_target_fails_before_authoritative_engine_boundary() -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, store, state, _ = application(host, FakeNarrationModel())

    with pytest.raises(TurnExecutionError) as failed:
        await app.prepare(
            room_id=state.room_id,
            player_id="player_1",
            client_action_id="invalid-target",
            utterance="调查秘密目标",
        )

    assert failed.value.code == "HOST_AGENT_INVALID_OUTPUT"
    assert host.calls == 1
    with pytest.raises(ContractError, match="动作尚未执行"):
        store.inspect_completed_action(state.room_id, "invalid-target")
    assert store.inspect_state(state.room_id).event_sequence == 0


@pytest.mark.asyncio
async def test_host_observability_is_metadata_only_and_records_rejection_code() -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, _, state, _ = application(host, FakeNarrationModel())

    with capture_logs() as logs, pytest.raises(TurnExecutionError):
        await app.prepare(
            room_id=state.room_id,
            player_id="player_1",
            client_action_id="safe-observability",
            utterance=SECRET_SENTINEL,
        )

    encoded = json.dumps(logs, ensure_ascii=False)
    assert SECRET_SENTINEL not in encoded
    assert "module-secret-entity" not in encoded
    assert "HOST_AGENT_INVALID_OUTPUT" in encoded
    assert "safe-observability" in encoded
