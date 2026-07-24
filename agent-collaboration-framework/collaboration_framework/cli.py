"""Offline developer CLI for the unified Fake WebSocket turn flow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from collaboration_framework.bootstrap import build_fake_application
from collaboration_framework.contracts import (
    ContractError,
    ContractModel,
    ModuleContent,
    PlayerInput,
)
from collaboration_framework.engine import GameState

ModelT = TypeVar("ModelT", bound=ContractModel)


def _load_model(path: str, model_type: type[ModelT]) -> ModelT:
    payload = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return model_type.model_validate_json(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one offline unified Agent turn")
    parser.add_argument("--module", required=True, help="ModuleContent JSON")
    parser.add_argument("--state", required=True, help="Fake-engine GameState JSON")
    parser.add_argument("--input", required=True, help="PlayerInput JSON, or - for stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        module = _load_model(args.module, ModuleContent)
        state = _load_model(args.state, GameState)
        player_input = _load_model(args.input, PlayerInput)
        app = build_fake_application(module, state)
        output = asyncio.run(app.websocket_gateway.handle(player_input))
    except (ContractError, OSError, ValidationError) as exc:
        sys.stdout.write(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2)
            + "\n"
        )
        return 1

    sys.stdout.write(output.model_dump_json(by_alias=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
