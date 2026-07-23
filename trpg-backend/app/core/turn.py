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
from collaboration_framework.host.schemas import WebSocketOutput

from app.core.engine import engine_store, rule_engine_service


class ActorResolutionError(ContractError):
    """当前房间运行时没有且仅有一个由该 Player 控制的 Actor。"""


@dataclass(frozen=True)
class TurnApplication:
    """无 Room 内存状态的单回合应用入口。"""

    store: EngineStore
    engine: RuleEngineService
    gateway: WebSocketGateway

    async def resolve_actor_id(self, room_id: str, player_id: str) -> str:
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
    ) -> WebSocketOutput:
        actor_id = await self.resolve_actor_id(room_id, player_id)
        return await self.gateway.handle(
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
) -> TurnApplication:
    """装配唯一的主持编排纵切；模型端口后续可原位替换为 #111 的生产 Adapter。"""

    orchestrator = Orchestrator(
        context_assembler=ContextAssembler(),
        intent_parser=IntentParser(FakeIntentModel()),
        action_executor=engine,
        player_view_projector=PlayerViewProjector(engine),
        narrator=Narrator(FakeNarrationModel()),
    )
    return TurnApplication(
        store=store,
        engine=engine,
        gateway=WebSocketGateway(orchestrator),
    )


turn_application = build_turn_application(engine_store, rule_engine_service)

__all__ = [
    "ActorResolutionError",
    "TurnApplication",
    "build_turn_application",
    "turn_application",
]
