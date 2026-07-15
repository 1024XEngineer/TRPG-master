from typing import Literal

from host_orchestrator.schemas.base import ContractModel, SchemaVersion


class PlayerInput(ContractModel):
    schema_version: SchemaVersion = "1"
    request_id: str
    room_id: str
    player_id: str
    actor_id: str
    text: str
    input_mode: Literal["text"] = "text"
