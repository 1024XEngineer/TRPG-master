from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from collaboration_framework.contracts import (
    ActionPlanPolicy,
    AvailableExitView,
    CommittedResult,
    InventoryItemView,
    KeeperCapabilityView,
    KeeperEntityCapability,
    KeeperInformationCapability,
    NarrationEvidence,
    PlayerInput,
    PlayerView,
    PostRollDecisionRequest,
    SceneView,
    SelfActorView,
    VisibleEntity,
)
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
)
from collaboration_framework.host.schemas import (
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
    CompletedPlanStepSummary,
)

from app.adapters.structured_http import StructuredOutputError
from app.core.action_plan_turn import ActionPlanTurnApplication


def _run(*, cancel_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        room_id="room-281",
        player_id="player-281",
        actor_id="actor-281",
        parent_action_id="plan-281",
        parent_utterance="完成连续行动",
        plan=SimpleNamespace(goal="完成连续行动"),
        plan_id="plan-281",
        status="waiting_for_player",
        current_step_index=0,
        pending_cancel_request_id=cancel_id,
        steps=(
            SimpleNamespace(
                step_request_id="step-281",
                status="waiting_for_player",
                adjudication_execution=None,
            ),
        ),
    )


def _status(status: str) -> SimpleNamespace:
    check_run = SimpleNamespace(
        check_id="check-281",
        version=1,
        post_roll_options=(SimpleNamespace(kind="accept_result", option_id="accept-current"),),
    )
    execution = SimpleNamespace(
        status=status,
        view_revision="revision-7",
        check_run=check_run if status == "awaiting_post_roll_decision" else None,
    )
    return SimpleNamespace(status=status, execution=execution)


class _Engine:
    def __init__(self, status: SimpleNamespace) -> None:
        self.status = status
        self.status_requests = []
        self.post_roll_requests: list[PostRollDecisionRequest] = []

    async def get_status(self, request):
        self.status_requests.append(request)
        return self.status

    async def decide_post_roll(self, request: PostRollDecisionRequest):
        self.post_roll_requests.append(request)
        self.status = _status("resolved")
        return self.status.execution


class _Orchestrator:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run
        self.resume_calls = []
        self.adjudicator = object()
        self.policy = ActionPlanPolicy(max_repair_attempts=3)

    async def get_run(self, room_id: str, parent_action_id: str):
        assert room_id == self.run.room_id
        assert parent_action_id == self.run.parent_action_id
        return self.run

    async def resume_owned(self, **kwargs):
        self.resume_calls.append(kwargs)
        return SimpleNamespace(run=self.run)


class _NarrationContextStub:
    def __init__(
        self,
        evidence: NarrationEvidence,
        termination_status: str,
        *,
        interlocutor_id: str | None = None,
        visible_entities: tuple[object, ...] = (),
    ) -> None:
        self.narration_evidence = (evidence,)
        self.termination_status = termination_status
        self.narration_retry_hint: str | None = None
        self.interlocutor_id = interlocutor_id
        self.visible_entities = visible_entities
        self.player_input = SimpleNamespace(
            client_action_id="action-narration-test",
            utterance="",
            interlocutor_id=interlocutor_id,
        )
        self.player_view = SimpleNamespace(
            scene=SimpleNamespace(visible_entities=visible_entities),
        )
        self.completed_steps: tuple[object, ...] = ()

    def model_copy(self, *, update: dict[str, object]):
        copied = _NarrationContextStub(
            self.narration_evidence[0],
            self.termination_status,
            interlocutor_id=self.interlocutor_id,
            visible_entities=self.visible_entities,
        )
        copied.narration_retry_hint = cast(str | None, update["narration_retry_hint"])
        return copied


def _application(run: SimpleNamespace, engine: _Engine, orchestrator: _Orchestrator):
    application = object.__new__(ActionPlanTurnApplication)
    application._adjudication_engine = engine
    application._orchestrator = orchestrator
    application._resolve_actor_id = AsyncMock(return_value=run.actor_id)
    application._finish_plan_with_phases = AsyncMock(return_value="recovered")
    return application


