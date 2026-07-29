"""OpenAI Agents SDK Host Agent adapter for compatible chat providers."""

from .adapter import OpenAICompatibleHostAgentAdapter, QwenHostAgentAdapter
from .config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAICompatibleHostAgentConfig,
    QwenHostAgentConfig,
)
from .prompt import PROMPT_VERSION

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "OpenAICompatibleHostAgentAdapter",
    "OpenAICompatibleHostAgentConfig",
    "PROMPT_VERSION",
    "QwenHostAgentAdapter",
    "QwenHostAgentConfig",
]
