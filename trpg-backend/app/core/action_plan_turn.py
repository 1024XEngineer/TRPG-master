"""Production composition for issue #225 finite ActionPlan turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import structlog
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    ActionTarget,
    AdjudicationExecution,
    CancelActionPlanRequest,
    CancelCheckChoice,
    CheckDecisionRequest,
    ContractError,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    HostTurnDecision,
    KeeperCapabilityView,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PlayerView,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
    SingleActionDecision,
    SkillCheckCandidate,
    WorldClockView,
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
from collaboration_framework.host.ports import ActionPlanStepAdjudicator, RecentHistorySource
from collaboration_framework.host.schemas import (
    ActionPlanAdvanceResult,
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
    ActionPlanStepContext,
    CompletedPlanStepSummary,
    HostAgentContext,
    RecentHistoryBudget,
    RecentTurnContext,
    SingleActionTurnResult,
)
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.turn_events import TurnPhase

logger = structlog.get_logger()

TurnPhaseObserver = Callable[[TurnPhase], Awaitable[None]]


async def _emit_phase(observer: TurnPhaseObserver | None, phase: TurnPhase) -> None:
    if observer is not None:
        await observer(phase)


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


@dataclass(frozen=True)
class _TravelTarget:
    id: str
    name: str


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

        compact = _compact_travel_plan(context.player_view, utterance)
        if compact is not None:
            return compact

        destination = _match_travel_target(context.player_view, utterance)
        if destination is not None:
            return SingleActionDecision(
                adjudication=ActionAdjudication(
                    request_id="application-owned",
                    source_revision=context.player_view.revision,
                    actor_id=context.player_input.actor_id,
                    summary=utterance,
                    target=ActionTarget(
                        kind="location",
                        id=destination.id,
                    ),
                    method=ActionMethod(family="travel", description=utterance),
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id=destination.id),),
                )
            )

        # A single action uses the same player-safe Rule Match View as a plan
        # step.  Without this bridge, the Fake planner returned narrative_only
        # for every non-travel utterance, so CI could exercise v3 rules only by
        # artificially wrapping one action in a multi-step plan.
        deterministic = _deterministic_step_adjudication(
            ActionPlanStepContext(
                player_input=context.player_input,
                plan_id="single-action",
                plan_goal=utterance,
                step_index=0,
                step_request_id="application-owned",
                step=ActionPlanStep(
                    kind=(
                        "dialogue"
                        if any(word in utterance for word in ("问", "交谈", "聊天"))
                        else "action"
                    ),
                    semantic_goal=utterance,
                ),
                player_view=context.player_view,
                keeper_capabilities=context.keeper_capabilities,
            )
        )
        if deterministic is not None:
            return SingleActionDecision(adjudication=deterministic)

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


def _compact_travel_plan(view: PlayerView, utterance: str) -> ActionPlan | None:
    """Split compact fake-provider phrases without consulting hidden ModuleContent."""

    destination = _match_travel_target(view, utterance)
    if destination is None:
        return None
    anchor = _best_label_overlap(
        utterance,
        (
            destination.name,
            destination.id,
        ),
    )
    if anchor is None:
        return None
    anchor_end = utterance.find(anchor) + len(anchor)
    remainder = utterance[anchor_end:].strip(" ，,。")
    action_markers = (
        "搜索",
        "调查",
        "查阅",
        "查找",
        "研究",
        "询问",
        "交谈",
        "找",
        "查",
        "问",
    )
    marker = next((item for item in action_markers if item in remainder), None)
    if marker is None:
        return None
    # Keep method qualifiers that precede the verb (for example “用侦查搜索”
    # or “用信用评级询问”).  Rule options are selected from those player-safe
    # words; slicing from the verb silently discarded the only discriminating
    # evidence and made the step fall back to narrative_only.
    follow_up = remainder.strip(" ，,。")
    if not follow_up:
        return None
    destination_name = destination.name
    return ActionPlan(
        goal=utterance,
        steps=(
            ActionPlanStep(kind="travel", semantic_goal=f"前往{destination_name}"),
            ActionPlanStep(
                kind=(
                    "dialogue" if any(word in follow_up for word in ("问", "交谈")) else "action"
                ),
                semantic_goal=f"在{destination_name}{follow_up}",
            ),
        ),
    )


def _match_visible_exit(view: PlayerView, text: str):
    if not any(word in text for word in ("去", "前往", "进入", "到", "抵达")):
        return None
    matches = []
    for exit_view in view.scene.available_exits:
        destination_labels = (
            (exit_view.destination.name, exit_view.destination.scene_id)
            if exit_view.destination
            else ()
        )
        labels = (
            exit_view.name,
            exit_view.id,
            *exit_view.aliases,
            *destination_labels,
        )
        overlap = _best_label_overlap(text, labels)
        if overlap is not None:
            matches.append((len(overlap), exit_view.id, exit_view))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][2]


"""普通环境地点：现实中理应遍地都是、不承载任何剧情秘密的那类去处。

