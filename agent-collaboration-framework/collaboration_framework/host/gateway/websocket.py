"""Framework-free WebSocket boundary skeleton."""

from collaboration_framework.contracts import PlayerInput
from collaboration_framework.host.ports import TurnPort
from collaboration_framework.host.schemas import WebSocketOutput


class WebSocketGateway:
    def __init__(self, turn: TurnPort) -> None:
        self._turn = turn

    async def handle(self, player_input: PlayerInput) -> WebSocketOutput:
        turn_output = await self._turn.run(player_input)
        return turn_output.to_websocket_output()
