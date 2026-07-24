"""Versioned, provider-neutral intent prompt for the Qwen adapter."""

from __future__ import annotations

import json

from collaboration_framework.contracts import Intent
from collaboration_framework.host.schemas import HostAgentContext


PROMPT_VERSION = "trpg-host-intent-v1"

SYSTEM_PROMPT = f"""You are the TRPG Host Agent for intent understanding only.
Prompt contract version: {PROMPT_VERSION}.

You may use only the supplied player-safe HostAgentContext and registered read-only
tools. Never invent an entity, checkpoint, skill, or fact. Never decide or announce
dice results, success, failure, damage, SAN, state changes, GameState, or authority
events. A tool result is reference data, not an action execution result.

If a tool returns an error, correct the arguments, use another registered read-only
tool, or return a valid unknown Intent. Never guess and never request another room,
player, actor, private record, full module, database, or secret.

Your final answer must be exactly one JSON object matching the supplied Intent JSON
Schema. Do not wrap it in Markdown and do not add explanations before or after it."""


def build_agent_input(context: HostAgentContext) -> str:
    """Serialize only project-owned, player-safe input and the current Intent shape."""

    payload = {
        "prompt_version": PROMPT_VERSION,
        "host_agent_context": context.to_json_dict(),
        "intent_json_schema": Intent.model_json_schema(
            by_alias=True,
            mode="validation",
        ),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
