"""Generate JSON Schema from the framework-neutral Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import (
    ActionResult,
    ContractModel,
    EngineRequest,
    GameState,
    Intent,
    ModuleContent,
    NarrationOutput,
    PlayerInput,
    StateModifiedEvent,
    SummaryOperation,
    TurnContext,
    TurnOutput,
    TurnState,
)


SCHEMA_MODELS: dict[str, type[ContractModel]] = {
    "module-content.schema.json": ModuleContent,
    "game-state.schema.json": GameState,
    "player-input.schema.json": PlayerInput,
    "turn-context.schema.json": TurnContext,
    "intent.schema.json": Intent,
    "engine-request.schema.json": EngineRequest,
    "action-result.schema.json": ActionResult,
    "event.schema.json": StateModifiedEvent,
    "narration-output.schema.json": NarrationOutput,
    "summary-operation.schema.json": SummaryOperation,
    "turn-state.schema.json": TurnState,
    "turn-output.schema.json": TurnOutput,
}


def rendered_schemas() -> dict[str, str]:
    rendered: dict[str, str] = {}
    for filename, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema(by_alias=True, mode="validation")
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": filename,
            **schema,
        }
        rendered[filename] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    return rendered


def export_schemas(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in rendered_schemas().items():
        (directory / filename).write_text(content, encoding="utf-8")


def main() -> int:
    export_schemas(Path(__file__).resolve().parents[1] / "schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