def test_application_injects_plan_repair_dependencies_into_single_action_path() -> None:
    run = _run(cancel_id=None)
    engine = _Engine(_status("resolved"))
    orchestrator = _Orchestrator(run)

    application = ActionPlanTurnApplication(
        store=cast(Any, object()),
        engine=cast(Any, object()),
        adjudication_engine=cast(Any, engine),
        planner=cast(Any, object()),
        orchestrator=cast(Any, orchestrator),
        narrator=cast(Any, object()),
        recent_history_source=cast(Any, object()),
        recent_history_budget=cast(Any, object()),
        recent_history_enabled=False,
    )

    assert application._dispatcher._repair_adjudicator is orchestrator.adjudicator
    assert application._dispatcher._policy is orchestrator.policy


@pytest.mark.parametrize(
    ("outcomes", "termination_status", "expected"),
    (
        (
            ("failure",),
            "resolved",
            "这次行动未能成功，局面没有产生当前可确认的新结果。",
        ),
        (
            ("success", "failure"),
            "stopped",
            "当前步骤未能成功；此前已经完成的步骤仍然保留。",
        ),
        (("cancelled",), "cancelled", "这次行动已经取消。"),
        (("success",), "resolved", "这次行动已经按当前可确认的结果完成。"),
    ),
)
def test_deterministic_narration_fallback_preserves_action_outcome(
    outcomes: tuple[str, ...],
    termination_status: str,
    expected: str,
) -> None:
    """模型叙事被拒绝后，兜底文案仍必须忠实表达权威行动结果。"""

    context = SimpleNamespace(
        termination_status=termination_status,
        player_input=SimpleNamespace(client_action_id="action-fallback"),
        completed_steps=tuple(
            SimpleNamespace(outcome=outcome, committed_results=()) for outcome in outcomes
        ),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(visible_entities=()),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.text == expected


def test_clarification_fallback_points_to_visible_dead_body() -> None:
    """模型连续忽略可见尸体时，兜底应给出权威位置而不是继续要求寻找。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="find-body",
            utterance="去找他的尸体",
        ),
        completed_steps=(),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(
                visible_entities=(
                    SimpleNamespace(
                        id="melodias",
                        name="梅洛迪亚斯·杰弗逊",
                        observable_state=(SimpleNamespace(key="consciousness", value="dead"),),
                    ),
                ),
            ),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.kind == "clarification"
    assert output.text.startswith("梅洛迪亚斯·杰弗逊的尸体就在当前场景中")


def test_unresolved_travel_fallback_narrates_not_found_without_substitution() -> None:
    """无法创建的明确地点应说没找到，不应返回通用表单式澄清。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="unresolved-clinic",
            utterance="去一个与当前背景冲突的诊所",
        ),
        completed_steps=(),
        player_view=SimpleNamespace(scene=SimpleNamespace(visible_entities=())),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert "没有" in output.text
    assert "找到" in output.text
    assert "仍停留在原处" in output.text
    assert "作用于谁或什么" not in output.text
    assert "具体变化" not in output.text


