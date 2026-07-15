from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite+aiosqlite:///./app.db"
    enable_docs: bool = True
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:9877"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
