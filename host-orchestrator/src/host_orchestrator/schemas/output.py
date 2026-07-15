from typing import Literal

from host_orchestrator.schemas.base import ContractModel, SchemaVersion
from host_orchestrator.schemas.narration import NarrationOutput
from host_orchestrator.schemas.player_view import PlayerView


class TurnOutput(ContractModel):
    schema_version: SchemaVersion = "1"
    request_id: str
    room_id: str
    player_id: str
    narration: NarrationOutput
    player_view: PlayerView


class WebSocketOutput(ContractModel):
    schema_version: SchemaVersion = "1"
    event_id: str
    event_type: Literal["turn.completed"] = "turn.completed"
    correlation_id: str
    room_id: str
    player_id: str
    payload: TurnOutput
