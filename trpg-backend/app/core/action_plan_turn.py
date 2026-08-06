"""Production composition for issue #225 finite ActionPlan turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    ActionTarget,
    AdjudicationExecution,
    CancelActionPlanRequest,
    HostTurnDecision,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PlayerView,
    SingleActionDecision,
)
from collaboration_framework.engine import AdjudicationEngineService, EngineStore, RuleEngineService
from collaboration_framework.host.adapters import InMemoryActionPlanRunStore
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
    ActionPlanOrchestrator,
    HostTurnDecisionExecutor,
    PlayerViewProjector,
    TurnExecutionError,
)
from collaboration_framework.host.schemas import (
    ActionPlanAdvanceResult,
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
    CompletedPlanStepSummary,
    HostAgentContext,
    RecentTurnContext,
    SingleActionTurnResult,
)


class HostTurnDecisionModel(Protocol):
    async def generate(self, context: HostAgentContext) -> HostTurnDecision: ...


@dataclass(frozen=True)
class ActionPlanTurnResult:
    player_input: PlayerInput
    player_view: PlayerView
    status: str
    execution: AdjudicationExecution | None = None
    narration: ActionPlanNarrationOutput | None = None
    plan_id: str | None = None

    @property
    def waiting_for_player(self) -> bool:
        return self.status == "waiting_for_player"


class DeterministicHostTurnDecisionModel:
    """Offline-safe model used only by fake/test composition."""

    async def generate(self, context: HostAgentContext) -> HostTurnDecision:
        utterance = context.player_input.utterance
        separators = ("然后", "接着", "随后", "再去", "，再", ";", "；")
        pieces = [utterance]
        for separator in separators:
            if separator in utterance:
                pieces = [part.strip(" ，,。") for part in utterance.split(separator)]
                pieces = [part for part in pieces if part]
                break
        if len(pieces) >= 2:
            return ActionPlan(
                goal=utterance,
                steps=tuple(
                    ActionPlanStep(
                        kind=(
                            "travel"
                            if any(word in part for word in ("去", "前往", "进入"))
                            else "action"
                        ),
                        semantic_goal=part,
                    )
                    for part in pieces
                ),
            )
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=utterance,
                target=ActionTarget(kind="location", id=context.player_view.scene.id),
                method=ActionMethod(family="action", description=utterance),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        )


class DeterministicActionPlanNarrationModel:
    async def generate(self, context: ActionPlanNarrationContext) -> object:
        completed = "；".join(step.semantic_goal for step in context.completed_steps)
        if context.termination_status == "needs_clarification":
            text = f"已经完成的行动是：{completed}。接下来的目标还不够明确，你想具体怎么做？"
            kind = "clarification"
        elif context.termination_status in {"cancelled", "stopped"}:
            text = f"已经发生的行动是：{completed or '当前没有已完成步骤'}。后续行动已停止。"
            kind = "narration"
        else:
            text = f"你依次完成了：{completed or context.plan_goal}。"
            kind = "narration"
        return {
            "kind": kind,
            "text": text,
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class ActionPlanTurnApplication:
    def __init__(
        self,
        *,
        store: EngineStore,
        engine: RuleEngineService,
        adjudication_engine: AdjudicationEngineService,
        planner: HostTurnDecisionModel,
        orchestrator: ActionPlanOrchestrator,
        narrator: ActionPlanNarrator,
    ) -> None:
        self._store = store
        self._engine = engine
        self._adjudication_engine = adjudication_engine
        self._planner = planner
        self._orchestrator = orchestrator
        self._narrator = narrator
        self._projector = PlayerViewProjector(engine)
        self._dispatcher = HostTurnDecisionExecutor(
            plan_orchestrator=orchestrator,
            executor=adjudication_engine,
            player_view_projector=self._projector,
        )

    async def start(
        self,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        utterance: str,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
        on_input_accepted: (Callable[[PlayerInput, PlayerView], Awaitable[None]] | None) = None,
    ) -> ActionPlanTurnResult:
        actor_id = await self._resolve_actor_id(room_id, player_id)
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            utterance=utterance,
        )
        existing = await self._orchestrator.get_run(room_id, client_action_id)
        if existing is not None:
            advanced = await self._orchestrator.start_or_resume(
                player_input,
                plan=None,
                on_progress=on_progress,
            )
            return await self._from_plan(player_input, advanced)

        view = await self._projector.project(player_input)
        if on_input_accepted is not None:
            await on_input_accepted(player_input, view)
        decision = await self._planner.generate(
            HostAgentContext(
                player_input=player_input,
                player_view=view,
                recent_history=RecentTurnContext.empty(
                    player_input=player_input,
                    player_view=view,
                ),
            )
        )
        result = await self._dispatcher.execute(
            player_input,
            decision,
            on_progress=on_progress,
        )
        if isinstance(result, ActionPlanAdvanceResult):
            return await self._from_plan(player_input, result)
        return await self._from_single(player_input, decision, result)

    async def resume_plan(
        self,
        player_input: PlayerInput,
        *,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
    ) -> ActionPlanTurnResult:
        advanced = await self._orchestrator.start_or_resume(
            player_input,
            plan=None,
            on_progress=on_progress,
        )
        return await self._from_plan(player_input, advanced)

    async def resume_owned(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
    ) -> ActionPlanTurnResult:
        actor_id = await self._resolve_actor_id(room_id, player_id)
        advanced = await self._orchestrator.resume_owned(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            parent_action_id=parent_action_id,
            on_progress=on_progress,
        )
        run = advanced.run
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=parent_action_id,
            utterance=run.plan.goal,
        )
        return await self._from_plan(
            player_input,
            advanced,
            verify_fingerprint=False,
        )

    async def active_for_room(self, room_id: str):
        return await self._orchestrator.active_for_room(room_id)

    async def get_plan(self, room_id: str, parent_action_id: str):
        return await self._orchestrator.get_run(room_id, parent_action_id)

    async def cancel_remaining(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        request_id: str,
    ) -> ActionPlanTurnResult:
        actor_id = await self._resolve_actor_id(room_id, player_id)
        run = await self._orchestrator.cancel_remaining(
            CancelActionPlanRequest(
                request_id=request_id,
                room_id=room_id,
                player_id=player_id,
                actor_id=actor_id,
                parent_action_id=parent_action_id,
            )
        )
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=parent_action_id,
            utterance=run.plan.goal,
        )
        result = ActionPlanAdvanceResult(
            run=run,
            player_view=await self._projector.project(player_input),
        )
        return await self._from_plan(
            player_input,
            result,
            verify_fingerprint=False,
        )

    async def mark_narration_persisted(
        self,
        *,
        room_id: str,
        parent_action_id: str,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
    ) -> None:
        active = await self._orchestrator.active_for_room(room_id)
        if (
            active is not None
            and active.parent_action_id == parent_action_id
            and active.status == "awaiting_narration"
        ):
            await self._orchestrator.mark_narration_completed(
                room_id=room_id,
                parent_action_id=parent_action_id,
                on_progress=on_progress,
            )

    async def _from_plan(
        self,
        player_input: PlayerInput,
        result: ActionPlanAdvanceResult,
        *,
        verify_fingerprint: bool = True,
    ) -> ActionPlanTurnResult:
        run = result.run
        if run.status == "waiting_for_player":
            return ActionPlanTurnResult(
                player_input=player_input,
                player_view=result.player_view,
                status=run.status,
                execution=result.latest_execution,
                plan_id=run.plan_id,
            )
        if run.status == "retryable_failure":
            raise TurnExecutionError(
                run.steps[run.current_step_index].safe_failure_code or "PLAN_RETRYABLE_FAILURE",
                "前序步骤已经保存，当前步骤暂时失败；请使用原请求重试",
                retryable=True,
            )
        if run.status not in {
            "awaiting_narration",
            "completed",
            "needs_clarification",
            "cancelled",
            "stopped",
        }:
            raise TurnExecutionError(
                "PLAN_NOT_SETTLED",
                "行动计划尚未到达可返回状态",
                retryable=True,
            )
        context = await self._orchestrator.build_narration_context(
            player_input,
            verify_fingerprint=verify_fingerprint,
        )
        narration = await self._narrate(context)
        return ActionPlanTurnResult(
            player_input=player_input,
            player_view=context.player_view,
            status=run.status,
            execution=result.latest_execution,
            narration=narration,
            plan_id=run.plan_id,
        )

    async def _from_single(
        self,
        player_input: PlayerInput,
        decision: HostTurnDecision,
        result: SingleActionTurnResult,
    ) -> ActionPlanTurnResult:
        if not isinstance(decision, SingleActionDecision):
            raise TypeError("single result 必须对应 SingleActionDecision")
        execution = result.execution
        if execution.status in {"awaiting_skill_choice", "awaiting_post_roll_decision"}:
            return ActionPlanTurnResult(
                player_input=player_input,
                player_view=result.player_view,
                status="waiting_for_player",
                execution=execution,
            )
        if execution.outcome == "success":
            completed_outcome = "success"
        elif execution.outcome == "failure":
            completed_outcome = "failure"
        elif execution.outcome == "cancelled":
            completed_outcome = "cancelled"
        else:
            raise TurnExecutionError(
                "PENDING_EXECUTION_NOT_WAITING",
                "行动状态尚未完成，请重试",
                retryable=True,
            )
        summary = CompletedPlanStepSummary(
            step_index=0,
            semantic_goal=decision.adjudication.summary,
            outcome=completed_outcome,
            view_revision=execution.view_revision,
            event_refs=execution.public_event_refs,
        )
        context = ActionPlanNarrationContext(
            background=result.player_view.background,
            player_input=player_input,
            plan_goal=decision.adjudication.summary,
            termination_status=("cancelled" if execution.status == "cancelled" else "resolved"),
            completed_steps=(summary,),
            player_view=result.player_view,
            allowed_evidence_refs=execution.public_event_refs,
        )
        return ActionPlanTurnResult(
            player_input=player_input,
            player_view=result.player_view,
            status="completed",
            execution=execution,
            narration=await self._narrate(context),
        )

    async def _narrate(
        self,
        context: ActionPlanNarrationContext,
    ) -> ActionPlanNarrationOutput:
        for attempt in range(2):
            try:
                return await self._narrator.narrate(context)
            except ActionPlanNarrationValidationError as exc:
                if attempt == 1:
                    raise TurnExecutionError(
                        "PLAN_NARRATION_INVALID",
                        "规则结果已保存，但叙事未通过安全校验；请使用原请求重试",
                        retryable=True,
                    ) from exc
            except Exception as exc:
                raise TurnExecutionError(
                    "PLAN_NARRATOR_FAILED",
                    "规则结果已保存，但叙事生成失败；请使用原请求重试",
                    retryable=True,
                ) from exc
        raise AssertionError("unreachable")

    async def _resolve_actor_id(self, room_id: str, player_id: str) -> str:
        async with self._store.transaction(room_id) as transaction:
            runtime = await transaction.load_runtime()
        actors = [
            actor_id
            for actor_id, actor in runtime.game_state.actors.items()
            if actor.player_id == player_id
        ]
        if len(actors) != 1:
            raise TurnExecutionError(
                "ACTOR_NOT_CONTROLLED",
                "当前玩家没有唯一可控制的局内角色",
                retryable=False,
            )
        return actors[0]


def build_action_plan_turn_application(
    *,
    store: EngineStore,
    engine: RuleEngineService,
    adjudication_engine: AdjudicationEngineService,
    plan_store=None,
    settings=None,
    client=None,
) -> ActionPlanTurnApplication:
    """Compose the finite-plan path without changing the single-intent Engine."""

    from app.adapters import (
        DeepSeekChatCompletionsJsonClient,
        OpenAIResponsesJsonClient,
        PromptActionPlanNarrationModel,
        PromptActionPlanStepAdjudicator,
        PromptHostTurnDecisionModel,
        QwenChatCompletionsJsonClient,
    )
    from app.core.config import get_settings, secret_value

    resolved = settings or get_settings()
    policy = ActionPlanPolicy(
        max_plan_steps=resolved.action_plan_max_steps,
        max_steps_per_advance=resolved.action_plan_max_steps_per_advance,
    )
    if resolved.host_model_provider == "fake":
        planner = DeterministicHostTurnDecisionModel()
        adjudicator = _DeterministicStepAdjudicator()
        narration_model = DeterministicActionPlanNarrationModel()
    else:
        if client is None:
            if resolved.host_model_provider == "deepseek":
                client_type = DeepSeekChatCompletionsJsonClient
                api_key = resolved.deepseek_api_key
                base_url = resolved.deepseek_base_url
                model = resolved.deepseek_model
                timeout = resolved.deepseek_timeout_seconds
            elif resolved.host_model_provider == "qwen":
                client_type = QwenChatCompletionsJsonClient
                api_key = resolved.qwen_api_key
                base_url = resolved.qwen_base_url
                model = resolved.qwen_model
                timeout = resolved.qwen_timeout_seconds
            else:
                client_type = OpenAIResponsesJsonClient
                api_key = resolved.openai_api_key
                base_url = resolved.openai_base_url
                model = resolved.openai_model
                timeout = resolved.openai_timeout_seconds
            if api_key is None:
                raise ValueError("ActionPlan Host 模型缺少 API key")
            client = client_type(
                api_key=secret_value(api_key),
                base_url=base_url,
                model=model,
                timeout_seconds=timeout,
            )
        planner = PromptHostTurnDecisionModel(client, policy=policy)
        adjudicator = PromptActionPlanStepAdjudicator(client)
        narration_model = PromptActionPlanNarrationModel(client)

    plan_store = plan_store or InMemoryActionPlanRunStore()
    projector = PlayerViewProjector(engine)
    orchestrator = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=adjudicator,
        executor=adjudication_engine,
        player_view_projector=projector,
        policy=policy,
    )
    return ActionPlanTurnApplication(
        store=store,
        engine=engine,
        adjudication_engine=adjudication_engine,
        planner=planner,
        orchestrator=orchestrator,
        narrator=ActionPlanNarrator(narration_model),
    )


class _DeterministicStepAdjudicator:
    async def adjudicate(self, context):
        if context.step.kind in {"wait", "rest"}:
            raise TurnExecutionError(
                "STEP_KIND_UNSUPPORTED",
                "当前步骤需要尚未接入的时间/休息领域能力",
                retryable=False,
            )
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="location", id=context.player_view.scene.id),
            method=ActionMethod(
                family=context.step.kind,
                description=context.step.semantic_goal,
            ),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


__all__ = [
    "ActionPlanTurnApplication",
    "ActionPlanTurnResult",
    "DeterministicActionPlanNarrationModel",
    "DeterministicHostTurnDecisionModel",
    "HostTurnDecisionModel",
    "build_action_plan_turn_application",
]


def _production_application() -> ActionPlanTurnApplication:
    from app.core.engine import (
        action_plan_store,
        adjudication_engine_service,
        engine_store,
        rule_engine_service,
    )

    return build_action_plan_turn_application(
        store=engine_store,
        engine=rule_engine_service,
        adjudication_engine=adjudication_engine_service,
        plan_store=action_plan_store,
    )


action_plan_turn_application = _production_application()
__all__.append("action_plan_turn_application")
