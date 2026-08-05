"""应用配置。

用 pydantic-settings 从环境变量 / `.env` 文件里读配置，而不是散落在代码各处的
硬编码常量或裸 `os.environ.get(...)`——好处是每个配置项都有类型、默认值和校验，
IDE 能补全，写错类型（比如 ENABLE_DOCS 传了个不是 true/false 的字符串）会在启动时
就报错，而不是运行到一半才炸。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    host_agent_max_turns: int = Field(default=6, gt=0, le=20)
    host_agent_max_tool_calls: int = Field(default=8, gt=0, le=50)
    host_agent_tool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    host_agent_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    opening_narration_mode: Literal["model", "template"] = "model"
    opening_narration_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    recent_history_enabled: bool = True
    recent_history_max_turns: int = Field(default=6, ge=1, le=24)
    recent_history_max_chars: int = Field(default=6000, ge=2)

    # 讨论区/Narrator 主线的兼容配置：未配置时使用确定性占位叙事，测试可通过
    # 延迟钩子稳定覆盖行动锁并发分支。
    narrator_delay_seconds: float = Field(default=0.0, ge=0, le=120)

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

    # DeepSeek API Key（issue #107 地基，`app/core/narrator.py`）：配了就走真实
    # DeepSeek 生成叙事回应，不配（默认）自动回退到确定性的占位文案——CI/e2e
    # 环境不配这个变量，本地演示/线上环境按需配置。
    deepseek_api_key: str | None = None

    # ⚠️ 测试专用（issue #107）：让叙事生成人为延迟 N 秒后再返回，生产永远保持 0。
    # 存在的理由：无 key 时的占位叙事同步秒回，action.submit 的房间锁窗口只有
    # 微秒级，e2e 两个客户端"同时提交"永远压不中 ACTION_IN_PROGRESS——锁的
    # 并发拒绝路径会变成测不到的死代码。e2e 起后端时把它设成 1~2 秒，锁窗口
    # 就能被稳定命中。
    narrator_delay_seconds: float = 0.0


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一的 Settings 实例。

    加 @lru_cache 是因为 Settings() 在实例化时会去读环境变量/.env 文件，
    没必要每次调用都重新读一遍磁盘——缓存下来，全进程共享同一份配置对象。
    """
    return Settings()