只收录「模组不写、但世界里一定有」的通用场所。任何可能是关键地点的词
（教堂、警局、医院、码头……）都不在这里——那些必须由模组作者写出来，
或者由 Agent 在完整上下文里判断，不能由这张表凭空造出来。
"""
_AMBIENT_VENUE_LABELS: tuple[tuple[str, str, str], ...] = (
    ("旅店", "ambient_inn", "镇上的旅店"),
    ("旅馆", "ambient_inn", "镇上的旅店"),
    ("客栈", "ambient_inn", "镇上的旅店"),
    ("寄宿屋", "ambient_boarding_house", "出租床位的寄宿屋"),
    ("住处", "ambient_boarding_house", "出租床位的寄宿屋"),
    ("餐馆", "ambient_diner", "街边的餐馆"),
    ("饭馆", "ambient_diner", "街边的餐馆"),
    ("餐厅", "ambient_diner", "街边的餐馆"),
    ("咖啡馆", "ambient_cafe", "街角的咖啡馆"),
    ("杂货店", "ambient_general_store", "街边的杂货店"),
    ("商店", "ambient_general_store", "街边的杂货店"),
)

_AMBIENT_VENUE_INTENT_WORDS = ("找", "去", "前往", "进入", "到", "住", "休息", "睡")


def _ambient_venue_adjudication(
    context: ActionPlanStepContext,
) -> ActionAdjudication | None:
    """把「找一家旅店」这类泛指去处，确定性地落成一个运行时地点。

    只在三件事同时成立时才动手：说的是一个普通场所、玩家确实想去、而且它
    和模组写过的任何地点都不重名。第三条是关键——重名意味着这可能是一个
    隐藏的 Canon 地点（比如地下酒吧），那就必须留给模组自己揭示，绝不能由
    这里凭空造一个同名替身出来。
    """

    goal = context.step.semantic_goal
    if not any(word in goal for word in _AMBIENT_VENUE_INTENT_WORDS):
        return None
    matched = next(
        ((label, id_stem, name) for label, id_stem, name in _AMBIENT_VENUE_LABELS if label in goal),
        None,
    )
    if matched is None:
        return None
    label, id_stem, display_name = matched

    capabilities = context.keeper_capabilities
    if capabilities is None:
        return None
    # 和任何已写地点（含隐藏地点）重名就退出，交给模型在完整上下文里判断。
    for location in capabilities.locations:
        if label in location.name or location.name in goal:
            return None
    if any(location.id == id_stem for location in capabilities.locations):
        return None

    anchor_id = _ambient_venue_anchor(context.player_view)
    if anchor_id is None:
        return None

    return ActionAdjudication(
        request_id=context.step_request_id,
        source_revision=context.player_view.revision,
        actor_id=context.player_input.actor_id,
        summary=goal,
        # 目标仍是作为连接锚点的既有地点：新地点这一刻还不存在。
        target=ActionTarget(kind="location", id=anchor_id),
        method=ActionMethod(family="travel", description=goal),
        check=NoAdjudicationCheck(),
        success_effects=(
            EnsureRuntimeLocationEffect(
                location_id=id_stem,
                name=display_name,
                connected_location_id=anchor_id,
            ),
            EnterLocationEffect(location_id=id_stem),
        ),
    )


def _ambient_venue_anchor(view: PlayerView) -> str | None:
    """普通去处应当挂在公共路网上，而不是你此刻站着的那间私人书房。"""

    for location in view.known_locations:
        if (
            location.kind == "connector"
            and location.existence == "known"
            and location.localization == "located"
            and location.access != "blocked"
        ):
            return location.id
    return view.scene.id or None


def _match_travel_target(view: PlayerView, text: str) -> _TravelTarget | None:
    if not any(word in text for word in ("去", "前往", "进入", "到", "抵达")):
        return None
    matches: list[tuple[int, str, _TravelTarget]] = []
    for location in view.known_locations:
        if location.existence != "known" or location.localization != "located":
            continue
        overlap = _best_label_overlap(text, (location.name, location.id))
        if overlap is not None:
            matches.append((len(overlap), location.id, _TravelTarget(location.id, location.name)))
    for exit_view in view.scene.available_exits:
        if exit_view.destination is None:
            continue
        labels = (
            exit_view.name,
            exit_view.id,
            *exit_view.aliases,
            exit_view.destination.name,
            exit_view.destination.scene_id,
        )
        overlap = _best_label_overlap(text, labels)
        if overlap is not None:
            target = _TravelTarget(
                exit_view.destination.scene_id,
                exit_view.destination.name,
            )
            matches.append((len(overlap), target.id, target))
    if not matches:
        return None
    # The same location can be present in both known_locations and immediate exits.
    deduplicated = {
        target.id: (score, target_id, target)
        for score, target_id, target in matches
        if score == max(item[0] for item in matches if item[2].id == target.id)
    }
    ranked = sorted(deduplicated.values(), key=lambda item: (-item[0], item[1]))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][2]


def _best_label_overlap(text: str, labels: tuple[str, ...]) -> str | None:
    candidates: set[str] = set()
    for label in labels:
        normalized = label.strip()
        if not normalized:
            continue
        if normalized in text:
            candidates.add(normalized)
        if any("一" <= character <= "鿿" for character in normalized):
            for width in range(len(normalized), 1, -1):
                for start in range(len(normalized) - width + 1):
                    candidate = normalized[start : start + width]
                    if candidate in text:
                        candidates.add(candidate)
                if candidates:
                    break
    return max(candidates, key=lambda item: (len(item), item)) if candidates else None


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
        recent_history_source: RecentHistorySource,
        recent_history_budget: RecentHistoryBudget,
        recent_history_enabled: bool,
    ) -> None:
        self._store = store
        self._engine = engine
        self._adjudication_engine = adjudication_engine
        self._planner = planner
        self._orchestrator = orchestrator
        self._recent_history_source = recent_history_source
        self._recent_history_budget = recent_history_budget
        self._recent_history_enabled = recent_history_enabled
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
        on_phase: TurnPhaseObserver | None = None,
        on_input_accepted: (Callable[[PlayerInput, PlayerView], Awaitable[None]] | None) = None,
    ) -> ActionPlanTurnResult:
        await _emit_phase(on_phase, "reading_player_view")
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
            await _emit_phase(on_phase, "executing_action")
            advanced = await self._orchestrator.start_or_resume(
                player_input,
                plan=None,
                on_progress=on_progress,
            )
            return await self._finish_plan_with_phases(
                player_input,
                advanced,
                on_phase=on_phase,
            )

        # A plan stuck in needs_clarification never produced any committed step
        # effect (see ActionPlanOrchestrator.cancel_remaining's boundary check),
        # so it is always safe to fold into the next turn. The player's new
        # utterance is handed to the planner together with recent history
        # (including the clarifying question itself); the model decides whether
        # this is an answer to that question (multi-step) or unrelated fresh
        # input, instead of the transport layer blocking on a stale plan_id.
        stale_plan = await self._orchestrator.active_for_room(room_id)
        if (
            stale_plan is not None
            and stale_plan.parent_action_id != client_action_id
            and stale_plan.status == "needs_clarification"
            and stale_plan.player_id == player_id
        ):
            await self._orchestrator.cancel_remaining(
                CancelActionPlanRequest(
                    request_id=f"auto-supersede-{client_action_id}",
                    room_id=room_id,
                    player_id=player_id,
                    actor_id=actor_id,
                    parent_action_id=stale_plan.parent_action_id,
                )
            )

        view = await self._projector.project(player_input)
        if on_input_accepted is not None:
            await on_input_accepted(player_input, view)
        await _emit_phase(on_phase, "understanding_action")
        decision = await self._planner.generate(
            HostAgentContext(
                player_input=player_input,
                player_view=view,
                recent_history=await self._read_recent_history(
                    player_input=player_input,
                    player_view=view,
                ),
                # A single action is adjudicated right here in the planner call,
                # so it needs the same Keeper vocabulary a plan step gets.
                keeper_capabilities=await self._keeper_capabilities(player_input, view),
            )
        )
        await _emit_phase(on_phase, "executing_action")
        result = await self._dispatcher.execute(
            player_input,
            decision,
            on_progress=on_progress,
        )
        if isinstance(result, ActionPlanAdvanceResult):
            return await self._finish_plan_with_phases(
                player_input,
                result,
                on_phase=on_phase,
            )
        if not isinstance(decision, SingleActionDecision):
            raise TypeError("single result 必须对应 SingleActionDecision")
        if result.execution.status in {
            "awaiting_skill_choice",
            "awaiting_post_roll_decision",
        }:
            await _emit_phase(on_phase, "waiting_for_check")
        else:
            await _emit_phase(on_phase, "refreshing_player_view")
            await _emit_phase(on_phase, "generating_narration")
        return await self._from_single(
            player_input,
            decision.adjudication.summary,
            result,
        )

    async def _finish_plan_with_phases(
        self,
        player_input: PlayerInput,
        result: ActionPlanAdvanceResult,
        *,
        on_phase: TurnPhaseObserver | None,
        verify_fingerprint: bool = True,
    ) -> ActionPlanTurnResult:
        if result.run.status == "waiting_for_player":
            await _emit_phase(on_phase, "waiting_for_check")
        elif result.run.status in {
            "awaiting_narration",
            "completed",
            "needs_clarification",
            "cancelled",
            "stopped",
        }:
            await _emit_phase(on_phase, "refreshing_player_view")
            await _emit_phase(on_phase, "generating_narration")
        return await self._from_plan(
            player_input,
            result,
            verify_fingerprint=verify_fingerprint,
        )

    async def resume_plan(
        self,
        player_input: PlayerInput,
        *,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
        on_phase: TurnPhaseObserver | None = None,
    ) -> ActionPlanTurnResult:
        advanced = await self._orchestrator.start_or_resume(
            player_input,
            plan=None,
            on_progress=on_progress,
        )
        return await self._finish_plan_with_phases(
            player_input,
            advanced,
            on_phase=on_phase,
        )

    async def resume_owned(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
        on_phase: TurnPhaseObserver | None = None,
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
            utterance=run.parent_utterance or run.plan.goal,
        )
        return await self._finish_plan_with_phases(
            player_input,
            advanced,
            on_phase=on_phase,
            verify_fingerprint=False,
        )

    async def resume_pending(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        on_progress: Callable[[object], Awaitable[None]] | None = None,
        on_phase: TurnPhaseObserver | None = None,
    ) -> ActionPlanTurnResult:
        """Resume either a durable ActionPlan or a persisted single action."""

        if await self._orchestrator.get_run(room_id, parent_action_id) is not None:
            return await self.resume_owned(
                room_id=room_id,
                player_id=player_id,
                parent_action_id=parent_action_id,
                on_progress=on_progress,
                on_phase=on_phase,
            )
        return await self.resume_single(
            room_id=room_id,
            player_id=player_id,
            parent_action_id=parent_action_id,
            on_phase=on_phase,
        )

    async def resume_single(
        self,
        *,
        room_id: str,
        player_id: str,
        parent_action_id: str,
        on_phase: TurnPhaseObserver | None = None,
    ) -> ActionPlanTurnResult:
        """Finish a single ActionAdjudication without creating a PlanRun."""

        recovery = await self._adjudication_engine.recover_action(
            GetAdjudicationStatusRequest(
                room_id=room_id,
                player_id=player_id,
                action_request_id=parent_action_id,
            )
        )
        if recovery is None:
            raise TurnExecutionError(
                "ACTION_NOT_FOUND",
                "没有找到可恢复的单动作裁决",
                retryable=True,
            )
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=recovery.actor_id,
            client_action_id=parent_action_id,
            # The original player utterance is not part of the Engine contract;
            # the frozen adjudication summary is the safe recovery label.
            utterance=recovery.summary,
        )
        result = SingleActionTurnResult(
            execution=recovery.execution,
            player_view=await self._projector.refresh_adjudication(
                player_input,
                recovery.execution,
            ),
        )
        if recovery.execution.status in {
            "awaiting_skill_choice",
            "awaiting_post_roll_decision",
        }:
            await _emit_phase(on_phase, "waiting_for_check")
        else:
            await _emit_phase(on_phase, "refreshing_player_view")
            await _emit_phase(on_phase, "generating_narration")
        return await self._from_single(player_input, recovery.summary, result)

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
        existing = await self._orchestrator.get_run(room_id, parent_action_id)
        if (
            existing is not None
            and existing.player_id == player_id
            and existing.actor_id == actor_id
            and existing.status == "waiting_for_player"
            and existing.current_step_index < len(existing.steps)
        ):
            execution = existing.steps[existing.current_step_index].adjudication_execution
            pending = execution.pending_decision if execution is not None else None
            if (
                execution is not None
                and execution.status == "awaiting_skill_choice"
                and pending is not None
            ):
                await self._adjudication_engine.decide(
                    CheckDecisionRequest(
                        request_id=request_id,
                        room_id=room_id,
                        player_id=player_id,
                        source_revision=execution.view_revision,
                        decision_id=pending.decision_id,
                        decision_version=pending.decision_version,
                        choice=CancelCheckChoice(),
                    )
                )
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
            utterance=run.parent_utterance or run.plan.goal,
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
        summary: str,
        result: SingleActionTurnResult,
    ) -> ActionPlanTurnResult:
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
        completed_summary = CompletedPlanStepSummary(
            step_index=0,
            semantic_goal=summary,
            outcome=completed_outcome,
            view_revision=execution.view_revision,
            world_time_after=WorldClockView.from_world(result.player_view.world),
            event_refs=execution.public_event_refs,
        )
        context = ActionPlanNarrationContext(
            background=result.player_view.background,
            player_input=player_input,
            plan_goal=summary,
            termination_status=("cancelled" if execution.status == "cancelled" else "resolved"),
            completed_steps=(completed_summary,),
            player_view=result.player_view,
            opening_world_time=result.opening_world_time,
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

    async def _keeper_capabilities(
        self,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> KeeperCapabilityView | None:
        try:
            return await self._projector.keeper_capabilities(
                player_input,
                expected_revision=player_view.revision,
            )
        except (AttributeError, NotImplementedError):
            return None

    async def _read_recent_history(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> RecentTurnContext:
        recent_history = RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
        )
        if not self._recent_history_enabled:
            return recent_history
        try:
            recent_history = await self._recent_history_source.read(
                player_input=player_input,
                player_view=player_view,
                exclude_correlation_id=player_input.client_action_id,
                budget=self._recent_history_budget,
            )
            recent_history.validate_for(
                player_input=player_input,
                player_view=player_view,
            )
        except (ValidationError, ContractError, ValueError) as exc:
            raise TurnExecutionError(
                "RECENT_HISTORY_INVALID",
                "近期历史未通过安全校验，本次动作未执行",
                retryable=False,
            ) from exc
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.warning(
                "action_plan_recent_history_degraded",
                room_id=player_input.room_id,
                correlation_id=player_input.client_action_id,
                error_type=type(exc).__name__,
            )
            return RecentTurnContext.empty(
                player_input=player_input,
                player_view=player_view,
            )
        return recent_history

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


class _EmptyRecentHistorySource:
    async def read(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
        exclude_correlation_id: str,
        budget: RecentHistoryBudget,
    ) -> RecentTurnContext:
        del exclude_correlation_id, budget
        return RecentTurnContext.empty(player_input=player_input, player_view=player_view)


def build_action_plan_turn_application(
    *,
    store: EngineStore,
    engine: RuleEngineService,
    adjudication_engine: AdjudicationEngineService,
    plan_store=None,
    settings=None,
    client=None,
    recent_history_source: RecentHistorySource | None = None,
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
        adjudicator = _RuleFirstStepAdjudicator(PromptActionPlanStepAdjudicator(client))
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
        recent_history_source=recent_history_source or _EmptyRecentHistorySource(),
        recent_history_budget=RecentHistoryBudget(
            max_turns=resolved.recent_history_max_turns,
            max_chars=resolved.recent_history_max_chars,
        ),
        recent_history_enabled=resolved.recent_history_enabled,
    )


class _DeterministicStepAdjudicator:
    # Deliberately conservative: the offline composition only resolves steps
    # fully implied by the safe view, then falls back to narrative-only.

    async def adjudicate(self, context: ActionPlanStepContext) -> ActionAdjudication:
        adjudication = _deterministic_step_adjudication(context)
        if adjudication is not None:
            return adjudication

        action_text = context.step.semantic_goal.replace(
            context.player_view.scene.name,
            "",
        ).strip(" ，,。")
        target = _match_visible_entity(context.player_view, action_text)
        target_kind = "entity" if target is not None else "location"
        target_id = target.id if target is not None else context.player_view.scene.id
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(kind=target_kind, id=target_id),
            method=ActionMethod(
                family=context.step.kind,
                description=context.step.semantic_goal,
            ),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class _RuleFirstStepAdjudicator:
    """Resolve unambiguous Match View steps without a fallible model round-trip."""

    def __init__(self, fallback: ActionPlanStepAdjudicator) -> None:
        self._fallback = fallback

    async def adjudicate(self, context: ActionPlanStepContext) -> ActionAdjudication:
        adjudication = _deterministic_step_adjudication(context)
        if adjudication is not None:
            return adjudication
        return await self._fallback.adjudicate(context)


def _deterministic_step_adjudication(
    context: ActionPlanStepContext,
) -> ActionAdjudication | None:
    """Return only decisions fully implied by the current player-safe view."""

    if context.step.kind in {"wait", "rest"}:
        time = context.keeper_capabilities.time if context.keeper_capabilities else None
        if time is not None and time.blocked_reason is None and time.next_point_id:
            # 「休息到晚上」「睡到八点」要跳几个时间点，取决于玩家说的是哪个
            # 时间——这是语义问题，确定性分支答不了。把它交给模型，由它按
            # keeper_capabilities.time 数出 advance_world_time 的次数，Engine
            # 仍然逐个校验每一跳是不是时间线上的下一个点。
            return None
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
            # 时间推不动（多人房间还没有 ready 门禁，或模组没有下一个时间点）时，
            # 等待/休息就只是一次叙事停留，不改变任何权威状态。
            success_effects=(),
        )

    if context.step.kind == "travel":
        destination = _match_travel_target(
            context.player_view,
            context.step.semantic_goal,
        )
        if destination is None:
            # An unknown *ordinary* destination is not necessarily an error:
            # #212 lets the step Agent propose an ambient Runtime Location.
            # Prompting alone did not get us there — the model kept answering
            # "阿诺兹堡没有挂牌的旅店" instead of proposing one — so an ordinary
            # venue that collides with nothing authored is resolved here, and
            # everything else still falls through to the model.
            return _ambient_venue_adjudication(context)
        destination_id = destination.id
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="location", id=destination_id),
            method=ActionMethod(
                family="travel",
                description=context.step.semantic_goal,
            ),
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id=destination_id),),
        )

    action_text = context.step.semantic_goal.replace(
        context.player_view.scene.name,
        "",
    ).strip(" ，,。")
    target = _match_visible_entity(context.player_view, action_text)
    candidate, option = _match_rule_candidate(
        context.keeper_capabilities,
        action_text,
        target.id if target is not None else None,
    )
    if candidate is not None and option is not None:
        target_kind = (
            candidate.target_kinds[0]
            if candidate.target_kinds
            else "entity"
            if target is not None
            else "location"
        )
        # 不掷骰的分支（例如 proceed）不能为了凑格式编一个技能出来：option id
        # 不是技能名，`proceed` / `STR` 提交上去会被 Ruleset 快照拒绝。带检定的
        # 分支才沿用 option id 作技能，Engine 仍会再校验一次。
        check = (
            RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id=option.id,
                        skill_id=option.id,
                        difficulty="regular",
                        method_summary=context.step.semantic_goal,
                        player_safe_reason="使用当前地点公开的检定方式",
                    ),
                )
            )
            if option.requires_check
            else NoAdjudicationCheck()
        )
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(
                kind=target_kind,
                id=(
                    candidate.target_ids[0]
                    if candidate.target_ids
                    else target.id
                    if target is not None
                    else context.player_view.scene.id
                ),
            ),
            method=ActionMethod(
                family=(
                    candidate.action_families[0] if candidate.action_families else context.step.kind
                ),
                description=context.step.semantic_goal,
            ),
            rule_decision=RuleDecisionRef(rule_id=candidate.rule_id, option_id=option.id),
            check=check,
            # Effects belong to the rule (#226 §5), not to this stand-in.
            success_effects=(),
            failure_effects=(),
        )

    # Once the planner has identified a visible conversation partner, ordinary
    # dialogue needs no second model call to invent an adjudication.  Keeping
    # this path narrative-only is also an information boundary: authored rules
    # remain the only way to reveal facts or mutate state.
    if context.step.kind == "dialogue" and target is not None:
        return ActionAdjudication(
            request_id=context.step_request_id,
            source_revision=context.player_view.revision,
            actor_id=context.player_input.actor_id,
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="entity", id=target.id),
            method=ActionMethod(
                family="talk",
                description=context.step.semantic_goal,
            ),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )
    return None


def _match_visible_entity(view: PlayerView, text: str):
    matches = []
    for entity in view.scene.visible_entities:
        overlap = _best_label_overlap(text, (entity.id, entity.name, *entity.aliases))
        if overlap is not None:
            matches.append((len(overlap), entity.id, entity))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][2]


def _match_rule_candidate(capabilities, text: str, target_id: str | None):
    """Pick at most one v3 Rule the player's words clearly mean.

    The Fake stands in for the Agent's semantic judgement, so it only matches on
    the player-safe hints the Match View published — it never reads the module.
    Ambiguity yields nothing: guessing between two rules is exactly the mistake
    a real Agent would be asked not to make.

    Option hints have to participate in that judgement, not just candidate hints.
    In the published fixture every rule aimed at the same NPC carries that NPC's
    name as its candidate hint, and the word that actually tells them apart
    （"侦查" / "贿赂" / "威吓"）lives on the options. Scoring candidate hints alone
    therefore made all four caretaker rules tie on every utterance, and the tie
    was resolved as "no match" — the Fake could never reach a rule at all.
    """

    if capabilities is None:
        return None, None
    scored = []
    for candidate in capabilities.rule_candidates:
        if target_id is not None and candidate.target_ids and target_id not in candidate.target_ids:
            continue
        family_hits = [
            hint
            for family in candidate.action_families
            for hint in _ACTION_FAMILY_HINTS.get(family, ())
            if hint in text
        ]
        candidate_hits = [hint for hint in candidate.semantic_hints if hint and hint in text]
        best_option = None
        best_option_hit = 0
        for option in candidate.options:
            hits = [hint for hint in option.semantic_hints if hint and hint in text]
            if hits and max(len(hint) for hint in hits) > best_option_hit:
                best_option = option
                best_option_hit = max(len(hint) for hint in hits)
        if not family_hits and not candidate_hits and best_option is None:
            continue
        # Option evidence outranks candidate evidence: sibling rules share the
        # target's name, so only the option words carry discriminating power.
        score = (
            best_option_hit,
            max((len(hint) for hint in family_hits), default=0),
            max((len(hint) for hint in candidate_hits), default=0),
        )
        scored.append((score, candidate, best_option))
    if not scored:
        return None, None
    best = max(score for score, _, _ in scored)
    finalists = [(candidate, option) for score, candidate, option in scored if score == best]
    if len(finalists) != 1:
        return None, None
    candidate, option = finalists[0]
    if option is not None:
        return candidate, option
    return candidate, candidate.options[0] if candidate.options else None


# Match View action families are stable contract identifiers. These localized
# words merely recognize the player's explicit verb; they do not add a rule or
# reveal module-only facts. Ties still yield no match below.
_ACTION_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "observe": ("仔细观察", "观察", "察看", "查看"),
    "search": ("搜索", "搜查", "查找", "找线索", "寻找"),
    "research": ("研究", "查阅", "检索", "翻阅", "查旧报"),
    "social": ("留下好印象", "博取信任", "说服"),
    "intimidate": ("恐吓", "威吓"),
    "bribe": ("贿赂", "收买"),
}


__all__ = [
    "ActionPlanTurnApplication",
    "ActionPlanTurnResult",
    "DeterministicActionPlanNarrationModel",
    "DeterministicHostTurnDecisionModel",
    "HostTurnDecisionModel",
    "build_action_plan_turn_application",
]


def _production_application() -> ActionPlanTurnApplication:
    from app.adapters import SqlAlchemyRecentHistorySource
    from app.core.db import async_session_factory
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
        recent_history_source=SqlAlchemyRecentHistorySource(async_session_factory),
    )


action_plan_turn_application = _production_application()
__all__.append("action_plan_turn_application")
