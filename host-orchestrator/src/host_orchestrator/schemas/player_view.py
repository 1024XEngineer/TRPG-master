from host_orchestrator.schemas.base import ContractModel, SchemaVersion
from host_orchestrator.schemas.common import AvailableAction, VisibleEntity, VisibleFact


class PlayerView(ContractModel):
    schema_version: SchemaVersion = "1"
    room_id: str
    player_id: str
    actor_id: str
    scene_id: str
    revision: str
    scene_summary: str
    visible_facts: tuple[VisibleFact, ...] = ()
    visible_entities: tuple[VisibleEntity, ...] = ()
    available_actions: tuple[AvailableAction, ...] = ()
