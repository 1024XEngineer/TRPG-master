"""C-stage acceptance through the real rule engine and durable SQL plan/queue stores."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    CancelCheckChoice,
    CheckDecisionRequest,
    ContractError,
    EnterLocationEffect,
    ModuleContentV3,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    RuleEngineService,
    SequenceDiceSource,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import ActorState
from collaboration_framework.host.application import ActionPlanNarrator, TurnExecutionError
from collaboration_framework.host.schemas.action_plan import ActionPlanNpcReply
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters import SqlAlchemyActionPlanRunStore, SqlAlchemyEngineStore
from app.adapters.sqlalchemy_memory import SqlAlchemyMemoryStore
from app.controller import ws
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.core.host_entry import HostEntryContext, HostEntryRouter, HostPublicContext
from app.core.host_rule_loop import new_rule_loop, rule_loop_id
from app.core.turn import build_session_view_application
from app.dto.ws import (
    ActionRecipientPayload,
    SceneTransitionPendingPayload,
    TimeAdvancePendingPayload,
)
from app.models.engine import GameSession, ModuleVersion
from app.models.event import Event
from app.service import host_action_queue as queue
from tests.test_engine_runtime import _start_room
from tests.test_rule_match_adjudication import _content


class WorkerCrash(BaseException):
    """Simulate process loss, bypassing normal exception-to-retry handling."""


def _rule(rule_id: str, state_key: str) -> dict:
    return {
        "id": rule_id,
        "trigger": {
            "kind": "agent_match",
            "scope": {
                "location_ids": ["cemetery"],
                "target_kinds": ["entity"],
                "target_ids": ["cemetery_figure"],
            },
            "question": {"kind": "action_declaration", "semantic_hints": [rule_id]},
            "options": [{"id": "continue", "semantic_hints": ["继续交谈"]}],
        },
        "execution": {
            "branches": [{"id": "continue", "entry_step_id": "effect"}],
            "steps": [
                {
                    "id": "effect",
                    "kind": "effect",
                    "effect": {
                        "type": "change_entity_state",
                        "entity_id": "cemetery_figure",
                        "key": state_key,
                        "value": True,
                    },
                    "next_step_id": "finish",
                },
                {"id": "finish", "kind": "finish"},
            ],
        },
    }


async def _runtime(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    plan_store_factory: Callable[[], SqlAlchemyActionPlanRunStore],
    *,
    action_id: str = "composite-real-engine",
    clarification: bool = False,
    check_step: int | None = None,
    consent_kind: str | None = None,
):
    room, players, characters = await _start_room(
        db, room_number=4895, player_count=2, prepare_checkpoint=False
    )
    room_id, player_id, actor_id = room.id, players[0].id, characters[0].id
    raw = _content().to_json_dict()
    for entity in raw["entities"]:
        if entity["id"] == "cemetery_figure":
            entity["located_in"] = "cemetery"
    raw["rules"] = [
        _rule("greet_caretaker", "willing_to_talk"),
        _rule("ask_caretaker", "truth_told"),
    ]
    if check_step is not None:
        execution = raw["rules"][check_step]["execution"]
        execution["branches"][0]["entry_step_id"] = "check"
        execution["steps"].append(
            {
                "id": "check",
                "kind": "check",
                "check": {
                    "profile_id": "coc7.skill",
                    "actor_binding": "actor",
                    "initiation_kind": "active_action",
                    "parameters": {"skill_id": "spot-hidden"},
                    "difficulty": "regular",
                },
                "result_routes": {
                    "critical_success": "effect",
                    "extreme_success": "effect",
                    "hard_success": "effect",
                    "regular_success": "effect",
                    "failure": "finish",
                    "fumble": "finish",
                },
            }
        )
    session = await db.get(GameSession, room_id)
    assert session is not None
    raw["module_id"], raw["version"] = session.module_id, session.module_version
    content = ModuleContentV3.model_validate(raw)
    state = create_initial_game_state(
        content,
        room_id=room_id,
        actors={
            character.id: ActorState(
                player_id=player.id,
                name="调查员",
                source_character_id=character.id,
                source_character_version=1,
                state={"skills": {"spot-hidden": 60}},
            )
            for player, character in zip(players, characters, strict=True)
        },
    ).model_copy(update={"scene_id": "cemetery"}, deep=True)
    module = await db.get(ModuleVersion, (session.module_id, session.module_version))
    assert module is not None
    module.content_json = content.to_json_dict()
    session.state_json = state.to_json_dict()
    session.state_version = state.event_sequence
    await db.commit()
    assert db.bind is not None
    session_factory = async_sessionmaker(db.bind, expire_on_commit=False)
    store = SqlAlchemyEngineStore(session_factory)
    settings = Settings(host_model_provider="fake", opening_narration_mode="template")
    engine = RuleEngineService(store)
    monkeypatch.setattr(
        ws,
        "session_view_application",
        build_session_view_application(store, engine, settings=settings),
    )

    def restart():
        restarted_store = SqlAlchemyEngineStore(session_factory)
        restarted_engine = RuleEngineService(restarted_store)
        adjudication = AdjudicationEngineService(
            restarted_store, dice=DiceRoller(SequenceDiceSource([95]))
        )
        monkeypatch.setattr(ws, "adjudication_engine_service", adjudication)
        app = build_action_plan_turn_application(
            store=restarted_store,
            engine=restarted_engine,
            adjudication_engine=adjudication,
            plan_store=plan_store_factory(),
            settings=settings,
            time_consent_session_factory=session_factory,
            memory_source=SqlAlchemyMemoryStore(session_factory),
        )
        monkeypatch.setattr(ws, "action_plan_turn_application", app)
        return app

    if consent_kind is not None:
        # Inject a valid consent-requiring consequence at the rule builder
        # boundary. Authored module effects have their own authority policy;
        # this test covers the loop's shared Engine/SQL consent protocol.
        original_builder = ws.build_rule_once_adjudication

        def build_waiting_consequence(**kwargs):
            adjudication = original_builder(**kwargs)
            if kwargs["rule_id"] != "ask_caretaker":
                return adjudication
            is_time = consent_kind == "time"
            return ActionAdjudication(
                request_id=adjudication.request_id,
                source_revision=adjudication.source_revision,
                actor_id=adjudication.actor_id,
                summary="等待到下一个时间点" if is_time else "前往阿诺兹堡街道",
                persistence_intent="none" if is_time else "location",
                target=ActionTarget(
                    kind="world" if is_time else "location",
                    id=content.world_ref if is_time else "arnoldsburg_streets",
                ),
                method=ActionMethod(family="wait" if is_time else "travel", description="继续行动"),
                check=NoAdjudicationCheck(),
                success_effects=(
                    AdvanceWorldTimeEffect()
                    if is_time
                    else EnterLocationEffect(location_id="arnoldsburg_streets"),
                ),
            )

        monkeypatch.setattr(ws, "build_rule_once_adjudication", build_waiting_consequence)

    app = restart()
    contexts: list[HostEntryContext] = []

    class Model:
        async def generate(self, context: HostPublicContext | HostEntryContext):
            assert isinstance(context, HostEntryContext)
            public = context.public
            assert public.rule_loop_active
            contexts.append(context)
            index = public.loop_step_index
            assert len(public.completed_rule_feedback) == index
            if index:
                # The next model call sees the committed state AND a durable
                # public feedback event for the immediately preceding rule.
                current = await _state(store, room_id)
                assert current.entities["cemetery_figure"]["willing_to_talk"] is True
                event = await ws.room_service.get_correlated_event(
                    db, room_id, "narration.push", rule_loop_id(action_id, "step", index - 1)
                )
                assert event is not None
                assert event.payload["text"] == public.completed_rule_feedback[-1]
            if index == 1 and clarification and not public.player_answer:
                return {"route": "needs_clarification", "text": "接下来想问哪件事？"}
            if index < 2:
                return {
                    "route": "rule_once",
                    "rule_id": "greet_caretaker" if index == 0 else "ask_caretaker",
                    "option_id": "continue",
                    "target_kind": "entity",
                    "target_id": "cemetery_figure",
                    "summary": "和看守交谈",
                }
            return {"route": "direct_response", "text": "就先聊到这里。"}

    monkeypatch.setattr(ws, "_host_entry_router", HostEntryRouter(Model()))
    # Tests drive the drain explicitly; avoid background workers racing fixture teardown.
    monkeypatch.setattr(ws, "schedule_host_action_drain", lambda room_id: None)
    item, _ = await queue.enqueue(
        db,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id=action_id,
        utterance="先和看守打招呼，再询问他的往事",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    await queue.save_execution_route(db, item, route="composite_rule", text=None, provenance="test")
    await queue.save_rule_loop(
        db, item, new_rule_loop(client_action_id=action_id, player_id=player_id, actor_id=actor_id)
    )
    claimed = await queue.claim(db, item, recipient_kind="keeper")
    assert claimed is not None
    return store, claimed, app, contexts, restart


async def _state(store: SqlAlchemyEngineStore, room_id: str):
    async with store.transaction(room_id) as transaction:
        return (await transaction.load_runtime()).game_state


async def _events(db: AsyncSession, room_id: str):
    return list(
        (
            await db.scalars(
                select(Event)
                .where(Event.room_id == room_id, Event.event_type == "narration.push")
                .order_by(Event.created_at, Event.id)
            )
        ).all()
    )


async def test_real_rules_refresh_revision_and_feedback_before_next_decision(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    store, item, _, contexts, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed"
    assert len(contexts) == 3
    revisions = [context.rule_match.source_revision for context in contexts if context.rule_match]
    assert len(revisions) == 3 and len(set(revisions)) == 3
    assert (await _state(store, item.room_id)).entities["cemetery_figure"]["truth_told"] is True
    events = await _events(db_session, item.room_id)
    assert [event.correlation_id for event in events] == [
        f"{item.client_action_id}:step:0",
        f"{item.client_action_id}:step:1",
        item.client_action_id,
    ]
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert len(contexts) == 3
    assert len(await _events(db_session, item.room_id)) == 3


@pytest.mark.parametrize(
    "window", ["before_engine", "after_engine", "after_feedback", "after_release"]
)
async def test_worker_restart_recovers_without_redeciding_or_reapplying_current_rule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
    window: str,
) -> None:
    store, item, app, contexts, restart = await _runtime(
        db_session, monkeypatch, action_plan_store_factory
    )
    owner = ws if window == "after_feedback" else app
    method = (
        "_persist_composite_step_feedback"
        if window == "after_feedback"
        else "mark_narration_persisted"
        if window == "after_release"
        else "start_rule_once"
    )
    original = getattr(owner, method)
    crashed = False

    async def interrupt(*args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            if window != "before_engine":
                await original(*args, **kwargs)
            raise WorkerCrash()
        return await original(*args, **kwargs)

    monkeypatch.setattr(owner, method, interrupt)
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    with pytest.raises(WorkerCrash):
        await ws._run_composite_rule_action(db_session, item, view, None)
    assert len(contexts) == 1
    room_id, action_id = item.room_id, item.client_action_id
    # Recreate both the application and SQL run adapter, then reload the queue.
    monkeypatch.setattr(owner, method, original)
    app = restart()
    db_session.expire_all()
    item = await queue.get_by_client_action(db_session, room_id, action_id)
    assert item is not None
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed"
    assert len(contexts) == 3
    assert (await _state(store, room_id)).entities["cemetery_figure"]["truth_told"] is True
    assert len(await _events(db_session, room_id)) == 3
    for index in range(2):
        run = await app.get_plan(room_id, rule_loop_id(action_id, "rule", index))
        assert run is not None and run.status == "completed"


async def test_mid_loop_clarification_keeps_prior_results_and_original_action(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    store, item, _, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, clarification=True
    )
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "needs_clarification"
    assert await queue.peek_next(db_session, item.room_id) is None
    assert len(item.result_event_ids) == 2
    assert (await _state(store, item.room_id)).entities["cemetery_figure"][
        "willing_to_talk"
    ] is True
    await queue.save_continuation(db_session, item, text="问他的往事")
    claimed = await queue.claim(db_session, item, recipient_kind="keeper")
    assert claimed is not None
    await ws._run_composite_rule_action(db_session, claimed, view, None)
    assert claimed.status == "completed"
    assert [context.public.loop_step_index for context in contexts] == [0, 1, 1, 2]
    assert len(await _events(db_session, item.room_id)) == 4


async def test_damaged_cursor_never_starts_a_fresh_rule_loop(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, _, contexts, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)
    item.rule_loop_json = {**(item.rule_loop_json or {}), "actor_id": "another-actor"}
    await db_session.commit()
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    with pytest.raises(ContractError):
        await ws._run_composite_rule_action(db_session, item, view, None)
    assert not contexts


async def test_max_length_parent_id_is_accepted_through_real_engine(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, _, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, action_id="a" * 200
    )
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed" and len(contexts) == 3
    assert all(
        len(event.correlation_id or "") <= 200 for event in await _events(db_session, item.room_id)
    )


@pytest.mark.parametrize("cancel_index", [0, 1])
async def test_cancelled_check_stops_later_rules_and_preserves_prior_commits(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
    cancel_index: int,
) -> None:
    store, item, app, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, check_step=cancel_index
    )
    messages: list[dict] = []

    async def capture(_socket, message):
        messages.append(message)
        return True

    monkeypatch.setattr(ws, "_send_to_player", capture)
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    pending = [message for message in messages if message.get("type") == "adjudication.pending"]
    assert pending
    assert pending[-1]["payload"]["correlationId"] == item.client_action_id
    composite = await ws._find_composite_action(db_session, item.room_id, item.client_action_id)
    assert composite is not None
    _, loop, step = composite
    run = await app.get_plan(item.room_id, step.step_id)
    assert run is not None
    execution = run.steps[0].adjudication_execution
    assert execution is not None and execution.pending_decision is not None
    decision = execution.pending_decision
    await ws.adjudication_engine_service.decide(
        CheckDecisionRequest(
            request_id=f"cancel-check-{cancel_index}",
            room_id=item.room_id,
            player_id=item.player_id,
            source_revision=execution.view_revision,
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            choice=CancelCheckChoice(),
        )
    )
    result = await app.resume_pending(
        room_id=item.room_id, player_id=item.player_id, parent_action_id=step.step_id
    )
    await ws._finish_composite_step(db_session, None, item, loop, step, result)
    assert item.status == "completed"
    assert len(contexts) == cancel_index + 1
    state = (await _state(store, item.room_id)).entities["cemetery_figure"]
    assert bool(state.get("willing_to_talk")) is (cancel_index == 1)
    assert not state.get("truth_told")
    assert await app.active_for_room(item.room_id) is None


async def test_unresolved_composite_choice_never_executes_the_first_candidate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    store, item, _, _, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)

    class UnresolvedModel:
        async def generate(self, context):
            return {"route": "composite_rule"}

    monkeypatch.setattr(ws, "_host_entry_router", HostEntryRouter(UnresolvedModel()))
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed"
    assert item.rule_loop_json is not None and not item.rule_loop_json["steps"]
    assert (
        not (await _state(store, item.room_id)).entities["cemetery_figure"].get("willing_to_talk")
    )


async def test_failed_broadcast_does_not_cancel_or_replay_a_committed_step(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, _, contexts, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)
    emitted: list[str] = []

    async def fail_first_broadcast(*args, **kwargs):
        emitted.append(kwargs["client_action_id"])
        if len(emitted) == 1:
            raise OSError("connection lost")

    monkeypatch.setattr(ws, "_emit_turn_narration", fail_first_broadcast)
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed" and len(contexts) == 3
    assert len(emitted) == len(set(emitted)) == 3
    assert len(await _events(db_session, item.room_id)) == 3


async def test_cancelling_outer_action_releases_its_waiting_internal_plan(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, app, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, check_step=1
    )
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert await app.active_for_room(item.room_id) is not None
    assert await ws._cancel_composite_action(
        db_session,
        None,
        room_id=item.room_id,
        player_id=item.player_id,
        client_action_id=item.client_action_id,
        request_id="cancel-outer-action",
    )
    assert item.status == "completed"
    assert await app.active_for_room(item.room_id) is None
    assert len(contexts) == 2


@pytest.mark.parametrize("refresh_item", [False, True])
async def test_stale_worker_cannot_overwrite_newer_loop_cursor(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
    refresh_item: bool,
) -> None:
    _, item, _, _, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)
    assert db_session.bind is not None
    async with AsyncSession(db_session.bind, expire_on_commit=False) as other:
        stale = await queue.get_by_client_action(other, item.room_id, item.client_action_id)
        assert stale is not None
        state = queue.load_rule_loop(item)
        assert state is not None
        await queue.save_rule_loop(
            db_session, item, state.model_copy(update={"final_text": "newer"})
        )
        if refresh_item:
            await other.refresh(stale)
        with pytest.raises(queue.HostActionQueueError, match="另一个恢复任务"):
            await queue.save_rule_loop(
                other, stale, state.model_copy(update={"final_text": "stale"})
            )
    await db_session.refresh(item)
    assert item.rule_loop_json is not None and item.rule_loop_json["final_text"] == "newer"


async def test_failed_roll_stops_loop_without_losing_the_prior_rule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    store, item, app, contexts, restart = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, check_step=1
    )
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    composite = await ws._find_composite_action(db_session, item.room_id, item.client_action_id)
    assert composite is not None
    _, loop, step = composite
    run = await app.get_plan(item.room_id, step.step_id)
    assert run is not None
    execution = run.steps[0].adjudication_execution
    assert execution is not None and execution.pending_decision is not None
    decision = execution.pending_decision
    execution = await ws.adjudication_engine_service.decide(
        CheckDecisionRequest(
            request_id="failed-second-rule-roll",
            room_id=item.room_id,
            player_id=item.player_id,
            source_revision=execution.view_revision,
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            choice=SelectCheckChoice(candidate_id=decision.options[0].candidate_id),
        )
    )
    assert execution.status == "awaiting_post_roll_decision"
    assert execution.check_run is not None
    # Resume with a freshly constructed SQL engine/app at the post-roll wait.
    app = restart()
    execution = await ws.adjudication_engine_service.decide_post_roll(
        PostRollDecisionRequest(
            request_id="accept-second-rule-failure",
            room_id=item.room_id,
            player_id=item.player_id,
            source_revision=execution.view_revision,
            check_id=execution.check_run.check_id,
            check_version=execution.check_run.version,
            option_id="accept-current",
        )
    )
    assert execution.outcome == "failure"
    result = await app.resume_pending(
        room_id=item.room_id, player_id=item.player_id, parent_action_id=step.step_id
    )
    await ws._finish_composite_step(db_session, None, item, loop, step, result)
    assert item.status == "completed"
    assert len(contexts) == 2
    state = await _state(store, item.room_id)
    assert state.entities["cemetery_figure"]["willing_to_talk"] is True
    assert not state.entities["cemetery_figure"].get("truth_told")
    assert len(await _events(db_session, item.room_id)) == 3
    assert await app.active_for_room(item.room_id) is None


@pytest.mark.parametrize("consent_kind", ["time", "scene"])
@pytest.mark.parametrize("resolution", ["approve", "reject", "cancel"])
async def test_shared_consent_recovers_and_releases_the_outer_queue_in_order(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
    consent_kind: str,
    resolution: str,
) -> None:
    store, item, app, contexts, restart = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, consent_kind=consent_kind
    )
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    await ws._run_composite_rule_action(db_session, item, view, None)
    loop = queue.load_rule_loop(item)
    assert loop is not None and loop.status == "awaiting_player" and loop.step_index == 1
    service = ws.time_advance_service if consent_kind == "time" else ws.scene_transition_service
    pending = await service.get_pending(
        db_session, item.room_id, engine=ws.adjudication_engine_service
    )
    assert isinstance(pending, (TimeAdvancePendingPayload, SceneTransitionPendingPayload))
    assert len(pending.required_player_ids) == 2
    room_state = await ws._current_room_action_state(db_session, item.room_id)
    assert room_state is not None and room_state.client_action_id == item.client_action_id
    later, _ = await queue.enqueue(
        db_session,
        room_id=item.room_id,
        player_id=item.player_id,
        actor_id=item.actor_id,
        client_action_id="later-action",
        utterance="接着调查",
        recipient=ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True),
    )
    assert await queue.peek_next(db_session, item.room_id) is None
    app = restart()
    # Reconnect must only re-expose the pending consent, preserving its identity.
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert len(contexts) == 2
    replay = await service.get_pending(db_session, item.room_id)
    assert replay is not None and replay.proposal_id == pending.proposal_id
    if resolution == "cancel":
        assert await ws._cancel_composite_action(
            db_session,
            None,
            room_id=item.room_id,
            player_id=item.player_id,
            client_action_id=item.client_action_id,
            request_id="cancel-shared-consequence",
        )
    else:
        response = {
            "engine": ws.adjudication_engine_service,
            "room_id": item.room_id,
            "player_id": next(
                player for player in pending.required_player_ids if player != item.player_id
            ),
            "proposal_id": pending.proposal_id,
            "proposal_version": pending.proposal_version,
            "source_revision": pending.source_revision,
            "accept": resolution == "approve",
        }
        _, owner, action_id = await service.respond(db_session, **response)
        assert owner == item.player_id and action_id is not None
        composite = await ws._find_composite_step(db_session, item.room_id, action_id)
        assert composite is not None
        _, loop, step = composite
        result = await app.resume_pending(
            room_id=item.room_id, player_id=item.player_id, parent_action_id=step.step_id
        )
        await ws._finish_composite_step(db_session, None, item, loop, step, result)
        _, duplicate_owner, duplicate_action = await service.respond(db_session, **response)
        assert duplicate_owner is duplicate_action is None
    assert item.status == "completed"
    assert await service.get_pending(db_session, item.room_id) is None
    assert await app.active_for_room(item.room_id) is None
    assert len(contexts) == (3 if resolution == "approve" else 2)
    state = await _state(store, item.room_id)
    assert state.entities["cemetery_figure"]["willing_to_talk"] is True
    assert not state.entities["cemetery_figure"].get("truth_told")
    if consent_kind == "scene":
        assert state.scene_id == ("arnoldsburg_streets" if resolution == "approve" else "cemetery")
    head = await queue.peek_next(db_session, item.room_id)
    assert head is not None and head.item_id == later.item_id
    assert len(await _events(db_session, item.room_id)) == 3


async def test_step_recovery_preserves_npc_reply_before_deciding_the_next_rule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, app, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory, action_id="n" * 190
    )
    original_start = app.start_rule_once
    original_followup = ws._emit_keeper_followup_dialogue
    router = ws._get_host_entry_router()
    original_decide = router.decide

    async def after_durable_reply(context):
        if context.public.loop_step_index:
            previous = rule_loop_id(
                item.client_action_id, "step", context.public.loop_step_index - 1
            )
            reply = await ws.room_service.get_correlated_event(
                db_session, item.room_id, "dialogue.npc", f"{previous}:followup-npc:0"
            )
            assert reply is not None
        return await original_decide(context)

    monkeypatch.setattr(router, "decide", after_durable_reply)

    async def with_reply(**kwargs):
        result = await original_start(**kwargs)
        assert result.narration is not None
        return replace(
            result,
            narration=result.narration.model_copy(
                update={
                    "npc_replies": (
                        ActionPlanNpcReply(speaker_id="cemetery_figure", text="我愿意谈谈。"),
                    ),
                }
            ),
        )

    async def crash_before_followup(*args, **kwargs):
        raise WorkerCrash()

    monkeypatch.setattr(app, "start_rule_once", with_reply)
    monkeypatch.setattr(ws, "_emit_keeper_followup_dialogue", crash_before_followup)
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    with pytest.raises(WorkerCrash):
        await ws._run_composite_rule_action(db_session, item, view, None)
    assert len(contexts) == 1
    monkeypatch.setattr(ws, "_emit_keeper_followup_dialogue", original_followup)
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert item.status == "completed" and len(contexts) == 3
    # Scene-scoped replies remain excluded from the room-wide public router context.
    assert not any(entry.text == "我愿意谈谈。" for entry in contexts[1].public.recent_history)
    replies = list(
        (
            await db_session.scalars(
                select(Event).where(
                    Event.room_id == item.room_id, Event.event_type == "dialogue.npc"
                )
            )
        ).all()
    )
    assert len(replies) == 2
    assert all(len(event.correlation_id or "") <= 200 for event in replies)
    await ws._run_composite_rule_action(db_session, item, view, None)
    assert len(await _events(db_session, item.room_id)) == 3


async def test_answer_to_initial_clarification_can_enter_a_fresh_composite_loop(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
) -> None:
    _, item, _, _, _ = await _runtime(db_session, monkeypatch, action_plan_store_factory)
    item.rule_loop_json = None
    await queue.save_execution_route(
        db_session, item, route="needs_clarification", text="想做什么？", provenance="test"
    )
    await queue.save_continuation(db_session, item, text="先打招呼，再询问往事")
    assert await queue.claim(db_session, item, recipient_kind="keeper") is not None

    class EntryModel:
        async def generate(self, context):
            assert context.public.player_answer
            return {"route": "composite_rule"}

    monkeypatch.setattr(ws, "_host_entry_router", HostEntryRouter(EntryModel()))
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    assert await ws._route_keeper_queue_item(db_session, item, view) == "composite_rule"
    loop = queue.load_rule_loop(item)
    assert loop is not None and loop.step_index == 0 and not loop.steps


@pytest.mark.parametrize("stop_method", ["retry_exhausted", "cancel"])
async def test_exhausted_narrator_retries_stop_and_release_the_committed_rule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action_plan_store_factory,
    stop_method: str,
) -> None:
    store, item, app, contexts, _ = await _runtime(
        db_session, monkeypatch, action_plan_store_factory
    )

    class UnavailableNarrator:
        async def generate(self, context):
            raise RuntimeError("narration provider unavailable")

    monkeypatch.setattr(app, "_narrator", ActionPlanNarrator(UnavailableNarrator()))
    view = await ws.session_view_application.current_player_view(
        room_id=item.room_id, player_id=item.player_id
    )
    for attempt in range(2):
        if attempt:
            claimed = await queue.claim(db_session, item, recipient_kind="keeper")
            assert claimed is not None
            item = claimed
        with pytest.raises(TurnExecutionError) as failure:
            await ws._run_composite_rule_action(db_session, item, view, None)
        if stop_method == "cancel":
            assert await ws._cancel_composite_action(
                db_session,
                None,
                room_id=item.room_id,
                player_id=item.player_id,
                client_action_id=item.client_action_id,
                request_id="cancel-committed-rule",
            )
            break
        await ws._handle_composite_failure(db_session, item, None, failure.value)
    assert item.status == "completed"
    assert len(contexts) == 1
    state = await _state(store, item.room_id)
    assert state.entities["cemetery_figure"]["willing_to_talk"] is True
    assert not state.entities["cemetery_figure"].get("truth_told")
    assert await app.active_for_room(item.room_id) is None
    assert len(await _events(db_session, item.room_id)) == 2
