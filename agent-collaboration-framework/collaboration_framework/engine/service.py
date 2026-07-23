"""Storage-backed command and read service exposed to the host ports."""

from __future__ import annotations

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    PlayerInput,
    ProjectionCheckpointOption,
    ProjectionEntity,
    ProjectionSnapshot,
)

from .kernel import RuleKernel
from .models import CompletedAction, EngineRuntimeSnapshot
from .ports import EngineStore


class RuleEngineService:
    """Stateless-over-rooms façade implementing both stable host ports."""

    def __init__(
        self,
        store: EngineStore,
        kernel: RuleKernel | None = None,
    ) -> None:
        self._store = store
        self._kernel = kernel or RuleKernel()

    async def read(self, player_input: PlayerInput) -> ProjectionSnapshot:
        async with self._store.transaction(player_input.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=player_input.player_id,
                actor_id=player_input.actor_id,
            )
            return self._project(runtime)

    async def execute(self, request: ActionRequest) -> ActionResult:
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=request.player_id,
                actor_id=request.actor_id,
            )

            completed = await transaction.find_completed_action(request.request_id)
            if completed is not None:
                return self._replay_result(
                    request=request,
                    completed=completed,
                    current_revision=runtime.revision,
                )
            if request.source_view_revision != runtime.revision:
                raise ContractError("ActionRequest 基于过期 PlayerView")

            execution, new_state = self._kernel.execute(
                request=request,
                module_content=runtime.module_content,
                game_state=runtime.game_state,
            )
            completed = CompletedAction(
                request=request.model_copy(deep=True),
                execution=execution.model_copy(deep=True),
            )
            await transaction.commit(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=execution.events,
                completed_action=completed,
            )
            return execution.action_result.model_copy(deep=True)

    @staticmethod
    def _validate_identity(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> None:
        actor = runtime.game_state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            raise ContractError("player_id/actor_id 未绑定到当前房间")

    @staticmethod
    def _replay_result(
        *,
        request: ActionRequest,
        completed: CompletedAction,
        current_revision: str,
    ) -> ActionResult:
        original = completed.request
        if (
            request.room_id,
            request.player_id,
            request.actor_id,
            request.intent,
        ) != (
            original.room_id,
            original.player_id,
            original.actor_id,
            original.intent,
        ):
            raise ContractError("request_id 已用于不同的动作请求")

        return completed.execution.action_result.model_copy(
            update={"view_revision": current_revision},
            deep=True,
        )

    @staticmethod
    def _project(runtime: EngineRuntimeSnapshot) -> ProjectionSnapshot:
        module = runtime.module_content
        state = runtime.game_state
        scene = next(
            (item for item in module.scenes if item.id == state.scene_id),
            None,
        )
        if scene is None:
            raise ContractError(f"当前 Scene 不存在: {state.scene_id}")
        entities = {item.id: item for item in module.entities}
        return ProjectionSnapshot(
            room_id=state.room_id,
            scene_id=scene.id,
            phase=state.phase,
            revision=runtime.revision,
            entities=tuple(
                ProjectionEntity(
                    id=entities[entity_id].id,
                    kind=entities[entity_id].kind,
                    name=entities[entity_id].name,
                    aliases=entities[entity_id].aliases,
                    content=entities[entity_id].content,
                )
                for entity_id in scene.entity_ids
            ),
            checkpoint_options=tuple(
                ProjectionCheckpointOption(
                    id=checkpoint.id,
                    target_id=checkpoint.target_id,
                    action_hint=checkpoint.action,
                    skills=checkpoint.skills,
                )
                for checkpoint in module.checkpoints
                if checkpoint.id in scene.checkpoint_ids
            ),
        )
