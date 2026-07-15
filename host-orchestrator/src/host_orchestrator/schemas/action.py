from typing import Literal, TypeAlias

from host_orchestrator.schemas.base import ContractModel, SchemaVersion
from host_orchestrator.schemas.common import VisibleFact
from host_orchestrator.schemas.intent import Intent

ActionStatus: TypeAlias = Literal["resolved", "rejected", "unrecognized"]


class ActionRequest(ContractModel):
    schema_version: SchemaVersion = "1"
    request_id: str
    room_id: str
    player_id: str
    actor_id: str
    intent: Intent


class ActionResult(ContractModel):
    schema_version: SchemaVersion = "1"
    action_id: str
    status: ActionStatus
    visible_facts: tuple[VisibleFact, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    view_revision: str | None = None
