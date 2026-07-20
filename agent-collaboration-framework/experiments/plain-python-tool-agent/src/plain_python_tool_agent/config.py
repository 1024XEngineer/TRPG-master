"""Qwen configuration with a tiny dependency-free .env reader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
API_KEY_NAMES = ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "qwen_api_key")


def _load_nearest_dotenv() -> None:
    roots = [Path.cwd(), *Path(__file__).resolve().parents]
    for dotenv_path in dict.fromkeys(root / ".env" for root in roots):
        if not dotenv_path.is_file():
            continue
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip("\"'")
            if name:
                os.environ.setdefault(name, value)
        return


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls) -> "Settings":
        _load_nearest_dotenv()
        api_key = next(
            (os.getenv(name) for name in API_KEY_NAMES if os.getenv(name)), None
        )
        if not api_key:
            names = ", ".join(API_KEY_NAMES)
            raise RuntimeError(f"Missing Qwen API key. Set one of: {names}")
        return cls(
            api_key=api_key,
            base_url=os.getenv("QWEN_BASE_URL", DEFAULT_BASE_URL),
            model=os.getenv("QWEN_MODEL", DEFAULT_MODEL),
        )
