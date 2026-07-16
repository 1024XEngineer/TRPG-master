"""Generate JSON Schema only for stable cross-boundary and player DTOs."""

from __future__ import annotations

import json
from pathlib import Path

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractModel,
    Intent,
    ModuleContent,
    PlayerInput,
    PlayerView,
    ProjectionSnapshot,
)
from collaboration_framework.host.schemas import NarrationOutput, WebSocketOutput


SCHEMA_MODELS: dict[str, type[ContractModel]] = {
    "module-content.schema.json": ModuleContent,
    "player-input.schema.json": PlayerInput,
    "projection-snapshot.schema.json": ProjectionSnapshot,
    "player-view.schema.json": PlayerView,
    "intent.schema.json": Intent,
    "action-request.schema.json": ActionRequest,
    "action-result.schema.json": ActionResult,
    "narration-output.schema.json": NarrationOutput,
    "websocket-output.schema.json": WebSocketOutput,
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
    expected = rendered_schemas()
    for path in directory.glob("*.schema.json"):
        if path.name not in expected:
            path.unlink()
    for filename, content in expected.items():
        (directory / filename).write_text(content, encoding="utf-8")


def main() -> int:
    export_schemas(Path(__file__).resolve().parents[1] / "schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
