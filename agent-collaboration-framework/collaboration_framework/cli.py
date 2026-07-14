"""CLI demo: validated JSON in, one checkpointer-free graph turn out."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError
from pydantic_ai import ModelHTTPError, UnexpectedModelBehavior

from .contracts import ContractError, ContractModel, GameState, ModuleContent, PlayerInput
from .agents import create_runtime_agent
from .engine import FakeAtomicEngine
from .settings import AgentSettings
from .workflow import GraphDependencies, run_turn_sync

ModelT = TypeVar("ModelT", bound=ContractModel)


def _load_model(path: str, model_type: type[ModelT]) -> ModelT:
    payload = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return model_type.model_validate_json(payload)


def build_parser(settings: AgentSettings | None = None) -> argparse.ArgumentParser:
    settings = settings or AgentSettings.from_env()
    parser = argparse.ArgumentParser(description="Run one stateless LangGraph turn")
    parser.add_argument("--module", required=True, help="ModuleContent JSON")
    parser.add_argument("--state", required=True, help="Fake-engine GameState JSON")
    parser.add_argument("--input", required=True, help="PlayerInput JSON, or - for stdin")
    parser.add_argument(
        "--agent-mode",
        choices=("fake", "pydantic-ai"),
        default=settings.mode,
    )
    parser.add_argument("--model", default=settings.model_name)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        module = _load_model(args.module, ModuleContent)
        state = _load_model(args.state, GameState)
        player_input = _load_model(args.input, PlayerInput)
        agent = create_runtime_agent(args.agent_mode, args.model)
        engine = FakeAtomicEngine(module, state)
        output = run_turn_sync(
            player_input,
            GraphDependencies(
                context_assembler=engine,
                interpreter=agent,
                engine=engine,
                narrator=agent,
            ),
        )
    except (
        ContractError,
        OSError,
        ValidationError,
        ModelHTTPError,
        UnexpectedModelBehavior,
    ) as exc:
        sys.stdout.write(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2)
            + "\n"
        )
        return 1

    sys.stdout.write(output.model_dump_json(by_alias=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
