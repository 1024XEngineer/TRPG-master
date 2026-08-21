"""Storage-backed command and read service exposed to the host ports."""

from __future__ import annotations

from collaboration_framework.contracts import (
    ActorBindingError,
    KeeperCapabilityView,
    PlayerViewScope,
    ProjectionSnapshot,
)

from .models import EngineRuntimeSnapshot
from .ports import EngineStore
from .projection_v3 import keeper_capabilities_v3, project_v3


class RuleEngineService:
    """Stateless-over-rooms read façade for the player view (#226: read-only).

    The authoritative write path used to sit here as `execute`, driving the
    Checkpoint kernel. Writes now belong to the adjudication engine and the
    ActionPlan runtime; this class only projects.
    """

    def __init__(self, store: EngineStore) -> None:
        self._store = store

    async def read(self, scope: PlayerViewScope) -> ProjectionSnapshot:
        async with self._store.transaction(scope.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )
            return self._project(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )

    @staticmethod
    def _validate_identity(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> None:
        actor = runtime.game_state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            raise ActorBindingError("player_id/actor_id 未绑定到当前房间")

    @staticmethod
    def _project(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> ProjectionSnapshot:
        return project_v3(runtime, player_id=player_id, actor_id=actor_id)

    async def read_keeper_capabilities(
        self,
        scope: PlayerViewScope,
    ) -> KeeperCapabilityView:
        """Project the controlled Keeper-side capability list for one Agent run.

        Same runtime snapshot and revision as :meth:`read`, so an adjudication
        written against this list is refused on submit once the world moves.
        This never reaches the client or the Narrator — see
        :mod:`collaboration_framework.contracts.keeper_view`.
        """

        async with self._store.transaction(scope.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=scope.player_id,
                actor_id=scope.actor_id,
            )
            return self._project_keeper_capabilities(runtime, actor_id=scope.actor_id)

    @staticmethod
    def _project_keeper_capabilities(
        runtime: EngineRuntimeSnapshot,
        *,
        actor_id: str,
    ) -> KeeperCapabilityView:
        return keeper_capabilities_v3(runtime, actor_id=actor_id)
