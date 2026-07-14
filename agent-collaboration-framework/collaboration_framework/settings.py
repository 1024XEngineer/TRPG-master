"""Environment-backed settings without coupling orchestration to a provider SDK."""

from __future__ import annotations

import os
from typing import Literal

from .contracts import ContractModel


class AgentSettings(ContractModel):
    mode: Literal["fake", "pydantic-ai"] = "fake"
    model_name: str = "openai:gpt-5-mini"

    @classmethod
    def from_env(cls) -> AgentSettings:
        return cls(
            mode=os.getenv("AIDM_AGENT_MODE", "fake"),
            model_name=os.getenv("PYDANTIC_AI_MODEL", "openai:gpt-5-mini"),
        )
