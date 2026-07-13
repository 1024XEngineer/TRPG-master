"""模型适配层配置 —— 对应 master §6.3。「用哪个模型」是配置，不是代码。"""

from __future__ import annotations

import os
from typing import Literal, Optional

from pydantic import BaseModel

ModelRole = Literal["intent", "narrator", "npc", "qa", "summarizer"]
"""🆕 2026-07-11 补 'summarizer'（复盘摘要生成），非流式/大上下文/一次性，配置独立但 persona 复用 narrator 人格。"""


class ModelRoleParams(BaseModel):
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ModelRoleConfig(BaseModel):
    role: ModelRole
    provider: str  # 具体供应商标识
    model: str  # 具体型号
    params: Optional[ModelRoleParams] = None


# ===== 2026-07-13：先全部角色共用 DeepSeek，验证走通后再按角色差异化 =====
# provider/model 是非密配置，API Key 单独走环境变量（见 get_api_key），不混进
# ModelRoleConfig——避免这个可能被日志/序列化的对象里带上密钥。

PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
}

DEFAULT_MODEL_ROLE_CONFIGS: dict[ModelRole, ModelRoleConfig] = {
    role: ModelRoleConfig(role=role, provider="deepseek", model="deepseek-chat")
    for role in ("intent", "narrator", "npc", "qa", "summarizer")
}


def get_api_key(provider: str) -> str:
    env_var = f"{provider.upper()}_API_KEY"
    return os.environ[env_var]
