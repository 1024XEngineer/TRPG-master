"""Public item names must survive planning without releasing their hidden facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from collaboration_framework.contracts import (
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    InventoryItemView,
    KeeperCapabilityView,
    KeeperEntityCapability,
    KeeperInformationCapability,
    KnownInformationView,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
)
from collaboration_framework.host.schemas import (
    MemoryContext,
    RecentTurn,
    RecentTurnContext,
    TurnPlanningContext,
    TurnPlanningView,
    VisibleHistoryText,
)

from app.core.action_plan_turn import ActionPlanTurnApplication, _action_plan_disclosure_reason


@pytest.fixture
def player_input():
    return PlayerInput(
        room_id="room",
        player_id="player",
        actor_id="actor",
        client_action_id="inspect-flyer",
        utterance="查看传单，然后去蛙蛙村",
    )


@pytest.fixture
def view(player_input):
    return PlayerView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        background="调查失踪事件。",
        scene_id="manor",
        phase="playing",
        revision="0",
        self_actor=SelfActorView(id="actor", name="调查员"),
        scene=SceneView(id="manor", name="庄园", description="会客厅。"),
    )


@pytest.fixture
def capabilities():
    return KeeperCapabilityView(
        room_id="room",
        actor_id="actor",
        revision="0",
        entities=(
            KeeperEntityCapability(
                id="resort_flyer",
                name="蛙蛙度假村传单",
                kind="object",
                origin="canon",
                holder_actor_id="actor",
            ),
            KeeperEntityCapability(
                id="private_whistle",
                name="铜哨",
                kind="object",
                origin="canon",
                holder_actor_id="another-actor",
            ),
        ),
        information=(
            KeeperInformationCapability(
                id="flyer_secret",
                title="传单密文",
                summary="纸张中的暗号",
                content="传单背面藏着祭坛口令。",
                related_entities=("resort_flyer",),
            ),
        ),
    )


def item(item_id="resort_flyer"):
    return InventoryItemView(
        id=item_id,
        name="蛙蛙度假村传单",
        quantity=1,
        condition="intact",
        version=1,
    )


def plan(text="查看蛙蛙度假村传单"):
    return ActionPlan(
        goal=text,
        steps=(
            ActionPlanStep(kind="action", semantic_goal=text, public_progress_label=text),
            ActionPlanStep(kind="travel", semantic_goal="前往蛙蛙村"),
        ),
    )


@pytest.mark.parametrize("source", ["inventory", "loose_items", "known_information"])
@pytest.mark.parametrize("item_id", ["resort_flyer", "flyer-instance-2"])
def test_public_full_name_is_allowed_from_short_player_input(
    player_input,
    view,
    capabilities,
    source,
    item_id,
):
    if source == "inventory":
        view = view.model_copy(update={"inventory": (item(item_id),)})
    elif source == "loose_items":
        view = view.model_copy(
            update={
                "scene": view.scene.model_copy(update={"loose_items": (item(item_id),)}),
            }
        )
    else:
        view = view.model_copy(
            update={
                "known_information": (
                    KnownInformationView(
                        id="flyer_public",
                        title="蛙蛙度假村传单",
                        summary="介绍度假村。",
                        content="欢迎到蛙蛙村游玩。",
                        scope="actor",
                    ),
                )
            }
        )
    assert (
        _action_plan_disclosure_reason(
            plan(),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        is None
    )


@pytest.mark.parametrize("field", ["goal", "semantic_goal", "public_progress_label"])
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("查看蛙蛙度假村传单", None),
        ("传单背面藏着祭坛口令。", "hidden_keeper_term"),
        ("寻找铜哨", "hidden_keeper_term"),
        ("查看resort_flyer", "internal_target_id"),
        ("查看flyer-instance-2", "internal_target_id"),
        ("查看flyer_secret", "internal_target_id"),
    ],
)
def test_public_item_does_not_release_private_content_or_ids(
    player_input,
    view,
    capabilities,
    field,
    text,
    reason,
):
    view = view.model_copy(update={"inventory": (item("flyer-instance-2"),)})
    candidate = plan("查看传单")
    if field == "goal":
        candidate = candidate.model_copy(update={"goal": text})
    else:
        candidate = candidate.model_copy(
            update={
                "steps": (
                    candidate.steps[0].model_copy(update={field: text}),
                    candidate.steps[1],
                )
            }
        )
    assert (
        _action_plan_disclosure_reason(
            candidate,
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        == reason
    )


def planning_context(player_input, view, *, history_text="你拿到蛙蛙度假村传单。"):
    history = RecentTurnContext(
        room_id=view.room_id,
        viewer_player_id=view.player_id,
        as_of_revision=view.revision,
        turns=(
            RecentTurn(
                correlation_id="prior-turn",
                source_player_id=view.player_id,
                source_actor_id=view.actor_id,
                player_utterance=VisibleHistoryText(text="查看传单", visibility="public"),
                published_narration=VisibleHistoryText(text=history_text, visibility="public"),
                evidence_refs=("flyer_secret", "private_whistle"),
            ),
        ),
    )
    return TurnPlanningContext(
        player_input=player_input,
        planning_view=TurnPlanningView.from_player_view(view),
        recent_history=history,
    )


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("查看蛙蛙度假村传单", None),
        ("查看flyer_secret", "internal_target_id"),
        ("寻找铜哨", "hidden_keeper_term"),
    ],
)
def test_public_history_allows_names_but_not_metadata(
    player_input,
    view,
    capabilities,
    text,
    reason,
):
    assert (
        _action_plan_disclosure_reason(
            plan(text),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
            planning_context=planning_context(player_input, view),
        )
        == reason
    )


def test_public_name_does_not_imply_ownership_or_secret_discovery(player_input, view, capabilities):
    # 同名 Information 的标题公开了物品名称，正文仍未揭示。
    capabilities = capabilities.model_copy(
        update={
            "information": (
                capabilities.information[0].model_copy(update={"title": "蛙蛙度假村传单"}),
            )
        }
    )
    view = view.model_copy(update={"inventory": (item(),)})
    assert (
        _action_plan_disclosure_reason(
            plan(),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        is None
    )
    assert (
        _action_plan_disclosure_reason(
            plan(capabilities.information[0].content),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        == "hidden_keeper_term"
    )


@pytest.mark.parametrize("text", ["查看Resort Flyer", "查看Resort Flyer，引用FLYER"])
def test_english_public_name_does_not_allow_extra_internal_id(
    player_input,
    view,
    capabilities,
    text,
):
    view = view.model_copy(
        update={"inventory": (item().model_copy(update={"id": "flyer", "name": "Resort Flyer"}),)}
    )
    capabilities = capabilities.model_copy(
        update={
            "entities": (
                capabilities.entities[0].model_copy(update={"id": "flyer", "name": "Resort Flyer"}),
            )
        }
    )
    assert _action_plan_disclosure_reason(
        plan(text),
        player_input=player_input,
        player_view=view,
        capabilities=capabilities,
    ) == ("internal_target_id" if "引用" in text else None)


def application_for(player_input, view, capabilities, decisions, context):
    application = object.__new__(ActionPlanTurnApplication)
    application._resolve_actor_id = AsyncMock(return_value=player_input.actor_id)
    application._projector = SimpleNamespace(project=AsyncMock(return_value=view))
    application._orchestrator = SimpleNamespace(
        get_run=AsyncMock(return_value=None),
        active_for_room=AsyncMock(return_value=None),
        policy=ActionPlanPolicy(),
    )
    application._read_recent_history = AsyncMock(return_value=context.recent_history)
    application._read_memory_context = AsyncMock(
        return_value=MemoryContext(
            room_id=view.room_id,
            player_id=view.player_id,
            actor_id=view.actor_id,
            as_of_revision=view.revision,
        )
    )
    application._keeper_capabilities = AsyncMock(return_value=capabilities)
    application._semantic_planner = SimpleNamespace(generate=AsyncMock(side_effect=decisions))
    application._semantic_planner_rollout_percent = 0
    application._planner = SimpleNamespace(generate=AsyncMock())
    application._dispatcher = SimpleNamespace(execute=AsyncMock(return_value="advanced"))
    application._finish_plan_with_phases = AsyncMock(return_value="executed")
    return application


@pytest.mark.parametrize("source", ["inventory", "history"])
async def test_full_name_plan_reaches_execution_once(
    player_input,
    view,
    capabilities,
    source,
):
    if source == "inventory":
        view = view.model_copy(update={"inventory": (item(),)})
    context = planning_context(
        player_input,
        view,
        history_text="你拿到蛙蛙度假村传单。" if source == "history" else "你站在庄园。",
    )
    candidate = plan()
    application = application_for(player_input, view, capabilities, [candidate], context)
    result = await application.start(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        client_action_id=player_input.client_action_id,
        utterance=player_input.utterance,
    )
    assert result == "executed"
    application._semantic_planner.generate.assert_awaited_once()
    application._dispatcher.execute.assert_awaited_once()
    assert application._dispatcher.execute.await_args.args[1] == candidate
    application._planner.generate.assert_not_awaited()


@pytest.mark.parametrize("retry_succeeds", [False, True])
async def test_disclosure_retry_is_checked_and_never_executes_rejected_plan(
    player_input,
    view,
    capabilities,
    retry_succeeds,
):
    view = view.model_copy(update={"inventory": (item(),)})
    rejected = plan("传单背面藏着祭坛口令。")
    context = planning_context(player_input, view)
    application = application_for(
        player_input,
        view,
        capabilities,
        [rejected, plan() if retry_succeeds else rejected],
        context,
    )
    phases = []

    async def observe(phase):
        phases.append(phase)

    result = await application.start(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        client_action_id=player_input.client_action_id,
        utterance=player_input.utterance,
        on_phase=observe,
    )
    assert application._semantic_planner.generate.await_count == 2
    application._planner.generate.assert_not_awaited()
    if retry_succeeds:
        assert result == "executed"
        application._dispatcher.execute.assert_awaited_once()
        assert application._dispatcher.execute.await_args.args[1] == plan()
    else:
        application._dispatcher.execute.assert_not_awaited()
        assert result.execution is None and result.plan_id is None
        assert result.narration is not None
        assert "行动尚未执行" in result.narration.text
        assert "明确" not in result.narration.text
        assert "祭坛" not in result.narration.text
        assert phases[-1] == "generating_narration"


@pytest.mark.parametrize("failure_reason", ["structure", "disclosure"])
def test_model_failure_does_not_ask_player_to_clarify(player_input, view, failure_reason):
    result = ActionPlanTurnApplication._planning_failure_clarification(
        player_input=player_input,
        player_view=view,
        failure_reason=failure_reason,
    )
    assert result.execution is None
    assert result.narration is not None
    assert "行动尚未执行" in result.narration.text
    assert "请再明确" not in result.narration.text


async def test_frog_module_inventory_plan_reaches_authoritative_skill_check():
    from collaboration_framework.contracts import ModuleContentV3
    from collaboration_framework.engine import (
        ActorState,
        AdjudicationEngineService,
        InMemoryEngineStore,
        RuleEngineService,
    )
    from collaboration_framework.engine.initialization import create_initial_game_state
    from collaboration_framework.host.schemas import ActionPlanStepContext

    from app.core.action_plan_turn import (
        build_action_plan_turn_application,
        build_rule_once_adjudication,
    )
    from app.core.config import Settings
    from tests.test_accompanying_host import FIXTURE, EmptyMemory

    content = ModuleContentV3.model_validate_json(FIXTURE.read_text())
    state = create_initial_game_state(
        content,
        room_id="flyer-regression",
        actors={
            "actor": ActorState(
                player_id="player",
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                state={"skills": {"library-use": 60}},
            )
        },
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    rules = RuleEngineService(store)
    engine = AdjudicationEngineService(store)

    class OfflineClient:
        def __init__(self):
            self.calls = []

        async def generate(self, *, schema_name, schema, instructions, input_payload):
            self.calls.append(schema_name)
            if schema_name == "trpg_turn_plan":
                assert "keeper_capabilities" not in input_payload
                planning_view = TurnPlanningView.model_validate(input_payload["planning_view"])
                assert "蛙蛙度假村传单" in [i.name for i in planning_view.inventory_items]
                assert "蛙蛙度假村传单" not in [i.name for i in planning_view.visible_entities]
                return plan().to_json_dict()
            assert schema_name == "trpg_action_plan_step_adjudication"
            context = ActionPlanStepContext.model_validate(input_payload)
            assert context.step_index == 0
            assert context.keeper_capabilities is not None
            return build_rule_once_adjudication(
                player_input=context.player_input,
                player_view=context.player_view,
                capabilities=context.keeper_capabilities,
                rule_id="inspect_resort_flyer",
                option_id="library-use",
                summary=context.step.semantic_goal,
            ).to_json_dict()

    client = OfflineClient()
    application = build_action_plan_turn_application(
        store=store,
        engine=rules,
        adjudication_engine=engine,
        settings=Settings(host_model_provider="deepseek", deepseek_api_key="offline-test"),
        client=client,
        planner_client=client,
        memory_source=EmptyMemory(),
    )
    result = await application.start(
        room_id="flyer-regression",
        player_id="player",
        client_action_id="inspect-flyer",
        utterance="查看传单，然后去蛙蛙村",
    )
    assert client.calls == ["trpg_turn_plan", "trpg_action_plan_step_adjudication"]
    assert result.status == "waiting_for_player"
    assert result.execution is not None
    assert result.execution.status == "awaiting_skill_choice"
    assert result.plan_id is not None
    run = await application.get_plan("flyer-regression", "inspect-flyer")
    assert run is not None
    assert run.plan == plan()
    assert run.current_step_index == 0
    assert run.steps[1].status == "pending"
    assert store.inspect_state("flyer-regression").scene_id == "lane_manor"


@pytest.mark.parametrize("utterance", ["查看传单", "查看resort_flyer"])
def test_public_short_word_cannot_mask_part_of_internal_id(
    player_input,
    view,
    capabilities,
    utterance,
):
    view = view.model_copy(update={"inventory": (item().model_copy(update={"name": "Flyer"}),)})
    player_input = player_input.model_copy(update={"utterance": utterance})
    assert (
        _action_plan_disclosure_reason(
            plan("查看resort_flyer"),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        == "internal_target_id"
    )


def test_keeper_custody_alone_does_not_make_name_public(player_input, view, capabilities):
    assert (
        _action_plan_disclosure_reason(
            plan(),
            player_input=player_input,
            player_view=view,
            capabilities=capabilities,
        )
        == "hidden_keeper_term"
    )


@pytest.mark.parametrize("source", ["memory", "summary"])
def test_public_long_term_text_allows_name_but_not_metadata(
    player_input,
    view,
    capabilities,
    source,
):
    from collaboration_framework.host.schemas import ConversationSummary, MemoryEntry

    context = planning_context(player_input, view, history_text="你站在庄园。")
    if source == "memory":
        context = context.model_copy(
            update={
                "memories": (
                    MemoryEntry(
                        memory_id="old-memory",
                        room_id=view.room_id,
                        subject_id=view.actor_id,
                        object_id="private_whistle",
                        kind="clue",
                        content="你见过蛙蛙度假村传单。",
                        epistemic_status="experienced",
                        visibility="player_scoped",
                        source_event_id="flyer_secret",
                        source_sequence=1,
                    ),
                )
            }
        )
    else:
        context = context.model_copy(
            update={
                "conversation_summary": ConversationSummary(
                    room_id=view.room_id,
                    player_id=view.player_id,
                    summary="你见过蛙蛙度假村传单。",
                    important_entities=("private_whistle",),
                    source_event_ids=("flyer_secret",),
                )
            }
        )
    for text, reason in [
        ("查看蛙蛙度假村传单", None),
        ("查看flyer_secret", "internal_target_id"),
        ("寻找铜哨", "hidden_keeper_term"),
        ("传单背面藏着祭坛口令。", "hidden_keeper_term"),
    ]:
        assert (
            _action_plan_disclosure_reason(
                plan(text),
                player_input=player_input,
                player_view=view,
                capabilities=capabilities,
                planning_context=context,
            )
            == reason
        )
