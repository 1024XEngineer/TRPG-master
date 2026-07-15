from host_orchestrator.schemas.action import ActionResult
from host_orchestrator.schemas.base import ContractModel, SchemaVersion
from host_orchestrator.schemas.intent import Intent
from host_orchestrator.schemas.player_input import PlayerInput
from host_orchestrator.schemas.player_view import PlayerView


class IntentContext(ContractModel):
    schema_version: SchemaVersion = "1"
    player_input: PlayerInput
    player_view: PlayerView


class NarrationContext(ContractModel):
    schema_version: SchemaVersion = "1"
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult
    player_view: PlayerView
