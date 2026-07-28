"""Explicit production composition for OpenAI-compatible Host Agent adapters."""

from __future__ import annotations

from collections.abc import Mapping
import os

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pydantic import ValidationError

from collaboration_framework.host.adapters.openai_agents import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    OpenAICompatibleHostAgentAdapter,
    OpenAICompatibleHostAgentConfig,
)
from collaboration_framework.host.application.tool_registry import ToolRegistry
from collaboration_framework.host.tools import build_player_view_tool_registry


class HostAgentConfigurationError(RuntimeError):
    """Safe bootstrap error that never includes secret configuration values."""


def build_qwen_host_agent(
    environ: Mapping[str, str] | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
) -> OpenAICompatibleHostAgentAdapter:
    """Build Qwen with its provider-specific thinking switch disabled."""

    return _build_host_agent(
        environ,
        tool_registry=tool_registry,
        model_settings_extra_body={"enable_thinking": False},
        default_base_url=DEFAULT_BASE_URL,
        default_model=DEFAULT_MODEL,
    )


def build_deepseek_host_agent(
    environ: Mapping[str, str] | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
) -> OpenAICompatibleHostAgentAdapter:
    """Build DeepSeek without sending Qwen-only request fields."""

    return _build_host_agent(
        environ,
        tool_registry=tool_registry,
        model_settings_extra_body=None,
        default_base_url=DEEPSEEK_BASE_URL,
        default_model=DEEPSEEK_MODEL,
    )


def _build_host_agent(
    environ: Mapping[str, str] | None,
    *,
    tool_registry: ToolRegistry | None,
    model_settings_extra_body: dict[str, bool] | None,
    default_base_url: str,
    default_model: str,
) -> OpenAICompatibleHostAgentAdapter:
    """Build a validated OpenAI-compatible Chat Completions Host Agent."""

    source = os.environ if environ is None else environ
    api_key = source.get("HOST_AGENT_API_KEY", "")
    if not api_key.strip():
        raise HostAgentConfigurationError("HOST_AGENT_API_KEY is required")

    try:
        config = OpenAICompatibleHostAgentConfig(
            api_key=api_key,
            base_url=source.get("HOST_AGENT_BASE_URL", default_base_url),
            model=source.get("HOST_AGENT_MODEL", default_model),
            max_turns=_read_int(source, "HOST_AGENT_MAX_TURNS", 6),
            max_tool_calls=_read_int(source, "HOST_AGENT_MAX_TOOL_CALLS", 8),
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
            model_settings_extra_body=model_settings_extra_body,
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
    return OpenAICompatibleHostAgentAdapter(
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
