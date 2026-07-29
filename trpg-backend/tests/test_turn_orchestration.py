from __future__ import annotations

import json
import logging
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
    RecentTurnContext,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.adapters import SqlAlchemyRecentHistorySource
from app.core.config import Settings
from app.core.turn import build_turn_application
from app.models.event import Event
from app.models.room import Player, Room
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


class CapturingHistoryHost(CountingHostAgent):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[HostAgentContext] = []

    async def astream(self, context: HostAgentContext) -> AsyncIterator[HostAgentEvent]:
        self.contexts.append(context)
        async for event in super().astream(context):
            yield event


class InvalidHistorySource:
    async def read(self, *, player_input, player_view, **_):  # noqa: ANN001
        return RecentTurnContext.model_construct(
            room_id=player_input.room_id,
            viewer_player_id="another-player",
            as_of_revision=player_view.revision,
            turns=(),
        )


class UnavailableHistorySource:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self, **_):  # noqa: ANN003
        self.calls += 1
        raise OperationalError("SELECT recent history", {}, Exception("offline"))


class PaperChaseHistoryHost(CountingHostAgent):
    def __init__(self) -> None:
        super().__init__(target_id="thomas")
        self.contexts: list[HostAgentContext] = []

    async def astream(self, context: HostAgentContext) -> AsyncIterator[HostAgentEvent]:
        self.contexts.append(context)
        self.calls += 1
        if context.player_input.utterance == "是的":
            previous = context.recent_history.turns[-1]
            summary = "确认上一轮关于五本书是否都被叔叔带走的问题"
            assert "五本书" in previous.player_utterance.text
            assert previous.published_narration is not None
            assert "确定" in previous.published_narration.text
        else:
            summary = context.player_input.utterance
        yield HostAgentCompleted(
            type="agent.completed",
            raw_output={
                "kind": "dialogue",
                "verb": "talk",
                "target": {"matched": True, "id": "thomas"},
                "check": {"route": "none"},
                "summary": summary,
            },
            usage=HostAgentUsage(
                model_rounds=1,
                tool_calls=0,
                duration_ms=1,
                termination_reason="completed",
            ),
        )


