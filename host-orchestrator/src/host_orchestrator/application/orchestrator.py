from host_orchestrator.schemas.output import TurnOutput
from host_orchestrator.schemas.player_input import PlayerInput


class Orchestrator:
    """TODO: run the fixed MVP async workflow without business rules."""

    async def run(self, player_input: PlayerInput) -> TurnOutput:
        raise NotImplementedError("TODO: implement the fixed async workflow")
