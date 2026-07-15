from host_orchestrator.schemas.output import WebSocketOutput
from host_orchestrator.schemas.player_input import PlayerInput


class WebSocketGateway:
    """TODO: validate transport data, invoke TurnPort, and emit output."""

    async def handle(self, player_input: PlayerInput) -> WebSocketOutput:
        raise NotImplementedError("TODO: adapt a WebSocket transport")
