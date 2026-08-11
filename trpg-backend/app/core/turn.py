"""主持编排与规则引擎的后端组合根（issues #122 / #123）。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import anyio
import httpx
import structlog
from collaboration_framework.contracts import (
    ActionResult,
    ContractError,
    PlayerInput,
    PlayerView,
    PlayerViewScope,
)
from collaboration_framework.engine import EngineStore, RuleEngineService
from collaboration_framework.host.adapters.fakes import (
    FakeOpeningNarrationModel,
)
from collaboration_framework.host.adapters.openai_agents import PROMPT_VERSION
from collaboration_framework.host.application import (
    ContextAssembler,
    OpeningNarrationValidationError,
    OpeningNarrator,
    PlayerViewProjector,
    deterministic_opening_narration,
)
from collaboration_framework.host.ports import (
    OpeningNarrationModelPort,
)
from collaboration_framework.host.schemas import (
    NarrationOutput,
    RecentHistoryBudget,
    RecentTurnContext,
)
from pydantic import ValidationError

from app.adapters import (
    DeepSeekChatCompletionsJsonClient,
    OpenAIResponsesJsonClient,
    PromptOpeningNarrationModel,
    QwenChatCompletionsJsonClient,
)
from app.core.config import Settings, get_settings, secret_value
from app.core.engine import engine_store, rule_engine_service

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
class SessionViewApplication:
    """房间视图与开场叙事。

    `room.join` 要推当前视图，`game.start` 要生成开场——两件事都只依赖投影器和开场
    模型。它们本来和 v2 单动作入口挤在同一个类里；先拆出来，删 v2 动作路径（#226）
    时才不会把 v3 同样需要的这两件事一起带走。动作本身现在只走 ActionPlan。
    """

    store: EngineStore
    engine: RuleEngineService
    opening_narration_model: OpeningNarrationModelPort
    host_metadata: HostModelMetadata
    opening_narration_mode: Literal["model", "template"]
    opening_narration_timeout_seconds: float

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
                    narration = await OpeningNarrator(self.opening_narration_model).narrate(context)
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


def _configured_opening_models(
    settings: Settings,
) -> tuple[OpeningNarrationModelPort, HostModelMetadata]:
    """Pick the opening-narration model for the configured Host provider.

    v2 删除之后这里只剩开场叙事一个消费者：动作路径的 Host Agent 与回合叙事模型
    由 build_action_plan_turn_application 自己装配（#226）。
    """

    if settings.host_model_provider == "fake":
        return (
            FakeOpeningNarrationModel(),
            HostModelMetadata(provider="fake", model="deterministic"),
        )
    if settings.host_model_provider == "deepseek":
        if settings.deepseek_api_key is None:
            raise ValueError("DeepSeek Host 模型缺少 API key")
        return (
            PromptOpeningNarrationModel(
                DeepSeekChatCompletionsJsonClient(
                    api_key=secret_value(settings.deepseek_api_key),
                    base_url=settings.deepseek_base_url,
                    model=settings.deepseek_model,
                    timeout_seconds=settings.deepseek_timeout_seconds,
                )
            ),
            HostModelMetadata(provider="deepseek", model=settings.deepseek_model),
        )
    if settings.host_model_provider == "qwen":
        if settings.qwen_api_key is None:
            raise ValueError("Qwen Host 模型缺少 API key")
        return (
            PromptOpeningNarrationModel(
                QwenChatCompletionsJsonClient(
                    api_key=secret_value(settings.qwen_api_key),
                    base_url=settings.qwen_base_url,
                    model=settings.qwen_model,
                    timeout_seconds=settings.qwen_timeout_seconds,
                )
            ),
            HostModelMetadata(provider="qwen", model=settings.qwen_model),
        )
    if settings.openai_api_key is None:
        raise ValueError("OpenAI Host 模型缺少 API key")
    return (
        PromptOpeningNarrationModel(
            OpenAIResponsesJsonClient(
                api_key=secret_value(settings.openai_api_key),
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                timeout_seconds=settings.openai_timeout_seconds,
            )
        ),
        HostModelMetadata(provider="openai", model=settings.openai_model),
    )


def build_session_view_application(
    store: EngineStore,
    engine: RuleEngineService,
    *,
    settings: Settings | None = None,
    opening_narration_model: OpeningNarrationModelPort | None = None,
    host_metadata: HostModelMetadata | None = None,
) -> SessionViewApplication:
    """Compose the room-view / opening half of the session."""

    resolved_settings = settings or get_settings()
    if opening_narration_model is None:
        opening_narration_model, configured_metadata = _configured_opening_models(resolved_settings)
        host_metadata = host_metadata or configured_metadata
    return SessionViewApplication(
        store=store,
        engine=engine,
        opening_narration_model=opening_narration_model,
        host_metadata=host_metadata or HostModelMetadata(provider="custom", model="custom"),
        opening_narration_mode=resolved_settings.opening_narration_mode,
        opening_narration_timeout_seconds=(resolved_settings.opening_narration_timeout_seconds),
    )


session_view_application = build_session_view_application(engine_store, rule_engine_service)

__all__ = [
    "ActorResolutionError",
    "HostModelMetadata",
    "OpeningGenerationResult",
    "SessionViewApplication",
    "build_session_view_application",
    "session_view_application",
]
