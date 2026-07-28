"""主持编排与规则引擎的后端组合根（issues #122 / #123）。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from collaboration_framework.bootstrap.host_agent import build_qwen_host_agent
from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    DefaultCheck,
    Intent,
    ModuleCheck,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.engine import EngineStore, RuleEngineService
from collaboration_framework.host.adapters import OneShotHostAgentAdapter
from collaboration_framework.host.adapters.fakes import FakeHostAgent, FakeNarrationModel
from collaboration_framework.host.application import (
    ContextAssembler,
    HostAgentIntentResolver,
    Narrator,
    PlayerViewProjector,
    TurnExecutionError,
)
from collaboration_framework.host.ports import (
    HostAgentPort,
    IntentModelPort,
    NarrationModelPort,
)
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    TurnOutput,
    WebSocketOutput,
)

from app.adapters import (
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
    QwenChatCompletionsJsonClient,
)
from app.core.config import Settings, get_settings
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
ActionResultSink = Callable[[ActionResult], Awaitable[None]]

_PUBLIC_TOOL_LABELS = {
    "search_visible_entities": "守秘人正在查看当前场景",
    "get_visible_entity": "守秘人正在确认可见目标",
}


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
    intent: Intent
    candidates: tuple[SkillCheckCandidate, ...]
    difficulty: CheckDifficulty
    stored_roll_value: int | None = None


@dataclass(frozen=True)
class HostModelMetadata:
    provider: str
    model: str
    prompt_version: str = "trpg-host-intent-v2"


@dataclass(frozen=True)
class TurnApplication:
    """无 Room 内存状态的单回合应用入口。"""

    store: EngineStore
    engine: RuleEngineService
    intent_resolver: HostAgentIntentResolver
    narration_model: NarrationModelPort
    host_metadata: HostModelMetadata

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
        bootstrap_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id="view-projection",
            utterance="读取当前场景",
        )
        return await PlayerViewProjector(self.engine).project(bootstrap_input)

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
    ) -> WebSocketOutput:
        prepared = await self.prepare(
            room_id=room_id,
            player_id=player_id,
            client_action_id=client_action_id,
            utterance=utterance,
            on_event=on_event,
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
    ) -> PreparedTurn:
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
        async with self.store.transaction(room_id) as transaction:
            completed = await transaction.find_completed_action(client_action_id)
        if completed is not None:
            if completed.request.player_id != player_id or completed.request.actor_id != actor_id:
                raise ContractError("client_action_id belongs to another actor")
            intent = completed.request.intent
            candidates: tuple[SkillCheckCandidate, ...] = ()
            difficulty: CheckDifficulty = "regular"
            stored_roll_value = completed.request.roll_value
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
                intent = await self.intent_resolver.resolve(
                    HostAgentContext(
                        player_input=player_input,
                        player_view=view_before,
                    ),
                    on_event=observe_host_event,
                )
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
            intent=intent,
            candidates=candidates,
            difficulty=difficulty,
            stored_roll_value=stored_roll_value,
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
        action_result = await self.engine.execute(
            ActionRequest(
                request_id=prepared.player_input.client_action_id,
                room_id=prepared.player_input.room_id,
                player_id=prepared.player_input.player_id,
                actor_id=prepared.player_input.actor_id,
                source_view_revision=prepared.view_before.revision,
                intent=intent,
                roll_value=(
                    roll_value if selected_skill is not None else prepared.stored_roll_value
                ),
            )
        )
        if on_action_result is not None:
            await on_action_result(action_result)
        await emit_turn_event(
            on_event,
            TurnPhaseChanged(
                correlation_id=prepared.player_input.client_action_id,
                phase="refreshing_player_view",
            ),
        )
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
        )
        try:
            narration = await Narrator(self.narration_model).narrate(narration_context)
        except Exception as exc:
            raise TurnExecutionError(
                "NARRATOR_FAILED",
                "规则结果已安全保存，但叙事生成失败，请重试原动作",
                retryable=True,
            ) from exc
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


def build_turn_application(
    store: EngineStore,
    engine: RuleEngineService,
    *,
    settings: Settings | None = None,
    host_agent: HostAgentPort | None = None,
    intent_resolver: HostAgentIntentResolver | None = None,
    intent_model: IntentModelPort | None = None,
    narration_model: NarrationModelPort | None = None,
    host_metadata: HostModelMetadata | None = None,
) -> TurnApplication:
    """Compose the sole production turn path around one HostAgentPort."""

    resolver_inputs = sum(
        value is not None for value in (host_agent, intent_resolver, intent_model)
    )
    if resolver_inputs > 1:
        raise ValueError("host_agent、intent_resolver、intent_model 只能提供一个")
    if narration_model is None:
        if resolver_inputs:
            raise ValueError("自定义 Host Agent 时必须同时提供 narration_model")
        intent_resolver, narration_model, host_metadata = _configured_models(
            settings or get_settings()
        )
    elif intent_resolver is None:
        if host_agent is not None:
            intent_resolver = HostAgentIntentResolver(host_agent)
        elif intent_model is not None:
            intent_resolver = HostAgentIntentResolver(OneShotHostAgentAdapter(intent_model))
        else:
            raise ValueError("必须提供 Host Agent 意图解析依赖")
    assert intent_resolver is not None
    host_metadata = host_metadata or HostModelMetadata(
        provider="custom",
        model="custom",
    )
    return TurnApplication(
        store=store,
        engine=engine,
        intent_resolver=intent_resolver,
        narration_model=narration_model,
        host_metadata=host_metadata,
    )


def _configured_models(
    settings: Settings,
) -> tuple[
    HostAgentIntentResolver,
    NarrationModelPort,
    HostModelMetadata,
]:
    if settings.host_model_provider == "fake":
        return (
            HostAgentIntentResolver(FakeHostAgent()),
            FakeNarrationModel(),
            HostModelMetadata(provider="fake", model="deterministic"),
        )
    if settings.host_model_provider == "qwen":
        if settings.qwen_api_key is None:
            raise ValueError("Qwen Host 模型缺少 API key")
        host_agent = build_qwen_host_agent(
            {
                "HOST_AGENT_API_KEY": settings.qwen_api_key.get_secret_value(),
                "HOST_AGENT_BASE_URL": settings.qwen_base_url,
                "HOST_AGENT_MODEL": settings.qwen_model,
                "HOST_AGENT_MAX_TURNS": str(settings.host_agent_max_turns),
                "HOST_AGENT_MAX_TOOL_CALLS": str(settings.host_agent_max_tool_calls),
                "HOST_AGENT_TOOL_TIMEOUT_SECONDS": str(settings.host_agent_tool_timeout_seconds),
                "HOST_AGENT_TIMEOUT_SECONDS": str(settings.host_agent_timeout_seconds),
            }
        )
        client = QwenChatCompletionsJsonClient(
            api_key=settings.qwen_api_key.get_secret_value(),
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            timeout_seconds=settings.qwen_timeout_seconds,
        )
        return (
            HostAgentIntentResolver(host_agent),
            PromptNarrationModel(client),
            HostModelMetadata(
                provider="qwen",
                model=settings.qwen_model,
            ),
        )
    else:
        if settings.openai_api_key is None:
            raise ValueError("OpenAI Host 模型缺少 API key")
        client = OpenAIResponsesJsonClient(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
        )
        return (
            HostAgentIntentResolver(OneShotHostAgentAdapter(PromptIntentModel(client))),
            PromptNarrationModel(client),
            HostModelMetadata(
                provider="openai",
                model=settings.openai_model,
            ),
        )


turn_application = build_turn_application(engine_store, rule_engine_service)

__all__ = [
    "ActorResolutionError",
    "TurnApplication",
    "build_turn_application",
    "turn_application",
]
