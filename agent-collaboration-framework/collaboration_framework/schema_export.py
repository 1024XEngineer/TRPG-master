"""Generate JSON Schema for active contracts and planner context."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanProgressEvent,
    ActionRequest,
    ActionResult,
    AdjudicationExecution,
    AdjudicationStatusView,
    CancelActionPlanRequest,
    CheckDecisionRequest,
    GetAdjudicationStatusRequest,
    KeeperCapabilityView,
    ModuleContentV3,
    PlayerInput,
    PlayerView,
    PostRollDecisionRequest,
    ProjectionSnapshot,
    SubmitAdjudicationRequest,
    ValidationFeedback,
    ValidationResult,
)
from collaboration_framework.host.schemas import (
    HostAgentContext,
    NarrationOutput,
    OpeningNarrationContext,
    RecentTurnContext,
    TurnPlanningContext,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "module-content-v3.schema.json": ModuleContentV3,
    "player-input.schema.json": PlayerInput,
    "projection-snapshot.schema.json": ProjectionSnapshot,
    "player-view.schema.json": PlayerView,
    "keeper-capability-view.schema.json": KeeperCapabilityView,
    "action-request.schema.json": ActionRequest,
    "action-result.schema.json": ActionResult,
    "action-adjudication.schema.json": ActionAdjudication,
    "action-plan.schema.json": ActionPlan,
    "action-plan-policy.schema.json": ActionPlanPolicy,
    "action-plan-progress.schema.json": ActionPlanProgressEvent,
    "submit-adjudication-request.schema.json": SubmitAdjudicationRequest,
    "check-decision-request.schema.json": CheckDecisionRequest,
    "post-roll-decision-request.schema.json": PostRollDecisionRequest,
    "adjudication-execution.schema.json": AdjudicationExecution,
    "adjudication-status.schema.json": AdjudicationStatusView,
    "cancel-action-plan-request.schema.json": CancelActionPlanRequest,
    "get-adjudication-status-request.schema.json": GetAdjudicationStatusRequest,
    "validation-result.schema.json": ValidationResult,
    "validation-feedback.schema.json": ValidationFeedback,
    "narration-output.schema.json": NarrationOutput,
    "opening-narration-context.schema.json": OpeningNarrationContext,
    "host-agent-context.schema.json": HostAgentContext,
    "turn-planning-context.schema.json": TurnPlanningContext,
    "recent-turn-context.schema.json": RecentTurnContext,
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
