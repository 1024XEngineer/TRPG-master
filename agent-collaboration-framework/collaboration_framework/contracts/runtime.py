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
    interlocutor_id: str | None = Field(default=None, min_length=1)
    interlocutor_name: str | None = Field(default=None, min_length=1)


def player_input_fingerprint(player_input: PlayerInput) -> str:
    """Return a stable opaque identity for one normalized player request."""

    version = 1
    canonical_payload = {
        "actor_id": player_input.actor_id,
        "client_action_id": player_input.client_action_id,
        "player_id": player_input.player_id,
        "room_id": player_input.room_id,
        "utterance": player_input.utterance,
    }
    if player_input.interlocutor_id is not None or player_input.interlocutor_name is not None:
        # 兼容旧记录：没有 NPC 目标时继续沿用原 fingerprint；一旦有结构化接收者，
        # 只在这一路上切到新版本，避免把历史 turn 的幂等键全部打散。
        version = 2
        canonical_payload["interlocutor_id"] = player_input.interlocutor_id
        canonical_payload["interlocutor_name"] = player_input.interlocutor_name

    canonical = json.dumps(
        {**canonical_payload, "version": version},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