class PaperChaseHistoryNarration:
    def __init__(self) -> None:
        self.contexts: list[NarrationContext] = []

    async def generate(self, context: NarrationContext):
        self.contexts.append(context)
        if "五本书" in context.player_input.utterance:
            text = "托马斯皱起眉头：你确定五本书都被叔叔一起带走了吗？"
        elif context.player_input.utterance == "是的":
            text = "托马斯缓缓点头，把这项说法记了下来。"
        else:
            text = "托马斯安静地听着，没有把你的说法当作既定事实。"
        return {
            "kind": "narration",
            "text": text,
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


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


class AlwaysFailNarration:
    async def generate(self, context: NarrationContext):
        raise TimeoutError("provider timeout")


class AlwaysNarration:
    async def generate(self, context: NarrationContext):
        return {
            "kind": "narration",
            "text": "错误地把恢复回合当成普通叙事。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


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
async def test_invalid_recent_history_fails_before_host_and_executor() -> None:
    host = CapturingHistoryHost()
    module = load_paper_chase()
    state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = CountingEngine(store)
    app = build_turn_application(
        store,
        engine,
        host_agent=host,
        narration_model=FakeNarrationModel(),
        recent_history_source=InvalidHistorySource(),
    )

    with pytest.raises(TurnExecutionError) as failed:
        await app.prepare(
            room_id=state.room_id,
            player_id="player_1",
            client_action_id="invalid-history",
            utterance="继续",
        )

    assert failed.value.code == "RECENT_HISTORY_INVALID"
    assert host.calls == 0
    assert engine.execute_calls == 0


@pytest.mark.asyncio
async def test_unavailable_recent_history_degrades_to_empty_single_turn_flow() -> None:
    host = CapturingHistoryHost()
    source = UnavailableHistorySource()
    module = load_paper_chase()
    state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = CountingEngine(store)
    app = build_turn_application(
        store,
        engine,
        host_agent=host,
        narration_model=FakeNarrationModel(),
        recent_history_source=source,
    )

    output = await app.handle(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="degraded-history",
        utterance="我询问托马斯",
    )

    assert output.correlation_id == "degraded-history"
    assert source.calls == 1
    assert host.contexts[0].recent_history.turns == ()
    assert engine.execute_calls == 1


@pytest.mark.asyncio
async def test_disabled_recent_history_keeps_required_empty_contract_without_reading() -> None:
    host = CapturingHistoryHost()
    source = UnavailableHistorySource()
    module = load_paper_chase()
    state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = CountingEngine(store)
    app = build_turn_application(
        store,
        engine,
        settings=Settings(recent_history_enabled=False),
        host_agent=host,
        narration_model=FakeNarrationModel(),
        recent_history_source=source,
    )

    await app.handle(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="disabled-history",
        utterance="我询问托马斯",
    )

    assert source.calls == 0
    assert host.contexts[0].recent_history.turns == ()


@pytest.mark.asyncio
async def test_paper_chase_three_turn_recent_continuity_uses_published_history(
    db_session: AsyncSession,
    recent_history_source: SqlAlchemyRecentHistorySource,
) -> None:
    room_id = "80000000-0000-0000-0000-000000000001"
    player_id = "80000000-0000-0000-0000-000000000002"
    db_session.add(Room(id=room_id, room_code="RH0170", room_name="追书人历史", max_players=1))
    db_session.add(
        Player(
            id=player_id,
            room_id=room_id,
            nickname="调查员",
            reconnect_token="80000000-0000-0000-0000-000000000012",
        )
    )
    await db_session.commit()

    module = load_paper_chase()
    original_state = conversation_state(module).model_copy(update={"scene_id": "client_briefing"})
    actor = original_state.actors["actor_1"].model_copy(update={"player_id": player_id})
    state = original_state.model_copy(update={"room_id": room_id, "actors": {"actor_1": actor}})
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = CountingEngine(store)
    host = PaperChaseHistoryHost()
    narration = PaperChaseHistoryNarration()
    app = build_turn_application(
        store,
        engine,
        host_agent=host,
        narration_model=narration,
        recent_history_source=recent_history_source,
    )

    async def persist_action(player_input, player_view):  # noqa: ANN001
        db_session.add(
            Event(
                room_id=room_id,
                player_id=player_id,
                event_type="action.broadcast",
                correlation_id=player_input.client_action_id,
                visibility="public",
                actor_id=player_input.actor_id,
                scene_id=player_view.scene_id,
                view_revision=player_view.revision,
                payload={"utterance": player_input.utterance},
            )
        )
        await db_session.commit()

    utterances = (
        "我告诉托马斯，叔叔去了很远的地方",
        "五本书被叔叔一起带走",
        "是的",
    )
    outputs = []
    for index, utterance in enumerate(utterances, start=1):
        prepared = await app.prepare(
            room_id=room_id,
            player_id=player_id,
            client_action_id=f"paper-chase-{index}",
            utterance=utterance,
            on_input_accepted=persist_action,
        )
        output = await app.complete(prepared)
        outputs.append(output)
        db_session.add(
            Event(
                room_id=room_id,
                player_id=player_id,
                event_type="narration.push",
                correlation_id=prepared.player_input.client_action_id,
                visibility="public",
                actor_id=prepared.player_input.actor_id,
                scene_id=output.player_view.scene_id,
                view_revision=output.player_view.revision,
                payload={"text": output.narration.text},
            )
        )
        await db_session.commit()

    assert [turn.player_utterance.text for turn in host.contexts[1].recent_history.turns] == [
        utterances[0]
    ]
    assert [turn.player_utterance.text for turn in host.contexts[2].recent_history.turns] == list(
        utterances[:2]
    )
    assert host.contexts[2].recent_history.turns[-1].published_narration is not None
    assert outputs[2].intent.kind == "dialogue"
    assert outputs[2].intent.summary.startswith("确认上一轮")
    assert "确定五本书" not in outputs[2].narration.text
    assert engine.execute_calls == 3
    known_information = json.dumps(
        [item.to_json_dict() for item in outputs[2].player_view.known_information],
        ensure_ascii=False,
    )
    assert "叔叔去了很远的地方" not in known_information
    assert "五本书被叔叔一起带走" not in known_information


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

    async def record_action_result(_, __):
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
async def test_invisible_target_becomes_state_free_clarification() -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, store, state = application(host, AlwaysFailNarration())

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="invalid-target",
        utterance="调查秘密目标",
    )
    output = await app.complete(prepared)

    assert output.intent.kind == "unknown"
    assert output.action_result.resolution == "unrecognized"
    assert output.status == "clarification"
    assert output.narration.kind == "clarification"
    assert host.calls == 1
    assert store.inspect_completed_action(state.room_id, "invalid-target") is not None
    assert store.inspect_state(state.room_id).event_sequence == 0


@pytest.mark.asyncio
async def test_recovered_intent_forces_deterministic_clarification() -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, _, state = application(host, AlwaysNarration())

    prepared = await app.prepare(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="forced-clarification",
        utterance="调查秘密目标",
    )
    output = await app.complete(prepared)

    assert output.intent.kind == "unknown"
    assert output.action_result.resolution == "unrecognized"
    assert output.status == "clarification"
    assert output.narration.kind == "clarification"
    assert output.narration.text == "你想对当前场景中的哪个人物、物品或地点做什么？"
    assert output.narration.suggested_actions


@pytest.mark.asyncio
async def test_host_observability_records_recovery_without_leaking_model_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = CountingHostAgent(target_id="module-secret-entity")
    app, _, state, _ = application(host, FakeNarrationModel())

    with caplog.at_level(logging.WARNING):
        await app.handle(
            room_id=state.room_id,
            player_id="player_1",
            client_action_id="safe-observability",
            utterance=SECRET_SENTINEL,
        )

    encoded = caplog.text
    assert SECRET_SENTINEL not in encoded
    assert "module-secret-entity" not in encoded
    assert "host_agent_intent_recovered" in encoded
    recovery_records = [
        record for record in caplog.records if record.message == "host_agent_intent_recovered"
    ]
    assert recovery_records
    assert getattr(recovery_records[-1], "failure_reason", "") == "target_not_visible_or_ambiguous"
    assert getattr(recovery_records[-1], "recovery_path", "") == "unknown_intent_clarification"