def test_partial_travel_success_fallback_keeps_the_arrival() -> None:
    """旅行已提交、后续步骤失败时，保底叙事不能把玩家送回原处。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="partial-inn",
            utterance="去旅馆，开一间房休息",
        ),
        completed_steps=(
            SimpleNamespace(
                outcome="success",
                semantic_goal="前往旅馆",
                committed_results=(
                    CommittedResult(kind="location", target_id="inn", event_ref="arrived"),
                ),
            ),
        ),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(
                id="inn",
                name="镇上的旅店",
                description="门厅亮着灯。",
                visible_entities=(),
                available_exits=(),
            ),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.kind == "clarification"
    assert "来到镇上的旅店" in output.text
    assert "后续行动" in output.text
    assert "没有" not in output.text
    assert "仍停留在原处" not in output.text


def test_planning_failure_returns_host_reply_without_execution() -> None:
    """规划结构连续失败时必须有主持人回复，并保持零权威写入。"""

    player_input = PlayerInput(
        room_id="room-315",
        player_id="player-315",
        actor_id="actor-315",
        client_action_id="76664d06-3ac2-411b-8986-1ff12ed53cbf",
        utterance="去墓地",
    )
    result = ActionPlanTurnApplication._planning_failure_clarification(
        player_input=player_input,
        player_view=cast(Any, SimpleNamespace()),
    )

    assert result.status == "needs_clarification"
    assert result.execution is None
    assert result.narration is not None
    assert result.narration.kind == "clarification"
    assert "行动的对象或地点" in result.narration.text


@pytest.mark.asyncio
async def test_narration_falls_back_to_required_player_safe_evidence() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(side_effect=ActionPlanNarrationValidationError("required_evidence_missing"))
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-crypt-discovered",
        kind="entity_discovered",
        subject_id="crypt_entrance",
        subject_name="石板下的地穴入口",
        description="一块沉重石板遮住了向下的通道。",
        required_in_narration=True,
    )
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(evidence, "resolved"),
    )

    narration = await application._narrate(context)

    assert narrate.await_count == 2
    retry_context = narrate.await_args_list[1].args[0]
    assert "石板下的地穴入口" in retry_context.narration_retry_hint
    assert "claim" in retry_context.narration_retry_hint
    assert narration.claimed_evidence_refs == (evidence.ref,)
    assert "石板下的地穴入口" in narration.text
    assert "沉重石板" in narration.text
    assert "。。" not in narration.text


@pytest.mark.asyncio
async def test_narration_retries_atmosphere_repeat_with_hint() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(side_effect=ActionPlanNarrationValidationError("atmosphere_repeat"))
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-1",
        kind="entity_discovered",
        subject_id="x",
        subject_name="公开结果",
        required_in_narration=False,
    )
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(evidence, "resolved"),
    )

    narration = await application._narrate(context)

    assert narrate.await_count == 2
    retry_context = narrate.await_args_list[1].args[0]
    assert "不要照抄上一段环境开场" in retry_context.narration_retry_hint
    assert narration.kind == "narration"
    assert "这次行动已经按当前可确认的结果完成" in narration.text


@pytest.mark.asyncio
async def test_narration_retries_persistent_claim_with_actionable_hint() -> None:
    """持久状态校验失败后，第二次模型调用必须收到删除断言的提示。"""
    application = object.__new__(ActionPlanTurnApplication)
    success = SimpleNamespace(kind="narration", text="环境恢复正常。", npc_replies=())
    narrate = AsyncMock(
        side_effect=[
            ActionPlanNarrationValidationError("persistent_claim_without_evidence:posture"),
            success,
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="环境恢复正常。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narration is success
    assert narrate.await_count == 2
    retry_hint = narrate.await_args_list[1].args[0].narration_retry_hint
    assert "没有权威证据确认" in retry_hint
    assert "只描述当前 PlayerView" in retry_hint


@pytest.mark.asyncio
async def test_narration_retries_unknown_validation_with_generic_hint() -> None:
    """未单独分类的安全拒绝也不能原样重复第一次模型输入。"""
    application = object.__new__(ActionPlanTurnApplication)
    success = SimpleNamespace(kind="narration", text="已按当前结果处理。", npc_replies=())
    narrate = AsyncMock(
        side_effect=[
            ActionPlanNarrationValidationError("evidence_scope"),
            success,
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="已按当前结果处理。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narration is success
    assert narrate.await_count == 2
    retry_hint = narrate.await_args_list[1].args[0].narration_retry_hint
    assert "未通过玩家可见输出安全校验" in retry_hint
    assert "输出协议" in retry_hint


class _ValidatingNarrator:
    """两次调用都被拒的 Narrator 桩，另带真实的 validate 供句级降级复校验。"""

    def __init__(self, error: ActionPlanNarrationValidationError) -> None:
        self._error = error
        self.narrate_calls = 0
        self.validate_calls: list[str] = []

    async def narrate(self, context):
        self.narrate_calls += 1
        raise self._error

    def validate(self, context, candidate):
        self.validate_calls.append(candidate.text)
        return candidate


def _rejection_with_span(text: str, start: int, end: int):
    return ActionPlanNarrationValidationError(
        "persistent_claim_without_evidence:inventory_acquisition",
        output=ActionPlanNarrationOutput(text=text),
        offending_spans=((start, end),),
    )


@pytest.mark.asyncio
async def test_narration_drops_the_offending_sentence_instead_of_the_whole_prose() -> None:
    """narrative_only 步骤的兜底素材恒为空，所以先剔除违规小句再考虑状态播报。"""
    application = object.__new__(ActionPlanTurnApplication)
    text = "你在门厅站定，四下打量。你把传单收进外套口袋。远处传来钟声。"
    offending = "你把传单收进外套口袋。"
    start = text.index(offending)
    narrator = _ValidatingNarrator(_rejection_with_span(text, start, start + len(offending)))
    application._narrator = narrator
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="环境恢复正常。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narrator.narrate_calls == 2
    assert narration.text == "你在门厅站定，四下打量。远处传来钟声。"
    assert narrator.validate_calls == ["你在门厅站定，四下打量。远处传来钟声。"]


@pytest.mark.asyncio
async def test_narration_falls_back_to_status_only_when_nothing_survives() -> None:
    """整段都是违规内容时仍旧落到确定性兜底，不能拼出未校验的碎片。"""
    application = object.__new__(ActionPlanTurnApplication)
    text = "你把传单收进外套口袋。"
    narrator = _ValidatingNarrator(_rejection_with_span(text, 0, len(text)))
    application._narrator = narrator
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="环境恢复正常。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narration.text == "这次行动已经按当前可确认的结果完成。"
    assert narrator.validate_calls == []


@pytest.mark.asyncio
async def test_narration_keeps_whole_prose_fallback_when_rejection_has_no_span() -> None:
    """无法定位到具体句子的拒绝类别行为不变，仍走原有兜底。"""
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(
        side_effect=[
            ActionPlanNarrationValidationError("subject_ownership"),
            ActionPlanNarrationValidationError("subject_ownership"),
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="环境恢复正常。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narration.text == "这次行动已经按当前可确认的结果完成。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "persistent_claim_without_evidence:inventory_acquisition",
            "claimed_inventory_ids",
        ),
        ("inventory_claim_scope", "claimed_inventory_ids"),
        ("state_claim_scope", "claimed_state_changes"),
    ],
)
async def test_narration_retry_hint_points_at_the_declaration_field(
    reason: str,
    expected: str,
) -> None:
    """申报类拒绝必须给出可操作的出路；通用提示在 narrative_only 上无从执行。"""
    application = object.__new__(ActionPlanTurnApplication)
    success = SimpleNamespace(kind="narration", text="环境恢复正常。", npc_replies=())
    narrate = AsyncMock(side_effect=[ActionPlanNarrationValidationError(reason), success])
    application._narrator = SimpleNamespace(narrate=narrate)
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            NarrationEvidence(
                ref="evt-1",
                kind="entity_discovered",
                subject_id="x",
                subject_name="公开结果",
                description="环境恢复正常。",
                required_in_narration=False,
            ),
            "resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narration is success
    retry_hint = narrate.await_args_list[1].args[0].narration_retry_hint
    assert expected in retry_hint


def _evidence() -> NarrationEvidence:
    return NarrationEvidence(
        ref="evt-1",
        kind="entity_discovered",
        subject_id="x",
        subject_name="公开结果",
        description="环境恢复正常。",
        required_in_narration=False,
    )


@pytest.mark.asyncio
async def test_npc_dialogue_rejection_retries_with_an_actionable_hint() -> None:
    """重试必须明确区分守秘人正文与 NPC 回复，避免原样重写后再次被拒。"""
    application = object.__new__(ActionPlanTurnApplication)
    success = SimpleNamespace(kind="narration", text="他简短地回答。", npc_replies=())
    narrate = AsyncMock(
        side_effect=[
            ActionPlanNarrationValidationError("npc_dialogue_embedded_in_text"),
            success,
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    context = cast(ActionPlanNarrationContext, _NarrationContextStub(_evidence(), "resolved"))

    narration = await application._narrate(context)

    assert narration is success
    retry_hint = narrate.await_args_list[1].args[0].narration_retry_hint
    assert "NPC 台词" in retry_hint
    assert "text" in retry_hint
    assert "npc_replies" in retry_hint


@pytest.mark.asyncio
async def test_at_npc_fallback_still_produces_a_reply_bubble() -> None:
    """玩家 @ 了 NPC 却连拒两次时，兜底也必须让那个 NPC 开口。"""
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(
        side_effect=[
            ActionPlanNarrationValidationError("subject_ownership"),
            ActionPlanNarrationValidationError("subject_ownership"),
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    james = SimpleNamespace(id="james", kind="npc", name="詹姆斯·莱恩")
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(
            _evidence(),
            "resolved",
            interlocutor_id="james",
            visible_entities=(james,),
        ),
    )

    narration = await application._narrate(context)

    assert narration.text == "这次行动已经按当前可确认的结果完成。"
    assert [reply.speaker_id for reply in narration.npc_replies] == ["james"]


@pytest.mark.asyncio
async def test_quoted_npc_line_is_dropped_sentence_wise_instead_of_the_whole_prose() -> None:
    """守秘人正文里的引语被整段引区间剔除，其余叙事保留。"""
    application = object.__new__(ActionPlanTurnApplication)
    text = "詹姆斯抬起头。他说：“我是詹姆斯。你们别担心。”窗外传来蛙鸣。"
    quoted_start = text.index("他说")
    quoted_end = text.index("窗外")
    narrator = _ValidatingNarrator(
        ActionPlanNarrationValidationError(
            "npc_dialogue_embedded_in_text",
            output=ActionPlanNarrationOutput(text=text),
            offending_spans=((quoted_start, quoted_end),),
        )
    )
    application._narrator = narrator
    context = cast(ActionPlanNarrationContext, _NarrationContextStub(_evidence(), "resolved"))

    narration = await application._narrate(context)

    assert narration.text == "詹姆斯抬起头。窗外传来蛙鸣。"
    assert "你们别担心" not in narration.text


def test_disclosure_source_maps_index_without_leaking_the_term() -> None:
    """命中禁词只还原成来源 id；禁词字面值是未公开剧情，绝不能落盘。"""
    from app.core.action_plan_turn import _disclosure_source

    sources = ("information:frog_resort_flyer:title", "entity:messenger:name")
    hit = ActionPlanNarrationValidationError("hidden_disclosure", disclosure_term_index=1)
    assert _disclosure_source(hit, sources) == "entity:messenger:name"

    # 越界或缺失时安静返回 None，不能让诊断字段本身把日志写崩。
    for index in (None, -1, 2):
        exc = ActionPlanNarrationValidationError("hidden_disclosure", disclosure_term_index=index)
        assert _disclosure_source(exc, sources) is None
    assert _disclosure_source(hit, ()) is None


def test_required_evidence_fallback_omits_second_person_description_in_named_actor() -> None:
    context = SimpleNamespace(
        addressing_mode="named_actor",
        acting_character_name="陈探员",
        narration_evidence=(
            NarrationEvidence(
                ref="evt-road-discovered",
                kind="entity_discovered",
                subject_id="kimball-road",
                subject_name="宅外道路",
                description="你可以在阴影中观察周围动静。",
                required_in_narration=True,
            ),
        ),
    )

    output = ActionPlanTurnApplication._required_evidence_fallback(cast(Any, context))

    assert "陈探员" in output.text
    assert "宅外道路" in output.text
    assert "你可以在阴影中观察周围动静" not in output.text
    assert output.claimed_evidence_refs == ("evt-road-discovered",)


def test_required_evidence_fallback_keeps_description_in_second_person() -> None:
    context = SimpleNamespace(
        addressing_mode="second_person",
        acting_character_name="陈探员",
        narration_evidence=(
            NarrationEvidence(
                ref="evt-road-discovered",
                kind="entity_discovered",
                subject_id="kimball-road",
                subject_name="宅外道路",
                description="你可以在阴影中观察周围动静。",
                required_in_narration=True,
            ),
        ),
    )

    output = ActionPlanTurnApplication._required_evidence_fallback(cast(Any, context))

    assert "你可以在阴影中观察周围动静" in output.text
    assert output.claimed_evidence_refs == ("evt-road-discovered",)


@pytest.mark.asyncio
async def test_required_evidence_fallback_never_changes_clarification_scope() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(side_effect=ActionPlanNarrationValidationError("required_evidence_missing"))
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-crypt-discovered",
        kind="entity_discovered",
        subject_id="crypt_entrance",
        subject_name="石板下的地穴入口",
        required_in_narration=True,
    )
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(evidence, "needs_clarification"),
    )

    narration = await application._narrate(context)

    assert narration.kind == "clarification"
    assert evidence.subject_name in narration.text
    assert narration.claimed_evidence_refs == (evidence.ref,)
    assert narrate.await_count == 2


@pytest.mark.asyncio
async def test_narration_retries_unreadable_structured_output_then_uses_safe_fallback() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(
        side_effect=[
            StructuredOutputError("response is not valid structured output"),
            StructuredOutputError("response is still not valid structured output"),
        ]
    )
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-1",
        kind="entity_discovered",
        subject_id="x",
        subject_name="公开结果",
        description="结果已确认。",
        required_in_narration=False,
    )
    context = cast(
        ActionPlanNarrationContext,
        _NarrationContextStub(evidence, "resolved"),
    )

    narration = await application._narrate(context)

    assert narrate.await_count == 2
    assert narration.kind == "narration"
    assert "公开结果" not in narration.text


@pytest.mark.asyncio
async def test_resume_owned_recovers_intent_after_crash_before_engine_write() -> None:
    run = _run(cancel_id="cancel-original")
    engine = _Engine(_status("awaiting_post_roll_decision"))
    orchestrator = _Orchestrator(run)
    application = _application(run, engine, orchestrator)

    result = await application.resume_owned(
        room_id=run.room_id,
        player_id=run.player_id,
        parent_action_id=run.parent_action_id,
    )

    assert result == "recovered"
    assert len(engine.post_roll_requests) == 1
    request = engine.post_roll_requests[0]
    assert request.request_id == "cancel-original:accept-current"
    assert request.source_revision == "revision-7"
    assert request.check_id == "check-281"
    assert len(orchestrator.resume_calls) == 1


@pytest.mark.asyncio
async def test_cancel_retry_reconciles_resolved_engine_after_crash_before_plan_write() -> None:
    run = _run(cancel_id="cancel-original")
    engine = _Engine(_status("resolved"))
    orchestrator = _Orchestrator(run)
    application = _application(run, engine, orchestrator)

    result = await application.cancel_remaining(
        room_id=run.room_id,
        player_id=run.player_id,
        parent_action_id=run.parent_action_id,
        request_id="cancel-retry-with-new-id",
    )

    assert result == "recovered"
    assert engine.post_roll_requests == []
    assert len(orchestrator.resume_calls) == 1
    assert orchestrator.resume_calls[0]["parent_action_id"] == run.parent_action_id


@pytest.mark.parametrize("last_error", ["atmosphere_repeat", "outer_schema", "structured"])
@pytest.mark.parametrize("status", ["resolved", "needs_clarification"])
async def test_confirmed_information_survives_retry_exhaustion(last_error, status):
    evidence = NarrationEvidence(
        ref="evt-information",
        kind="information_revealed",
        subject_id="refusal",
        subject_name="拒绝离开",
        description="你听见明确的答复：“今晚不能离开，必须等到明天。”",
        required_in_narration=True,
    )
    errors = [ActionPlanNarrationValidationError("required_evidence_missing")]
    errors.append(
        StructuredOutputError("invalid")
        if last_error == "structured"
        else ActionPlanNarrationValidationError(last_error)
    )
    app = object.__new__(ActionPlanTurnApplication)
    app._narrator = SimpleNamespace(narrate=AsyncMock(side_effect=errors))
    context = cast(ActionPlanNarrationContext, _NarrationContextStub(evidence, status))
    output = await app._narrate(context)
    assert evidence.description in output.text
    assert output.claimed_evidence_refs == (evidence.ref,)
    assert output.kind == ("clarification" if status == "needs_clarification" else "narration")
    assert app._narrator.narrate.await_count == 2


def test_travel_intent_with_success_but_no_location_result_does_not_claim_arrival():
    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(utterance="去旅店", client_action_id="no-travel"),
        completed_steps=(
            SimpleNamespace(outcome="success", semantic_goal="前往旅店", committed_results=()),
        ),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(id="street", name="街道", visible_entities=())
        ),
    )
    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))
    assert "抵达" not in output.text


@pytest.mark.parametrize(
    ("text", "claimed_inventory_ids", "accepted"),
    [
        pytest.param("你握着铅笔刀，仔细查看挂画。", ("pencil_knife",), True, id="carried-item"),
        pytest.param("床下藏着一把备用钥匙。", (), False, id="undiscovered-item"),
        pytest.param("你把暗格钥匙收进背包。", ("wall_key",), False, id="visible-but-not-owned"),
        pytest.param("铅笔刀的刀柄里藏着密文。", (), False, id="carried-item-secret"),
        pytest.param("同伴口袋里有一枚铜哨。", (), False, id="other-actor-private-item"),
    ],
)
async def test_narration_treats_inventory_as_public_without_releasing_hidden_content(
    text: str, claimed_inventory_ids: tuple[str, ...], accepted: bool
) -> None:
    player_input = PlayerInput(
        room_id="inventory-narration",
        player_id="player-1",
        actor_id="actor-1",
        client_action_id="inspect-painting",
        utterance="仔细查看挂画",
    )
    view = PlayerView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        background="调查员正在密室中寻找线索。",
        scene_id="room",
        phase="playing",
        revision="13",
        self_actor=SelfActorView(id="actor-1", name="调查员"),
        scene=SceneView(
            id="room",
            name="密室",
            description="墙上挂着一幅画。",
            visible_entities=(
                VisibleEntity(
                    id="wall_key", kind="object", name="暗格钥匙", description="暗格中的钥匙。"
                ),
            ),
        ),
        inventory=(
            InventoryItemView(
                id="pencil_knife", name="铅笔刀", quantity=1, condition="intact", version=1
            ),
        ),
    )
    capabilities = KeeperCapabilityView(
        room_id=player_input.room_id,
        actor_id=player_input.actor_id,
        revision=view.revision,
        entities=(
            KeeperEntityCapability(
                id="pencil_knife",
                name="铅笔刀",
                kind="object",
                origin="canon",
                holder_actor_id="actor-1",
            ),
            KeeperEntityCapability(id="wall_key", name="暗格钥匙", kind="object", origin="canon"),
            KeeperEntityCapability(id="bed_key", name="备用钥匙", kind="object", origin="canon"),
            KeeperEntityCapability(
                id="whistle",
                name="铜哨",
                kind="object",
                origin="canon",
                holder_actor_id="actor-2",
            ),
        ),
        information=(
            KeeperInformationCapability(
                id="knife_secret",
                title="刀柄密文",
                summary="刀柄中的秘密",
                content="铅笔刀的刀柄里藏着密文。",
                related_entities=("pencil_knife",),
            ),
        ),
    )
    context = ActionPlanNarrationContext(
        background=view.background,
        player_input=player_input,
        plan_goal=player_input.utterance,
        termination_status="resolved",
        player_view=view,
    )
    safe_retry = "你继续查看挂画。"
    generate = AsyncMock(
        side_effect=[
            {"text": text, "claimed_inventory_ids": claimed_inventory_ids},
            {"text": safe_retry},
        ]
    )

    class Model:
        async def generate(self, context: ActionPlanNarrationContext) -> object:
            return await generate(context)

    application = object.__new__(ActionPlanTurnApplication)
    application._narrator = ActionPlanNarrator(Model())
    application._keeper_capabilities = AsyncMock(return_value=capabilities)
    application._memory_source = None
    application._recent_history_enabled = False
    application._recent_history_source = SimpleNamespace()

    output = await application._narrate(context)

    assert generate.await_count == (1 if accepted else 2)
    assert output.text == (text if accepted else safe_retry)
    assert output.claimed_inventory_ids == (claimed_inventory_ids if accepted else ())


@pytest.mark.parametrize("keep_literal_source", [False, True])
def test_sentence_degradation_rechecks_information_after_removing_model_claims(
    keep_literal_source: bool,
) -> None:
    fact = NarrationEvidence(
        ref="map-revealed",
        kind="information_revealed",
        subject_id="map",
        subject_name="楼层地图",
        description="楼上有八间客房，进入需要许可。",
        required_in_narration=True,
    )
    player_input = PlayerInput(
        room_id="room",
        player_id="player",
        actor_id="actor",
        client_action_id="arrival",
        utterance="进入大厅",
    )
    view = PlayerView(
        room_id="room",
        player_id="player",
        actor_id="actor",
        background="调查旅店。",
        scene_id="hall",
        phase="playing",
        revision="2",
        self_actor=SelfActorView(id="actor", name="调查员"),
        scene=SceneView(
            id="hall",
            name="接待大厅",
            description="大厅有前台和地图。",
            visible_entities=(
                VisibleEntity(id="clerk", kind="npc", name="接待员", description=""),
                VisibleEntity(id="map", kind="object", name="楼层地图", description=""),
            ),
            available_exits=(AvailableExitView(id="upstairs", name="二楼客房"),),
        ),
    )
    step = CompletedPlanStepSummary(
        step_index=0,
        semantic_goal="进入大厅",
        outcome="success",
        view_revision="2",
        event_refs=("arrived", fact.ref),
        narration_evidence=(fact,),
        committed_results=(
            CommittedResult(kind="location", target_id="hall", event_ref="arrived"),
        ),
    )
    context = ActionPlanNarrationContext(
        background=view.background,
        player_input=player_input,
        plan_goal="进入大厅",
        termination_status="resolved",
        player_view=view,
        completed_steps=(step,),
        narration_evidence=(fact,),
        allowed_evidence_refs=step.event_refs,
    )
    prefix = "你走进接待大厅。" + (fact.description if keep_literal_source else "")
    removed = "楼上的八间房都需要获准才能进入，有人喊：“快走！”"
    candidate = ActionPlanNarrationOutput(text=prefix + removed, claimed_evidence_refs=(fact.ref,))
    error = ActionPlanNarrationValidationError(
        "npc_dialogue_embedded_in_text",
        output=candidate,
        offending_spans=((len(prefix), len(candidate.text)),),
    )
    app = object.__new__(ActionPlanTurnApplication)
    app._narrator = ActionPlanNarrator(cast(Any, None))
    output = app._sentence_degraded_narration(context, error)
    if keep_literal_source:
        assert output is not None
        assert output.text == prefix
        assert output.claimed_evidence_refs == (fact.ref,)
    else:
        assert output is None
        fallback = app._deterministic_narration_fallback(context)
        for required in (
            view.scene.name,
            "前台",
            "接待员",
            "楼层地图",
            "二楼客房",
            fact.description,
        ):
            assert required in fallback.text
        assert set(fallback.claimed_evidence_refs) == {"arrived", fact.ref}
        assert "周围可见：" not in fallback.text
        assert "可见出口：" not in fallback.text
        assert "\n\n" in fallback.text
