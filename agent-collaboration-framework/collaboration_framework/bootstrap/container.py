"""The only composition root that knows concrete A/B/C implementations."""

from dataclasses import dataclass

from collaboration_framework.contracts import ModuleContent
from collaboration_framework.engine import (
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
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
    engine: RuleEngineService
    engine_store: InMemoryEngineStore
    orchestrator: Orchestrator
    websocket_gateway: WebSocketGateway


def build_fake_application(
    module_content: ModuleContent,
    game_state: GameState,
) -> FakeApplication:
    engine_store = InMemoryEngineStore()
    engine_store.register_room(
        module_content=module_content,
        initial_state=game_state,
    )
    engine = RuleEngineService(engine_store)
    orchestrator = Orchestrator(
        context_assembler=ContextAssembler(),
        intent_parser=IntentParser(FakeIntentModel()),
        action_executor=engine,
        player_view_projector=PlayerViewProjector(engine),
        narrator=Narrator(FakeNarrationModel()),
    )
    return FakeApplication(
        engine=engine,
        engine_store=engine_store,
        orchestrator=orchestrator,
        websocket_gateway=WebSocketGateway(orchestrator),
    )
