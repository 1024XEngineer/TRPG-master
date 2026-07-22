"""The only composition root that knows concrete A/B/C implementations."""

from dataclasses import dataclass

from collaboration_framework.contracts import ModuleContent
from collaboration_framework.engine import FakeAtomicEngine, GameState
from collaboration_framework.host.adapters.fakes import (
    FakeIntentModel,
    FakeNarrationModel,
)
from collaboration_framework.host.application import (
    ContextAssembler,
    IntentParser,
    Narrator,
    Orchestrator,
    PlayerViewProjector,
)
from collaboration_framework.host.gateway import WebSocketGateway


@dataclass(frozen=True)
class FakeApplication:
    engine: FakeAtomicEngine
    orchestrator: Orchestrator
    websocket_gateway: WebSocketGateway


def build_fake_application(
    module_content: ModuleContent,
    game_state: GameState,
) -> FakeApplication:
    engine = FakeAtomicEngine(module_content, game_state)
    orchestrator = Orchestrator(
        context_assembler=ContextAssembler(),
        intent_parser=IntentParser(FakeIntentModel()),
        action_executor=engine,
        player_view_projector=PlayerViewProjector(engine),
        narrator=Narrator(FakeNarrationModel()),
    )
    return FakeApplication(
        engine=engine,
        orchestrator=orchestrator,
        websocket_gateway=WebSocketGateway(orchestrator),
    )
