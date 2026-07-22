"""Member-A deterministic projection over a GameState-free read snapshot."""

from collaboration_framework.contracts import (
    ActionResult,
    CheckpointOption,
    ContractError,
    PlayerInput,
    PlayerView,
    VisibleEntity,
)
from collaboration_framework.ports import PlayerViewSource


class PlayerViewProjector:
    def __init__(self, source: PlayerViewSource) -> None:
        self._source = source

    async def project(self, player_input: PlayerInput) -> PlayerView:
        return await self._read(player_input)

    async def refresh(
        self,
        player_input: PlayerInput,
        action_result: ActionResult,
    ) -> PlayerView:
        view = await self._read(player_input)
        if view.revision != action_result.view_revision:
            raise ContractError("动作后 PlayerView revision 与 ActionResult 不一致")
        return view

    async def _read(self, player_input: PlayerInput) -> PlayerView:
        snapshot = await self._source.read(player_input)
        if snapshot.room_id != player_input.room_id:
            raise ContractError("ProjectionSnapshot 与 PlayerInput 房间不一致")
        return PlayerView(
            room_id=player_input.room_id,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            scene_id=snapshot.scene_id,
            phase=snapshot.phase,
            revision=snapshot.revision,
            visible_entities=tuple(
                VisibleEntity(
                    id=item.id,
                    kind=item.kind,
                    name=item.name,
                    aliases=item.aliases,
                    content=item.content,
                )
                for item in snapshot.entities
            ),
            checkpoint_options=tuple(
                CheckpointOption(
                    id=item.id,
                    target_id=item.target_id,
                    action_hint=item.action_hint,
                    skills=item.skills,
                )
                for item in snapshot.checkpoint_options
            ),
        )
