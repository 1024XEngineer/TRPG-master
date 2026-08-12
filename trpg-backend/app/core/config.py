"""应用配置。

用 pydantic-settings 从环境变量 / `.env` 文件里读配置，而不是散落在代码各处的
硬编码常量或裸 `os.environ.get(...)`——好处是每个配置项都有类型、默认值和校验，
IDE 能补全，写错类型（比如 ENABLE_DOCS 传了个不是 true/false 的字符串）会在启动时
就报错，而不是运行到一半才炸。
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.adapters.structured_http import ModelClientRetryPolicy


def secret_value(value: str | SecretStr) -> str:
    if isinstance(value, str):
        return value
    return getattr(value, "get_secret_value")()  # noqa: B009


class HostSpeechVoiceConfig(BaseModel):
    """部署允许在房间里选择的豆包音色。"""

    # 部署文档沿用豆包 API 的 voiceType；populate_by_name 同时保留 Python
    # 侧 voice_type，避免业务代码为了环境变量格式到处使用 camelCase。
    model_config = ConfigDict(populate_by_name=True)

    voice_type: str = Field(alias="voiceType", min_length=1)
    label: str = Field(min_length=1)


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
    # 结构化输出请求的传输层重试，三个 provider 共用。只覆盖超时、连接错误、5xx
    # 与 429；其余 4xx 立即失败。默认一次重试，避免一次瞬态故障就让整个回合报废。
    model_client_max_attempts: int = Field(default=2, ge=1, le=5)
    model_client_retry_backoff_seconds: float = Field(default=0.5, gt=0, le=10)
    # 一键建卡的规则数值始终由本地 COC7 生成器负责；此开关只决定八项背景文字
    # 是否交给 DeepSeek 创作。模型失败时服务层会回退到生成器内置模板。
    character_background_provider: Literal["deterministic", "deepseek"] = "deterministic"
    host_agent_max_turns: int = Field(default=6, gt=0, le=20)
    host_agent_max_tool_calls: int = Field(default=8, gt=0, le=50)
    host_agent_tool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    host_agent_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    opening_narration_mode: Literal["model", "template"] = "model"
    # 10 秒对真实 provider 太紧：DeepSeek 生成开场稳定在 10s 上下，几乎每局都
    # 撞上超时、退回确定性模板——玩家看到的就是"开场变死板了"，而日志里是
    # opening_narration_completed result=fallback failure_category=timeout。
    # 开场期间前端已经收到 opening.started 并显示生成中，等待是可见的。
    opening_narration_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    recent_history_enabled: bool = True
    recent_history_max_turns: int = Field(default=6, ge=1, le=24)
    recent_history_max_chars: int = Field(default=6000, ge=2)
    action_plan_max_steps: int = Field(default=32, ge=2, le=256)
    action_plan_max_steps_per_advance: int = Field(default=3, ge=1, le=32)
    action_plan_max_repair_attempts: int = Field(default=1, ge=0, le=8)
    # Deterministic cross-process E2E hook. Production and development always
    # use the Engine's cryptographic dice source; this value is honored only
    # when APP_ENV=test.
    test_fixed_dice_roll: int | None = Field(default=None, ge=1, le=100)

    # 角色生图是建卡完成后的可选操作，入口默认开启。没有远程 Key 时
    # auto provider 仍然使用离线 mock，不会因为修改默认值而产生费用。
    character_portrait_enabled: bool = True
    portrait_prompt_provider: Literal["deterministic", "deepseek"] = "deterministic"
    portrait_image_provider: Literal["auto", "mock", "dashscope", "sufy"] = "auto"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        min_length=1,
    )
    dashscope_image_model: str = Field(default="wan2.2-t2i-flash", min_length=1)
    sufy_api_key: SecretStr | None = None
    sufy_base_url: str = Field(default="https://openai.sufy.com/v1", min_length=1)
    sufy_image_model: str = Field(default="google/gemini-3-pro-image", min_length=1)
    # 项目内置参考图只由后端读取并转成内存中的 Data URI，不通过前端或公开静态目录暴露。
    # 留空或文件不可读时，角色生图自动降级为纯提示词模式。
    portrait_reference_image_path: str = "app/assets/portrait-style-reference.png"
    portrait_generation_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    # 生图服务返回的 URL/Data URI 必须先由后端下载、解码并校验，再持久化为头像。
    # 该上限同时约束远程响应体和解码后的原始文件，避免异常响应耗尽内存或撑大数据库。
    portrait_max_image_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    portrait_image_download_timeout_seconds: float = Field(default=15.0, gt=0, le=60)

    # AI 主持人语音：默认关闭，未配置豆包凭证时不影响应用启动或文字游戏流程。
    host_speech_provider: Literal["disabled", "fake", "doubao"] = "disabled"
    doubao_tts_api_key: SecretStr | None = None
    doubao_tts_resource_id: str = "seed-tts-2.0"
    doubao_tts_voices: list[HostSpeechVoiceConfig] = Field(default_factory=list)
    doubao_tts_default_voice_type: str | None = None
    doubao_tts_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    host_speech_max_sentence_bytes: int = Field(default=900, ge=100, le=4000)
    host_speech_cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    host_speech_cache_max_bytes: int = Field(default=67_108_864, ge=0)
    host_speech_player_requests_per_minute: int = Field(default=60, ge=1, le=600)
    host_speech_room_misses_per_minute: int = Field(default=30, ge=1, le=600)
    host_speech_max_concurrency: int = Field(default=8, ge=1, le=64)

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
        if self.character_background_provider == "deepseek" and (
            self.deepseek_api_key is None or not secret_value(self.deepseek_api_key).strip()
        ):
            raise ValueError("CHARACTER_BACKGROUND_PROVIDER=deepseek 时必须设置 DEEPSEEK_API_KEY")
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
        if (
            self.character_portrait_enabled
            and self.portrait_image_provider == "sufy"
            and (self.sufy_api_key is None or not secret_value(self.sufy_api_key).strip())
        ):
            raise ValueError("角色生图使用 Sufy 时必须设置 SUFY_API_KEY")
        if self.host_speech_provider == "doubao":
            required = {
                "DOUBAO_TTS_API_KEY": (
                    secret_value(self.doubao_tts_api_key)
                    if self.doubao_tts_api_key is not None
                    else None
                ),
                "DOUBAO_TTS_DEFAULT_VOICE_TYPE": self.doubao_tts_default_voice_type,
            }
            missing = [name for name, value in required.items() if not value or not value.strip()]
            if missing:
                raise ValueError("HOST_SPEECH_PROVIDER=doubao 时缺少配置：" + ", ".join(missing))
            allowed = {voice.voice_type for voice in self.doubao_tts_voices}
            if not allowed:
                raise ValueError("HOST_SPEECH_PROVIDER=doubao 时必须配置 DOUBAO_TTS_VOICES")
            if self.doubao_tts_default_voice_type not in allowed:
                raise ValueError("DOUBAO_TTS_DEFAULT_VOICE_TYPE 必须属于 DOUBAO_TTS_VOICES")
        return self


def model_client_retry_policy(settings: Settings) -> ModelClientRetryPolicy:
    """把重试配置翻成 client 层的策略。

    每一个 StructuredJsonClient 的构造点都应该经过这里，否则该 client 会静默地
    吃默认值、无视 `MODEL_CLIENT_*`，运维就没法为它调整或关闭重试。

    在函数体内 import：`app.adapters` 的包初始化会间接回到 `app.core.db`，
    放到模块顶部会形成循环 import。
    """

    from app.adapters.structured_http import ModelClientRetryPolicy

    return ModelClientRetryPolicy(
        max_attempts=settings.model_client_max_attempts,
        backoff_seconds=settings.model_client_retry_backoff_seconds,
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一的 Settings 实例。

    加 @lru_cache 是因为 Settings() 在实例化时会去读环境变量/.env 文件，
    没必要每次调用都重新读一遍磁盘——缓存下来，全进程共享同一份配置对象。
    """
    return Settings()
