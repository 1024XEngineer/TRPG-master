"""Explicit production composition for the Qwen Host Agent adapter."""

from __future__ import annotations

from collections.abc import Mapping
import os

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pydantic import ValidationError

from collaboration_framework.host.adapters.openai_agents import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    QwenHostAgentAdapter,
    QwenHostAgentConfig,
)
from collaboration_framework.host.application.tool_registry import ToolRegistry
from collaboration_framework.host.tools import build_player_view_tool_registry


class HostAgentConfigurationError(RuntimeError):
    """Safe bootstrap error that never includes secret configuration values."""


def build_qwen_host_agent(
    environ: Mapping[str, str] | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
) -> QwenHostAgentAdapter:
    """Build the real adapter only when explicitly called by a composition root."""

    source = os.environ if environ is None else environ
    api_key = source.get("HOST_AGENT_API_KEY", "")
    if not api_key.strip():
        raise HostAgentConfigurationError("HOST_AGENT_API_KEY is required")

    try:
        config = QwenHostAgentConfig(
            api_key=api_key,
            base_url=source.get("HOST_AGENT_BASE_URL", DEFAULT_BASE_URL),
            model=source.get("HOST_AGENT_MODEL", DEFAULT_MODEL),
            max_turns=_read_int(source, "HOST_AGENT_MAX_TURNS", 6),
            max_tool_calls=_read_int(
                source,
                "HOST_AGENT_MAX_TOOL_CALLS",
                8,
            ),
            tool_timeout_seconds=_read_float(
                source,
                "HOST_AGENT_TOOL_TIMEOUT_SECONDS",
                5,
            ),
            timeout_seconds=_read_float(
                source,
                "HOST_AGENT_TIMEOUT_SECONDS",
                30,
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise HostAgentConfigurationError(
            "Host Agent configuration is invalid"
        ) from exc

    client = AsyncOpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
    )
    model = OpenAIChatCompletionsModel(
        model=config.model,
        openai_client=client,
    )
    return QwenHostAgentAdapter(
        model=model,
        tool_registry=tool_registry or build_player_view_tool_registry(),
        config=config,
    )


def _read_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    return int(environ.get(name, str(default)))


def _read_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    return float(environ.get(name, str(default)))
