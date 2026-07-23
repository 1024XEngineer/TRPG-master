"""Checkpoint 的玩家安全语义与权威免检条件。"""

from __future__ import annotations

from typing import Any

from app.runtime.state import ActorState


def checkpoint_label(checkpoint: dict[str, Any]) -> str:
    return str(checkpoint.get("action_label") or checkpoint["id"])


def checkpoint_bypass_reason(
    actor: ActorState,
    checkpoint: dict[str, Any],
) -> str | None:
    occupation = (actor.occupation or "").casefold()
    for condition in checkpoint.get("bypass_conditions", []):
        if condition.get("type") != "actor_occupation_contains_any":
            continue
        keywords = [str(value).casefold() for value in condition.get("values", [])]
        if any(keyword and keyword in occupation for keyword in keywords):
            return str(
                condition.get("reason")
                or f"{actor.occupation or '当前职业'}符合免检条件"
            )
    return None
