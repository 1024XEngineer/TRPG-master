"""Runtime input contracts shared by the gateway, host, and engine."""

import hashlib
import json

from pydantic import Field

from .common import ContractModel


class PlayerInput(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    client_action_id: str = Field(min_length=1)
    utterance: str = Field(min_length=1)


def player_input_fingerprint(player_input: PlayerInput) -> str:
    """Return a stable opaque identity for one normalized player request."""

    canonical = json.dumps(
        {
            "actor_id": player_input.actor_id,
            "client_action_id": player_input.client_action_id,
            "player_id": player_input.player_id,
            "room_id": player_input.room_id,
            "utterance": player_input.utterance,
            "version": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
