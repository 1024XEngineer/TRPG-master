from host_orchestrator.schemas.base import ContractModel, SchemaVersion


class NarrationOutput(ContractModel):
    schema_version: SchemaVersion = "1"
    text: str
    referenced_fact_ids: tuple[str, ...] = ()
