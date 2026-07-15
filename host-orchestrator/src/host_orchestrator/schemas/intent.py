from typing import Literal, TypeAlias

from host_orchestrator.schemas.base import ContractModel, SchemaVersion

IntentKind: TypeAlias = Literal["action", "dialogue", "unknown"]


class IntentTarget(ContractModel):
    entity_id: str | None = None
    raw_text: str | None = None


class Intent(ContractModel):
    schema_version: SchemaVersion = "1"
    kind: IntentKind
    verb: str
    target: IntentTarget | None = None
    content: str | None = None
    summary: str
