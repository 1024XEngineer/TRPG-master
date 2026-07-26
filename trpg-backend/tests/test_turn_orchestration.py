from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from collaboration_framework.contracts import ContractError
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


def application(host_agent, narration_model):
    module = load_paper_chase()
    state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    app = build_turn_application(
        store,
        RuleEngineService(store),
        host_agent=host_agent,
        narration_model=narration_model,
    )
    return app, store, state


@pytest.mark.asyncio
async def test_narrator_failure_retries_without_rerunning_host_or_state_change() -> None:
    host = CountingHostAgent()
    narration = FailOnceNarration()
    app, store, state = application(host, narration)

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
    assert store.inspect_state(state.room_id).event_sequence == 0


@pytest.mark.asyncio
async def test_invisible_target_fails_before_authoritative_engine_boundary() -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, store, state = application(host, FakeNarrationModel())

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
    app, _, state = application(host, FakeNarrationModel())

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
