"""主持编排与规则引擎的后端组合根（issues #122 / #123）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import anyio
import httpx
import structlog
from collaboration_framework.bootstrap.host_agent import (
    build_deepseek_host_agent,
    build_qwen_host_agent,
)
from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    DefaultCheck,
    Intent,
    ModuleCheck,
    PlayerInput,
    PlayerView,
    PlayerViewScope,
    player_input_fingerprint,
)
from collaboration_framework.engine import EngineStore, RuleEngineService
from collaboration_framework.host.adapters import OneShotHostAgentAdapter
from collaboration_framework.host.adapters.fakes import (
    FakeHostAgent,
    FakeNarrationModel,
    FakeOpeningNarrationModel,
)
from collaboration_framework.host.adapters.openai_agents import PROMPT_VERSION
from collaboration_framework.host.application import (
    ContextAssembler,
    HostAgentIntentResolver,
    IntentResolution,
    NarrationValidationError,
    Narrator,
    OpeningNarrationValidationError,
    OpeningNarrator,
    PlayerViewProjector,
    TurnExecutionError,
    deterministic_opening_narration,
    is_scene_query_utterance,
)
from collaboration_framework.host.ports import (
    HostAgentPort,
    IntentModelPort,
    NarrationModelPort,
    OpeningNarrationModelPort,
    RecentHistorySource,
)
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    NarrationOutput,
    RecentHistoryBudget,
    RecentTurnContext,
    TurnOutput,
    WebSocketOutput,
)
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.adapters import (
    DeepSeekChatCompletionsJsonClient,
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
    PromptOpeningNarrationModel,
    QwenChatCompletionsJsonClient,
    SqlAlchemyRecentHistorySource,
)
from app.core.config import Settings, get_settings, secret_value
from app.core.db import async_session_factory
from app.core.engine import engine_store, rule_engine_service
from app.core.turn_events import (
    TurnEventSink,
    TurnPhaseChanged,
    TurnStarted,
    TurnToolCompleted,
    TurnToolStarted,
    emit_turn_event,
)

logger = structlog.get_logger()


class ActorResolutionError(ContractError):
    """当前房间运行时没有且仅有一个由该 Player 控制的 Actor。"""


CheckDifficulty = Literal["regular", "hard", "extreme"]
ActionResultSink = Callable[[ActionResult, PlayerView], Awaitable[None]]
TurnInputAcceptedSink = Callable[[PlayerInput, PlayerView], Awaitable[None]]

_PUBLIC_TOOL_LABELS = {
    "search_visible_entities": "守秘人正在查看当前场景",
    "get_visible_entity": "守秘人正在确认可见目标",
}
_MAX_NARRATION_ATTEMPTS = 2


def _public_tool_label(tool_name: str) -> str:
    return _PUBLIC_TOOL_LABELS.get(tool_name, "守秘人正在整理当前信息")


@dataclass(frozen=True)
class SkillCheckCandidate:
    id: str
    name: str
    target_value: int


@dataclass(frozen=True)
class PreparedTurn:
    player_input: PlayerInput
    view_before: PlayerView
    recent_history: RecentTurnContext
    intent: Intent
    candidates: tuple[SkillCheckCandidate, ...]
    difficulty: CheckDifficulty
    stored_roll_value: int | None = None
    completed_action_result: ActionResult | None = None
    recovered_intent: bool = False


@dataclass(frozen=True)
class HostModelMetadata:
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION


@dataclass(frozen=True)
class OpeningGenerationResult:
    narration: NarrationOutput
    result: Literal["model", "template", "fallback"]
    failure_category: str | None = None


@dataclass(frozen=True)
class EmptyRecentHistorySource:
    async def read(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
        exclude_correlation_id: str,
        budget: RecentHistoryBudget,
    ) -> RecentTurnContext:
        del exclude_correlation_id, budget
        return RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
        )


@dataclass(frozen=True)
class TurnApplication:
    """无 Room 内存状态的单回合应用入口。"""

    store: EngineStore
    engine: RuleEngineService
    intent_resolver: HostAgentIntentResolver
    narration_model: NarrationModelPort
    opening_narration_model: OpeningNarrationModelPort
    host_metadata: HostModelMetadata
    opening_narration_mode: Literal["model", "template"]
    opening_narration_timeout_seconds: float
    recent_history_source: RecentHistorySource
    recent_history_budget: RecentHistoryBudget
    recent_history_enabled: bool

    async def resolve_actor_id(self, room_id: str, player_id: str) -> str:
        return await self._load_turn_scope(room_id, player_id)

    async def current_player_view(
        self,
        *,
        room_id: str,
        player_id: str,
    ) -> PlayerView:
        """Project the initial/current player-safe view without creating an action."""

        actor_id = await self._load_turn_scope(room_id, player_id)
        scope = PlayerViewScope(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
        )
        return await PlayerViewProjector(self.engine).project_scope(scope)

    async def generate_opening(
        self,
        player_view: PlayerView,
    ) -> OpeningGenerationResult:
        """Generate a validated opening, with a deterministic public fallback."""

        context = ContextAssembler().for_opening(player_view)
        started_at = time.perf_counter()
        failure_category: str | None = None
        result: Literal["model", "template", "fallback"]
        if self.opening_narration_mode == "template":
            narration = deterministic_opening_narration(context)
            result = "template"
        else:
            try:
                with anyio.fail_after(self.opening_narration_timeout_seconds):
                    narration = await OpeningNarrator(
                        self.opening_narration_model
                    ).narrate(context)
                result = "model"
            except Exception as exc:  # the opening must never prevent entering InGame
                failure_category = _opening_failure_category(exc)
                narration = deterministic_opening_narration(context)
                result = "fallback"

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        input_chars = len(
            json.dumps(context.to_json_dict(), ensure_ascii=False, separators=(",", ":"))
        )
        logger.info(
            "opening_narration_completed",
            room_ref=hashlib.sha256(player_view.room_id.encode()).hexdigest()[:12],
            message_id="game-opening",
            provider=self.host_metadata.provider,
            model=self.host_metadata.model,
            mode=self.opening_narration_mode,
            elapsed_ms=elapsed_ms,
            result=result,
            failure_category=failure_category,
            input_chars=input_chars,
            output_chars=len(narration.text),
        )
        return OpeningGenerationResult(
            narration=narration,
            result=result,
            failure_category=failure_category,
        )

    async def _load_turn_scope(
        self,
        room_id: str,
        player_id: str,
    ) -> str:
        async with self.store.transaction(room_id) as transaction:
            runtime = await transaction.load_runtime()
        actor_ids = [
            actor_id
            for actor_id, actor in runtime.game_state.actors.items()
            if actor.player_id == player_id
        ]
        if len(actor_ids) != 1:
            raise ActorResolutionError("当前玩家没有唯一绑定的局内 Actor")
        return actor_ids[0]

    async def handle(
        self,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        utterance: str,
        on_event: TurnEventSink | None = None,
        on_input_accepted: TurnInputAcceptedSink | None = None,
    ) -> WebSocketOutput:
        prepared = await self.prepare(
            room_id=room_id,
            player_id=player_id,
            client_action_id=client_action_id,
            utterance=utterance,
            on_event=on_event,
            on_input_accepted=on_input_accepted,
        )
        return (
            await self.complete(
                prepared,
                on_event=on_event,
            )
        ).to_websocket_output()

    async def prepare(
        self,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        utterance: str,
        on_event: TurnEventSink | None = None,
        on_input_accepted: TurnInputAcceptedSink | None = None,
    ) -> PreparedTurn:
        actor_id = await self._load_turn_scope(room_id, player_id)
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            utterance=utterance,
        )
        projector = PlayerViewProjector(self.engine)
        view_before = await projector.project(player_input)
        if on_input_accepted is not None:
            await on_input_accepted(player_input, view_before)
        await emit_turn_event(
            on_event,
            TurnStarted(correlation_id=client_action_id),
        )
        await emit_turn_event(
            on_event,
            TurnPhaseChanged(
                correlation_id=client_action_id,
                phase="reading_player_view",
            ),
        )
        recent_history = RecentTurnContext.empty(
            player_input=player_input,
            player_view=view_before,
        )
        history_degraded = False
        if self.recent_history_enabled:
            try:
                recent_history = await self.recent_history_source.read(
                    player_input=player_input,
                    player_view=view_before,
                    exclude_correlation_id=client_action_id,
                    budget=self.recent_history_budget,
                )
                recent_history.validate_for(
                    player_input=player_input,
                    player_view=view_before,
                )
            except (ValidationError, ContractError, ValueError) as exc:
                raise TurnExecutionError(
                    "RECENT_HISTORY_INVALID",
                    "近期历史未通过安全校验，本次动作未执行",
                    retryable=False,
                ) from exc
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                history_degraded = True
                logger.warning(
                    "recent_history_degraded",
                    room_ref=hashlib.sha256(room_id.encode("utf-8")).hexdigest()[:12],
                    correlation_id=client_action_id,
                    degraded=True,
                    error_type=type(exc).__name__,
                )
        self._log_recent_history(
            room_id=room_id,
            correlation_id=client_action_id,
            recent_history=recent_history,
            degraded=history_degraded,
        )
        async with self.store.transaction(room_id) as transaction:
            completed = await transaction.find_completed_action(client_action_id)
        recovered_intent = False
        if completed is not None:
            if (
                completed.request.room_id != room_id
                or completed.request.player_id != player_id
                or completed.request.actor_id != actor_id
            ):
                raise ContractError("client_action_id belongs to another actor")
            original_fingerprint = completed.request.input_fingerprint
            submitted_fingerprint = player_input_fingerprint(player_input)
            # Legacy records without a fingerprint cannot prove that a new payload is
            # the original request, so the fast recovery path fails closed.
            if original_fingerprint is None or not hmac.compare_digest(
                original_fingerprint,
                submitted_fingerprint,
            ):
                raise ContractError("request_id 已用于不同的动作请求")
            intent = completed.request.intent
            candidates: tuple[SkillCheckCandidate, ...] = ()
            difficulty: CheckDifficulty = "regular"
            stored_roll_value = completed.request.roll_value
            completed_action_result = completed.execution.action_result.model_copy(
                update={"view_revision": view_before.revision},
                deep=True,
            )
        else:
            await emit_turn_event(
                on_event,
                TurnPhaseChanged(
                    correlation_id=client_action_id,
                    phase="understanding_action",
                ),
            )

            tool_names: list[str] = []
            terminal: HostAgentCompleted | HostAgentFailed | None = None

            async def observe_host_event(event: HostAgentEvent) -> None:
                nonlocal terminal
                if isinstance(event, HostAgentToolStarted) and event.tool_name not in tool_names:
                    tool_names.append(event.tool_name)
                if isinstance(event, (HostAgentCompleted, HostAgentFailed)):
                    terminal = event
                await self._forward_host_progress(
                    client_action_id,
                    event,
                    on_event,
                )

            try:
                resolution: IntentResolution = await self.intent_resolver.resolve_with_metadata(
                    HostAgentContext(
                        player_input=player_input,
                        player_view=view_before,
                        recent_history=recent_history,
                    ),
                    on_event=observe_host_event,
                )
                intent = resolution.intent
                recovered_intent = resolution.recovered
            except TurnExecutionError as exc:
                self._log_host_run(
                    room_id=room_id,
                    correlation_id=client_action_id,
                    terminal=terminal,
                    tool_names=tool_names,
                    error_code=exc.code,
                )
                raise
            self._log_host_run(
                room_id=room_id,
                correlation_id=client_action_id,
                terminal=terminal,
                tool_names=tool_names,
                error_code=None,
            )
            candidates, difficulty = self._check_candidates(intent, view_before)
            stored_roll_value = None
            completed_action_result = None
            if candidates:
                await emit_turn_event(
                    on_event,
                    TurnPhaseChanged(
                        correlation_id=client_action_id,
                        phase="waiting_for_check",
                    ),
                )
        return PreparedTurn(
            player_input=player_input,
            view_before=view_before,
            recent_history=recent_history,
            intent=intent,
            candidates=candidates,
            difficulty=difficulty,
            stored_roll_value=stored_roll_value,
            completed_action_result=completed_action_result,
            recovered_intent=recovered_intent,
        )

    async def complete(
        self,
        prepared: PreparedTurn,
        *,
        selected_skill: str | None = None,
        roll_value: int | None = None,
        on_event: TurnEventSink | None = None,
        on_action_result: ActionResultSink | None = None,
    ) -> TurnOutput:
        if (selected_skill is None) != (roll_value is None):
            raise ContractError("selected_skill and roll_value must be supplied together")
        if prepared.completed_action_result is not None and selected_skill is not None:
            raise ContractError("Completed action cannot accept another skill check")

        intent = prepared.intent
        if selected_skill is not None:
            if selected_skill not in {candidate.id for candidate in prepared.candidates}:
                raise ContractError("Selected skill is not available for this check")
            check = intent.check
            if not isinstance(check, (ModuleCheck, DefaultCheck)):
                raise ContractError("This action is not waiting for a skill check")
            intent = intent.model_copy(
                update={"check": check.model_copy(update={"proposed_skills": (selected_skill,)})}
            )
        await emit_turn_event(
            on_event,
            TurnPhaseChanged(
                correlation_id=prepared.player_input.client_action_id,
                phase="executing_action",
            ),
        )
        executed_now = prepared.completed_action_result is None
        if prepared.completed_action_result is None:
            action_result = await self.engine.execute(
                ActionRequest(
                    request_id=prepared.player_input.client_action_id,
                    room_id=prepared.player_input.room_id,
                    player_id=prepared.player_input.player_id,
                    actor_id=prepared.player_input.actor_id,
                    source_view_revision=prepared.view_before.revision,
                    input_fingerprint=player_input_fingerprint(prepared.player_input),
                    intent=intent,
                    roll_value=(
                        roll_value if selected_skill is not None else prepared.stored_roll_value
                    ),
                )
            )
        else:
            action_result = prepared.completed_action_result.model_copy(deep=True)
        projector = PlayerViewProjector(self.engine)
        view_after = await projector.refresh(prepared.player_input, action_result)
        if (
            view_after.room_id != prepared.player_input.room_id
            or view_after.player_id != prepared.player_input.player_id
            or view_after.actor_id != prepared.player_input.actor_id
            or view_after.revision != action_result.view_revision
        ):
            raise TurnExecutionError(
                "PLAYER_VIEW_REVISION_MISMATCH",
                "规则结果与玩家视图版本不一致，请重试",
                retryable=True,
            )
        if executed_now and on_action_result is not None:
            await on_action_result(action_result, view_after)
        await emit_turn_event(
            on_event,
            TurnPhaseChanged(
                correlation_id=prepared.player_input.client_action_id,
                phase="refreshing_player_view",
            ),
        )
        await emit_turn_event(
            on_event,
            TurnPhaseChanged(
                correlation_id=prepared.player_input.client_action_id,
                phase="generating_narration",
            ),
        )
        narration_context = ContextAssembler().for_narration(
            prepared.player_input,
            intent,
            action_result,
            view_after,
            prepared.recent_history.model_copy(update={"as_of_revision": view_after.revision}),
        )
        narrator = Narrator(self.narration_model)
        narration = None
        for attempt in range(1, _MAX_NARRATION_ATTEMPTS + 1):
            try:
                narration = await narrator.narrate(narration_context)
                break
            except NarrationValidationError as exc:
                will_retry = attempt < _MAX_NARRATION_ATTEMPTS
                logger.warning(
                    "narration_validation_rejected",
                    correlation_id=prepared.player_input.client_action_id,
                    attempt=attempt,
                    will_retry=will_retry,
                    rejection_reason=exc.reason,
                )
                if not will_retry:
                    raise TurnExecutionError(
                        "NARRATION_INVALID",
                        "规则结果已安全保存，但叙事未通过安全校验，请使用原请求重试",
                        retryable=True,
                    ) from exc
            except Exception as exc:
                if action_result.resolution == "unrecognized":
                    narration = (
                        _fallback_scene_query(view_after)
                        if is_scene_query_utterance(prepared.player_input.utterance)
                        else _fallback_clarification(prepared.intent, view_after)
                    )
                    break
                raise TurnExecutionError(
                    "NARRATOR_FAILED",
                    "规则结果已安全保存，但叙事生成失败，请重试原动作",
                    retryable=True,
                ) from exc
        if narration is None:
            raise TurnExecutionError(
                "NARRATOR_FAILED",
                "规则结果已安全保存，但叙事生成失败，请重试原动作",
                retryable=True,
            )
        return TurnOutput(
            status="clarification" if narration.kind == "clarification" else "completed",
            player_input=prepared.player_input,
            intent=intent,
            action_result=action_result,
            narration=narration,
            player_view=view_after,
        )

    @staticmethod
    async def _forward_host_progress(
        correlation_id: str,
        event: HostAgentEvent,
        sink: TurnEventSink | None,
    ) -> None:
        if isinstance(event, HostAgentToolStarted):
            await emit_turn_event(
                sink,
                TurnToolStarted(
                    correlation_id=correlation_id,
                    tool_name=event.tool_name,
                    public_progress_label=_public_tool_label(event.tool_name),
                ),
            )
        elif isinstance(event, HostAgentToolCompleted):
            await emit_turn_event(
                sink,
                TurnToolCompleted(
                    correlation_id=correlation_id,
                    tool_name=event.tool_name,
                    status=event.status,
                ),
            )

    def _log_host_run(
        self,
        *,
        room_id: str,
        correlation_id: str,
        terminal: HostAgentCompleted | HostAgentFailed | None,
        tool_names: list[str],
        error_code: str | None,
    ) -> None:
        usage = terminal.usage if terminal is not None else None
        fields = {
            "correlation_id": correlation_id,
            "room_ref": hashlib.sha256(room_id.encode("utf-8")).hexdigest()[:12],
            "provider": self.host_metadata.provider,
            "model": self.host_metadata.model,
            "prompt_version": self.host_metadata.prompt_version,
            "model_rounds": usage.model_rounds if usage else None,
            "tool_calls": usage.tool_calls if usage else None,
            "tool_names": tuple(tool_names),
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "duration_ms": usage.duration_ms if usage else None,
            "termination_reason": (
                usage.termination_reason
                if usage
                else ("completed" if isinstance(terminal, HostAgentCompleted) else "internal_error")
            ),
            "error_code": error_code
            or (terminal.code if isinstance(terminal, HostAgentFailed) else None),
        }
        if isinstance(terminal, HostAgentCompleted) and error_code is None:
            logger.info("host_agent_run_completed", **fields)
        else:
            logger.warning("host_agent_run_failed", **fields)

    def _log_recent_history(
        self,
        *,
        room_id: str,
        correlation_id: str,
        recent_history: RecentTurnContext,
        degraded: bool,
    ) -> None:
        character_count = sum(
            len(turn.player_utterance.text)
            + len(turn.accepted_intent_summary or "")
            + (len(turn.published_narration.text) if turn.published_narration is not None else 0)
            + sum(
                len(fact.text)
                for fact in (
                    turn.player_safe_result.visible_facts
                    if turn.player_safe_result is not None
                    else ()
                )
            )
            for turn in recent_history.turns
        )
        logger.info(
            "recent_history_selected",
            room_ref=hashlib.sha256(room_id.encode("utf-8")).hexdigest()[:12],
            correlation_id=correlation_id,
            selected_turn_count=len(recent_history.turns),
            character_count=character_count,
            degraded=degraded,
            provider=self.host_metadata.provider,
            model=self.host_metadata.model,
            prompt_version=self.host_metadata.prompt_version,
        )

    @staticmethod
    def _check_candidates(
        intent: Intent,
        player_view: PlayerView,
    ) -> tuple[tuple[SkillCheckCandidate, ...], CheckDifficulty]:
        values = {
            item.id: item
            for item in (
                *player_view.self_actor.attributes,
                *player_view.self_actor.skills,
                *(item for item in player_view.self_actor.resources if item.id == "luck"),
            )
            if isinstance(item.value, int) and not isinstance(item.value, bool)
        }

        difficulty: CheckDifficulty = "regular"
        requested: tuple[str, ...] = ()
        if isinstance(intent.check, ModuleCheck):
            option = next(
                (
                    item
                    for item in player_view.checkpoint_options
                    if item.id == intent.check.checkpoint_id
                ),
                None,
            )
            if option is None:
                raise ContractError("Intent checkpoint is not available")
            difficulty = option.difficulty or "regular"
            requested = intent.check.proposed_skills or option.skills
            allowed = set(option.skills)
            requested = tuple(item for item in requested if item in allowed)
        elif isinstance(intent.check, DefaultCheck):
            requested = intent.check.proposed_skills

        candidates: list[SkillCheckCandidate] = []
        seen: set[str] = set()
        for skill_id in requested:
            value = values.get(skill_id)
            if (
                value is None
                or skill_id in seen
                or not isinstance(value.value, int)
                or isinstance(value.value, bool)
            ):
                continue
            seen.add(skill_id)
            candidates.append(
                SkillCheckCandidate(
                    id=skill_id,
                    name=value.name,
                    target_value=value.value,
                )
            )
        return tuple(candidates), difficulty


def _fallback_clarification(intent: Intent, view: PlayerView) -> NarrationOutput:
    suggestions = tuple(
        [
            *(f"观察{entity.name}" for entity in view.scene.visible_entities[:2]),
            *(f"前往{available_exit.name}" for available_exit in view.scene.available_exits[:1]),
        ][:3]
    )
    return NarrationOutput(
        kind="clarification",
        text=(intent.clarification_question or "我还不能确定你想做什么，请说明目标和行动。"),
        suggested_actions=suggestions,
    )


def _fallback_scene_query(view: PlayerView) -> NarrationOutput:
    description = view.scene.description.strip()
    text = f"你现在位于{view.scene.name}。"
    if description:
        text = f"{text}{description}"
    return NarrationOutput(
        kind="narration",
        text=text,
        suggested_actions=(),
    )


def _opening_failure_category(exc: Exception) -> str:
    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_status"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, OpeningNarrationValidationError):
        return f"validation_{exc.reason}"
    if isinstance(exc, ValidationError):
        return "pydantic_validation"
    return "unexpected"


def build_turn_application(
    store: EngineStore,
    engine: RuleEngineService,
    *,
    settings: Settings | None = None,
    host_agent: HostAgentPort | None = None,
    intent_resolver: HostAgentIntentResolver | None = None,
    intent_model: IntentModelPort | None = None,
    narration_model: NarrationModelPort | None = None,
    opening_narration_model: OpeningNarrationModelPort | None = None,
    host_metadata: HostModelMetadata | None = None,
    recent_history_source: RecentHistorySource | None = None,
) -> TurnApplication:
    """Compose the sole production turn path around one HostAgentPort."""

    resolved_settings = settings or get_settings()
    resolver_inputs = sum(
        value is not None for value in (host_agent, intent_resolver, intent_model)
    )
    if resolver_inputs > 1:
        raise ValueError("host_agent、intent_resolver、intent_model 只能提供一个")
    if narration_model is None:
        if resolver_inputs:
            raise ValueError("自定义 Host Agent 时必须同时提供 narration_model")
        (
            intent_resolver,
            narration_model,
            opening_narration_model,
            host_metadata,
        ) = _configured_models(resolved_settings)
    elif intent_resolver is None:
        if host_agent is not None:
            intent_resolver = HostAgentIntentResolver(host_agent)
        elif intent_model is not None:
            intent_resolver = HostAgentIntentResolver(OneShotHostAgentAdapter(intent_model))
        else:
            raise ValueError("必须提供 Host Agent 意图解析依赖")
    assert intent_resolver is not None
    opening_narration_model = (
        opening_narration_model or FakeOpeningNarrationModel()
    )
    host_metadata = host_metadata or HostModelMetadata(
        provider="custom",
        model="custom",
    )
    return TurnApplication(
        store=store,
        engine=engine,
        intent_resolver=intent_resolver,
        narration_model=narration_model,
        opening_narration_model=opening_narration_model,
        host_metadata=host_metadata,
        opening_narration_mode=resolved_settings.opening_narration_mode,
        opening_narration_timeout_seconds=(
            resolved_settings.opening_narration_timeout_seconds
        ),
        recent_history_source=recent_history_source or EmptyRecentHistorySource(),
        recent_history_budget=RecentHistoryBudget(
            max_turns=resolved_settings.recent_history_max_turns,
            max_chars=resolved_settings.recent_history_max_chars,
        ),
        recent_history_enabled=resolved_settings.recent_history_enabled,
    )


def _configured_models(
    settings: Settings,
) -> tuple[
    HostAgentIntentResolver,
    NarrationModelPort,
    OpeningNarrationModelPort,
    HostModelMetadata,
]:
    if settings.host_model_provider == "fake":
        return (
            HostAgentIntentResolver(FakeHostAgent()),
            FakeNarrationModel(),
            FakeOpeningNarrationModel(),
            HostModelMetadata(provider="fake", model="deterministic"),
        )
    if settings.host_model_provider == "deepseek":
        if settings.deepseek_api_key is None:
            raise ValueError("DeepSeek Host 模型缺少 API key")
        host_agent = build_deepseek_host_agent(
            {
                "HOST_AGENT_API_KEY": secret_value(settings.deepseek_api_key),
                "HOST_AGENT_BASE_URL": settings.deepseek_base_url,
                "HOST_AGENT_MODEL": settings.deepseek_model,
                "HOST_AGENT_MAX_TURNS": str(settings.host_agent_max_turns),
                "HOST_AGENT_MAX_TOOL_CALLS": str(settings.host_agent_max_tool_calls),
                "HOST_AGENT_TOOL_TIMEOUT_SECONDS": str(settings.host_agent_tool_timeout_seconds),
                "HOST_AGENT_TIMEOUT_SECONDS": str(settings.host_agent_timeout_seconds),
            }
        )
        client = DeepSeekChatCompletionsJsonClient(
            api_key=secret_value(settings.deepseek_api_key),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )
        return (
            HostAgentIntentResolver(host_agent),
            PromptNarrationModel(client),
            PromptOpeningNarrationModel(client),
            HostModelMetadata(
                provider="deepseek",
                model=settings.deepseek_model,
            ),
        )
    if settings.host_model_provider == "qwen":
        if settings.qwen_api_key is None:
            raise ValueError("Qwen Host 模型缺少 API key")
        host_agent = build_qwen_host_agent(
            {
                "HOST_AGENT_API_KEY": secret_value(settings.qwen_api_key),
                "HOST_AGENT_BASE_URL": settings.qwen_base_url,
                "HOST_AGENT_MODEL": settings.qwen_model,
                "HOST_AGENT_MAX_TURNS": str(settings.host_agent_max_turns),
                "HOST_AGENT_MAX_TOOL_CALLS": str(settings.host_agent_max_tool_calls),
                "HOST_AGENT_TOOL_TIMEOUT_SECONDS": str(settings.host_agent_tool_timeout_seconds),
                "HOST_AGENT_TIMEOUT_SECONDS": str(settings.host_agent_timeout_seconds),
            }
        )
        client = QwenChatCompletionsJsonClient(
            api_key=secret_value(settings.qwen_api_key),
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            timeout_seconds=settings.qwen_timeout_seconds,
        )
        return (
            HostAgentIntentResolver(host_agent),
            PromptNarrationModel(client),
            PromptOpeningNarrationModel(client),
            HostModelMetadata(
                provider="qwen",
                model=settings.qwen_model,
            ),
        )
    else:
        if settings.openai_api_key is None:
            raise ValueError("OpenAI Host 模型缺少 API key")
        client = OpenAIResponsesJsonClient(
            api_key=secret_value(settings.openai_api_key),
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
        )
        return (
            HostAgentIntentResolver(OneShotHostAgentAdapter(PromptIntentModel(client))),
            PromptNarrationModel(client),
            PromptOpeningNarrationModel(client),
            HostModelMetadata(
                provider="openai",
                model=settings.openai_model,
            ),
        )


turn_application = build_turn_application(
    engine_store,
    rule_engine_service,
    recent_history_source=SqlAlchemyRecentHistorySource(async_session_factory),
)

__all__ = [
    "ActorResolutionError",
    "OpeningGenerationResult",
    "TurnApplication",
    "build_turn_application",
    "turn_application",
]
