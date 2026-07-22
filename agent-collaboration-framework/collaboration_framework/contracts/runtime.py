"""Runtime input contracts shared by the gateway, host, and engine."""

from pydantic import Field

from .common import ContractModel


class PlayerInput(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    client_action_id: str = Field(min_length=1)
    utterance: str = Field(min_length=1)
