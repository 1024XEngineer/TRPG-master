"""主持编排与规则引擎的后端组合根（issues #122 / #123）。"""

from __future__ import annotations

from dataclasses import dataclass

from collaboration_framework.contracts import ContractError, PlayerInput
from collaboration_framework.engine import EngineStore, RuleEngineService
from collaboration_framework.host.adapters.fakes import FakeIntentModel, FakeNarrationModel
from collaboration_framework.host.application import (
    ContextAssembler,
    IntentParser,
    Narrator,
    Orchestrator,
    PlayerViewProjector,
)
from collaboration_framework.host.gateway import WebSocketGateway
from collaboration_framework.host.ports import IntentModelPort, NarrationModelPort
from collaboration_framework.host.schemas import WebSocketOutput

from app.adapters import (
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
    QwenChatCompletionsJsonClient,
)
from app.core.config import Settings, get_settings
from app.core.engine import engine_store, rule_engine_service


class ActorResolutionError(ContractError):
    """当前房间运行时没有且仅有一个由该 Player 控制的 Actor。"""


@dataclass(frozen=True)
class TurnApplication:
    """无 Room 内存状态的单回合应用入口。"""

    store: EngineStore
    engine: RuleEngineService
    intent_model: IntentModelPort
    narration_model: NarrationModelPort

    async def resolve_actor_id(self, room_id: str, player_id: str) -> str:
        actor_id, _ = await self._load_turn_scope(room_id, player_id)
        return actor_id

    async def _load_turn_scope(
        self,
        room_id: str,
        player_id: str,
    ) -> tuple[str, str]:
        async with self.store.transaction(room_id) as transaction:
            runtime = await transaction.load_runtime()
        actor_ids = [
            actor_id
            for actor_id, actor in runtime.game_state.actors.items()
            if actor.player_id == player_id
        ]
        if len(actor_ids) != 1:
            raise ActorResolutionError("当前玩家没有唯一绑定的局内 Actor")
        return actor_ids[0], runtime.module_content.background

    async def handle(
        self,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        utterance: str,
    ) -> WebSocketOutput:
        actor_id, background = await self._load_turn_scope(room_id, player_id)
        orchestrator = Orchestrator(
            context_assembler=ContextAssembler(background),
            intent_parser=IntentParser(self.intent_model),
            action_executor=self.engine,
            player_view_projector=PlayerViewProjector(self.engine),
            narrator=Narrator(self.narration_model),
        )
        return await WebSocketGateway(orchestrator).handle(
            PlayerInput(
                room_id=room_id,
                player_id=player_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                utterance=utterance,
            )
        )


def build_turn_application(
    store: EngineStore,
    engine: RuleEngineService,
    *,
    settings: Settings | None = None,
    intent_model: IntentModelPort | None = None,
    narration_model: NarrationModelPort | None = None,
) -> TurnApplication:
    """装配主持纵切；未启用远程模型时保持确定性的离线模式。"""

    if (intent_model is None) != (narration_model is None):
        raise ValueError("intent_model 与 narration_model 必须同时提供")
    if intent_model is None or narration_model is None:
        intent_model, narration_model = _configured_models(settings or get_settings())
    return TurnApplication(
        store=store,
        engine=engine,
        intent_model=intent_model,
        narration_model=narration_model,
    )


def _configured_models(
    settings: Settings,
) -> tuple[IntentModelPort, NarrationModelPort]:
    if settings.host_model_provider == "fake":
        return FakeIntentModel(), FakeNarrationModel()
    if settings.host_model_provider == "qwen":
        if settings.qwen_api_key is None:
            raise ValueError("Qwen Host 模型缺少 API key")
        client = QwenChatCompletionsJsonClient(
            api_key=settings.qwen_api_key.get_secret_value(),
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            timeout_seconds=settings.qwen_timeout_seconds,
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
    return PromptIntentModel(client), PromptNarrationModel(client)


turn_application = build_turn_application(engine_store, rule_engine_service)

__all__ = [
    "ActorResolutionError",
    "TurnApplication",
    "build_turn_application",
    "turn_application",
]
