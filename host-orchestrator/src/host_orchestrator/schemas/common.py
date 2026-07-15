from host_orchestrator.schemas.base import ContractModel


class VisibleFact(ContractModel):
    fact_id: str
    text: str


class VisibleEntity(ContractModel):
    entity_id: str
    name: str
    description: str | None = None


class AvailableAction(ContractModel):
    action_id: str
    label: str
    target_ids: tuple[str, ...] = ()
