"""主持编排与规则引擎的后端组合根（issues #122 / #123）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from collaboration_framework.contracts import (
    ActionRequest,
    ContractError,
    DefaultCheck,
    Intent,
    ModuleCheck,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.engine import EngineStore, RuleEngineService
from collaboration_framework.host.adapters.fakes import FakeIntentModel, FakeNarrationModel
from collaboration_framework.host.application import (
    ContextAssembler,
    IntentParser,
    Narrator,
    PlayerViewProjector,
)
from collaboration_framework.host.ports import IntentModelPort, NarrationModelPort
from collaboration_framework.host.schemas import TurnOutput, WebSocketOutput

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


CheckDifficulty = Literal["regular", "hard", "extreme"]


@dataclass(frozen=True)
class SkillCheckCandidate:
    id: str
    name: str
    target_value: int


@dataclass(frozen=True)
class PreparedTurn:
    player_input: PlayerInput
    background: str
    view_before: PlayerView
    intent: Intent
    candidates: tuple[SkillCheckCandidate, ...]
    difficulty: CheckDifficulty
    stored_roll_value: int | None = None


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
        prepared = await self.prepare(
            room_id=room_id,
            player_id=player_id,
            client_action_id=client_action_id,
            utterance=utterance,
        )
        return (await self.complete(prepared)).to_websocket_output()

    async def prepare(
        self,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        utterance: str,
    ) -> PreparedTurn:
        actor_id, background = await self._load_turn_scope(room_id, player_id)
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
            context_assembler = ContextAssembler(background)
            intent = await IntentParser(self.intent_model).parse(
                context_assembler.for_intent(player_input, view_before)
            )
            candidates, difficulty = self._check_candidates(intent, view_before)
            stored_roll_value = None
        return PreparedTurn(
            player_input=player_input,
            background=background,
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
        projector = PlayerViewProjector(self.engine)
        view_after = await projector.refresh(prepared.player_input, action_result)
        narration_context = ContextAssembler(prepared.background).for_narration(
            prepared.player_input,
            intent,
            action_result,
            view_after,
        )
        narration = await Narrator(self.narration_model).narrate(narration_context)
        return TurnOutput(
            status="clarification" if narration.kind == "clarification" else "completed",
            player_input=prepared.player_input,
            intent=intent,
            action_result=action_result,
            narration=narration,
            player_view=view_after,
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
            if value is None or skill_id in seen:
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
