"""应用配置。

用 pydantic-settings 从环境变量 / `.env` 文件里读配置，而不是散落在代码各处的
硬编码常量或裸 `os.environ.get(...)`——好处是每个配置项都有类型、默认值和校验，
IDE 能补全，写错类型（比如 ENABLE_DOCS 传了个不是 true/false 的字符串）会在启动时
就报错，而不是运行到一半才炸。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def secret_value(value: str | SecretStr) -> str:
    if isinstance(value, str):
        return value
    return getattr(value, "get_secret_value")()  # noqa: B009


class Settings(BaseSettings):
    # env_file=".env"：本地开发时从 backend 目录下的 .env 文件读取（该文件已被
    # .gitignore 排除，不会进 git）；线上部署通常直接注入真实环境变量，.env 不存在也没关系。
    # extra="ignore"：.env 里出现未在下面声明的字段时不报错，方便同一份 .env
    # 文件里塞一些暂时用不到、以后可能会用的变量。
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # development：本地开发（默认）；production：线上；test：预留给测试环境用，
    # 目前测试套件是通过 fixture 直接覆盖依赖注入，不依赖这个值。
    app_env: Literal["development", "production", "test"] = "development"

    # 本地默认用 SQLite（aiosqlite 驱动），不需要额外起数据库就能跑通整个项目；
    # 线上把这个环境变量换成 PostgreSQL 的连接串（asyncpg 驱动）即可切换，
    # 业务代码（models/service）完全不用改，因为都是通过 SQLAlchemy ORM 访问的。
    database_url: str = "sqlite+aiosqlite:///./app.db"

    # 是否开启 FastAPI 自带的 /docs、/redoc、/openapi.json。本地开发默认开，
    # 线上环境建议在环境变量里设为 false，避免把接口细节暴露给外部。
    enable_docs: bool = True

    # structlog 的最低日志级别，比如 "DEBUG"/"INFO"/"WARNING"。
    log_level: str = "INFO"

    # 允许跨域请求的前端来源列表，交给 main.py 里的 CORSMiddleware 使用。
    # 本地默认放行 Vite 开发服务器的默认端口 9877。
    cors_origins: list[str] = ["http://localhost:9877", "http://127.0.0.1:9877"]

    # 默认使用确定性的离线 Fake，便于本地启动和测试；显式切到远程 provider
    # 后，Host/Narrator 才会调用远程模型。
    host_model_provider: Literal["fake", "openai", "qwen", "deepseek"] = "fake"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        min_length=1,
    )
    openai_model: str = Field(default="gpt-5.6-luna", min_length=1)
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=1,
    )
    qwen_model: str = Field(default="qwen3.7-plus", min_length=1)
    qwen_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        min_length=1,
    )
    deepseek_model: str = Field(default="deepseek-chat", min_length=1)
    deepseek_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    host_agent_max_turns: int = Field(default=6, gt=0, le=20)
    host_agent_max_tool_calls: int = Field(default=8, gt=0, le=50)
    host_agent_tool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    host_agent_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    opening_narration_mode: Literal["model", "template"] = "model"
    opening_narration_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    recent_history_enabled: bool = True
    recent_history_max_turns: int = Field(default=6, ge=1, le=24)
    recent_history_max_chars: int = Field(default=6000, ge=2)

    # 角色生图是建卡完成后的可选扩展。默认关闭且使用离线 provider，
    # 只有显式开启并切换 provider 才会调用 DeepSeek / 阿里云。
    character_portrait_enabled: bool = False
    portrait_prompt_provider: Literal["deterministic", "deepseek"] = "deterministic"
    portrait_image_provider: Literal["mock", "dashscope"] = "mock"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        min_length=1,
    )
    dashscope_image_model: str = Field(default="wan2.2-t2i-flash", min_length=1)
    portrait_generation_timeout_seconds: float = Field(default=120.0, gt=0, le=300)

    # 讨论区/Narrator 主线的兼容配置：未配置时使用确定性占位叙事，测试可通过
    # 延迟钩子稳定覆盖行动锁并发分支。
    narrator_delay_seconds: float = Field(default=0.0, ge=0, le=120)

    @model_validator(mode="after")
    def validate_host_model(self) -> Settings:
        if self.host_model_provider == "openai" and (
            self.openai_api_key is None or not secret_value(self.openai_api_key).strip()
        ):
            raise ValueError("HOST_MODEL_PROVIDER=openai 时必须设置 OPENAI_API_KEY")
        if self.host_model_provider == "qwen" and (
            self.qwen_api_key is None or not secret_value(self.qwen_api_key).strip()
        ):
            raise ValueError("HOST_MODEL_PROVIDER=qwen 时必须设置 QWEN_API_KEY")
        if self.host_model_provider == "deepseek" and (
            self.deepseek_api_key is None or not secret_value(self.deepseek_api_key).strip()
        ):
            raise ValueError("HOST_MODEL_PROVIDER=deepseek 时必须设置 DEEPSEEK_API_KEY")
        if (
            self.character_portrait_enabled
            and self.portrait_prompt_provider == "deepseek"
            and (self.deepseek_api_key is None or not secret_value(self.deepseek_api_key).strip())
        ):
            raise ValueError("角色生图使用 DeepSeek 时必须设置 DEEPSEEK_API_KEY")
        if (
            self.character_portrait_enabled
            and self.portrait_image_provider == "dashscope"
            and (self.dashscope_api_key is None or not secret_value(self.dashscope_api_key).strip())
        ):
            raise ValueError("角色生图使用 DashScope 时必须设置 DASHSCOPE_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一的 Settings 实例。

    加 @lru_cache 是因为 Settings() 在实例化时会去读环境变量/.env 文件，
    没必要每次调用都重新读一遍磁盘——缓存下来，全进程共享同一份配置对象。
    """
    return Settings()
