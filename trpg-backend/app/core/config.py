"""应用配置。

用 pydantic-settings 从环境变量 / `.env` 文件里读配置，而不是散落在代码各处的
硬编码常量或裸 `os.environ.get(...)`——好处是每个配置项都有类型、默认值和校验，
IDE 能补全，写错类型（比如 ENABLE_DOCS 传了个不是 true/false 的字符串）会在启动时
就报错，而不是运行到一半才炸。
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    cors_origins: list[str] = ["http://localhost:9877"]


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一的 Settings 实例。

    加 @lru_cache 是因为 Settings() 在实例化时会去读环境变量/.env 文件，
    没必要每次调用都重新读一遍磁盘——缓存下来，全进程共享同一份配置对象。
    """
    return Settings()
