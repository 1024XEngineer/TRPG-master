"""OpenAI Agents SDK Host Agent adapter for compatible chat providers."""

from .adapter import OpenAICompatibleHostAgentAdapter, QwenHostAgentAdapter
from .config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAICompatibleHostAgentConfig,
    QwenHostAgentConfig,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OpenAICompatibleHostAgentAdapter",
    "OpenAICompatibleHostAgentConfig",
    "QwenHostAgentAdapter",
    "QwenHostAgentConfig",
]
