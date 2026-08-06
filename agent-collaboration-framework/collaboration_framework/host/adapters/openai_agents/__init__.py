"""OpenAI Agents SDK Host Agent adapter for compatible chat providers."""

from .action_plan_prompt import (
    current_step_adjudication_instructions,
    host_turn_decision_instructions,
)
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
    "current_step_adjudication_instructions",
    "host_turn_decision_instructions",
]
