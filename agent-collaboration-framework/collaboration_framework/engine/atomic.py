"""Deterministic execution over validated Pydantic contracts."""

from __future__ import annotations

from typing import Any

from ..contracts import (
    ActionResult,
    AllowOperation,
    CheckpointOption,
    Checkpoint,
    Condition,
    ContractError,
    DefaultCheck,
    Entity,
    EngineRequest,
    GameState,
    Intent,
    MatchedTarget,
    ModifyOperation,
    ModuleCheck,
    ModuleContent,
    PlayerInput,
    Rule,
    StateChange,
    StateModifiedEvent,
    StateModifiedPayload,
    TurnContext,
    VisibleEntity,
)

# TODO(atomic-engine): 实现 ContextAssembler 和 AtomicActionEngine 的正式适配器。
# execute_action() 内必须一次完成权限/幂等/规则检定、append Event、更新物化视图和提交；
# 事务绝不能拆成多个 LangGraph 节点，图也不得成为游戏状态的第二权威。


class _RuleKernel:
    """In-process demo kernel; LangGraph never calls its internal phases."""

    def execute(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        client_action_id: str,
        intent: Intent,
        module_content: ModuleContent,
        game_state: GameState,
    ) -> tuple[ActionResult, GameState, list[StateModifiedEvent]]:
        state = game_state.model_dump(mode="python", by_alias=True)
        self._validate_execution_context(room_id, player_id, actor_id, state)

        if intent.kind == "unknown" or not isinstance(intent.target, MatchedTarget):
            return self._finalize(
                self._result(
                    success=False,
                    resolution="unrecognized",
                    visible=["没有找到与这个说法对应的当前场景目标。"],
                    constraints=["不得编造目标或状态变化"],
                ),
                state,
                [],
            )

        scene = self._scene(module_content, str(state["scene_id"]))
        target_id = intent.target.id
        if target_id not in scene.entity_ids:
            return self._finalize(
                self._result(
                    success=False,
                    resolution="blocked",
                    visible=["这个目标不在当前场景中。"],
                    constraints=["不得声称动作已经执行"],
                ),
                state,
                [],
            )

        entity = self._entity(module_content, target_id)
        action = intent.action
        events: list[StateModifiedEvent] = []
        facts: list[str] = []
        visible: list[str] = []
        constraints: list[str] = []

        allowing_rule = self._allowing_rule(entity, action, state)
        if action in entity.refuse_ops and allowing_rule is None:
            return self._finalize(
                self._result(
                    success=False,
                    resolution="blocked",
                    facts=[f"{target_id}.{action} 被规则拒绝"],
                    visible=[entity.blocked_text or "这个行动被规则阻止了。"],
                    constraints=["不得声称被拒绝的状态变化已经发生"],
                ),
                state,
                [],
            )

        if isinstance(intent.check, ModuleCheck):
            checkpoint = self._validated_checkpoint(
                module_content=module_content,
                checkpoint_id=intent.check.checkpoint_id,
                scene_id=str(state["scene_id"]),
                action=action,
                target_id=target_id,
            )
            # MVP only: member B replaces this fixture switch with an authoritative roll.
            outcome_name = checkpoint.mvp_check_result
            outcome = getattr(checkpoint.outcomes, outcome_name)
            for operation in outcome.ops:
                self._apply_operation(
                    operation,
                    state,
                    events,
                    room_id=room_id,
                    actor_id=actor_id,
                    client_action_id=client_action_id,
                    cause=f"checkpoint:{checkpoint.id}",
                )
            facts.extend(outcome.facts)
            visible.extend(outcome.player_visible_information)
            constraints.extend(outcome.narration_constraints)
            success = outcome_name == "success"
            resolution = "checkpoint"
        elif isinstance(intent.check, DefaultCheck):
            return self._finalize(
                self._result(
                    success=False,
                    resolution="unrecognized",
                    visible=["当前世界尚未提供可执行的默认检定。"],
                    constraints=["不得把缺少定义的默认检定叙述为成功"],
                ),
                state,
                [],
            )
        else:
            if allowing_rule:
                for operation in allowing_rule.then:
                    if not isinstance(operation, AllowOperation):
                        self._apply_operation(
                            operation,
                            state,
                            events,
                            room_id=room_id,
                            actor_id=actor_id,
                            client_action_id=client_action_id,
                            cause=f"rule:{allowing_rule.id}",
                        )
                facts.extend(allowing_rule.facts)
                visible.extend(allowing_rule.player_visible_information)
            else:
                facts.append(f"{actor_id} 对 {target_id} 执行 {action}")
                visible.append(self._direct_visible_text(entity, action))
            success = True
            resolution = "direct"

        self._apply_win_conditions(
            module_content,
            state,
            events,
            room_id=room_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            facts=facts,
            visible=visible,
        )
        result = self._result(
            success=success,
            resolution=resolution,
            facts=facts,
            visible=visible,
            state_changes=[self._event_to_change(event) for event in events],
            constraints=constraints,
        )
        return self._finalize(result, state, events)

    @staticmethod
    def _validate_execution_context(
        room_id: str,
        player_id: str,
        actor_id: str,
        state: dict[str, Any],
    ) -> None:
        if state.get("room_id") != room_id:
            raise ContractError("可信 room_id 与 GameState 不一致")
        actor = state.get("actors", {}).get(actor_id)
        if not actor or actor.get("player_id") != player_id:
            raise ContractError("可信 player_id/actor_id 未绑定到当前 GameState")

    @staticmethod
    def _scene(module_content: ModuleContent, scene_id: str):
        for scene in module_content.scenes:
            if scene.id == scene_id:
                return scene
        raise ContractError(f"当前 Scene 不存在: {scene_id}")

    @staticmethod
    def _entity(module_content: ModuleContent, entity_id: str) -> Entity:
        for entity in module_content.entities:
            if entity.id == entity_id:
                return entity
        raise ContractError(f"Intent target 不存在: {entity_id}")

    @staticmethod
    def _validated_checkpoint(
        *,
        module_content: ModuleContent,
        checkpoint_id: str,
        scene_id: str,
        action: str,
        target_id: str,
    ) -> Checkpoint:
        for checkpoint in module_content.checkpoints:
            if checkpoint.id != checkpoint_id:
                continue
            expected = (scene_id, action, target_id)
            actual = (checkpoint.scene_id, checkpoint.action, checkpoint.target_id)
            if actual != expected:
                raise ContractError("Intent 的 Checkpoint 与当前 Scene/action/target 不一致")
            return checkpoint
        raise ContractError(f"Intent checkpoint 不存在: {checkpoint_id}")

    def _allowing_rule(
        self,
        entity: Entity,
        action: str,
        state: dict[str, Any],
    ) -> Rule | None:
        rules = sorted(entity.rules, key=lambda item: -item.priority)
        for rule in rules:
            allows_action = any(
                isinstance(operation, AllowOperation) and operation.action == action
                for operation in rule.then
            )
            if allows_action and self._condition_matches(rule.when, state):
                return rule
        return None

    @staticmethod
    def _read_path(state: dict[str, Any], path: str) -> Any:
        cursor: Any = state
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                raise ContractError(f"状态路径不存在: {path}")
            cursor = cursor[part]
        return cursor

    def _condition_matches(self, condition: Condition, state: dict[str, Any]) -> bool:
        return self._read_path(state, condition.path) == condition.equals

    def _apply_operation(
        self,
        operation: AllowOperation | ModifyOperation,
        state: dict[str, Any],
        events: list[StateModifiedEvent],
        *,
        room_id: str,
        actor_id: str,
        client_action_id: str,
        cause: str,
    ) -> None:
        if not isinstance(operation, ModifyOperation):
            raise ContractError(f"演示规则内核不支持 Op: {operation}")
        path = operation.path
        parts = path.split(".")
        if len(parts) < 2 or parts[0] not in {"entities", "actors"}:
            raise ContractError(f"状态路径不在 MVP 白名单中: {path}")
        parent: Any = state
        for part in parts[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise ContractError(f"状态路径不存在: {path}")
            parent = parent[part]
        leaf = parts[-1]
        if not isinstance(parent, dict) or leaf not in parent:
            raise ContractError(f"状态路径不存在: {path}")
        before = parent[leaf]
        after = operation.set
        if before == after:
            return
        parent[leaf] = after
        self._append_event(
            state,
            events,
            room_id=room_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            path=path,
            before=before,
            after=after,
            cause=cause,
        )

    @staticmethod
    def _append_event(
        state: dict[str, Any],
        events: list[StateModifiedEvent],
        *,
        room_id: str,
        actor_id: str,
        client_action_id: str,
        path: str,
        before: Any,
        after: Any,
        cause: str,
    ) -> None:
        sequence = int(state.get("event_sequence", 0)) + 1
        state["event_sequence"] = sequence
        events.append(
            StateModifiedEvent(
                event_id=f"evt_{sequence:04d}",
                sequence=sequence,
                room_id=room_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                cause=cause,
                payload=StateModifiedPayload(
                    path=path,
                    from_value=before,
                    to=after,
                ),
            )
        )

    def _apply_win_conditions(
        self,
        module_content: ModuleContent,
        state: dict[str, Any],
        events: list[StateModifiedEvent],
        *,
        room_id: str,
        actor_id: str,
        client_action_id: str,
        facts: list[str],
        visible: list[str],
    ) -> None:
        if state.get("phase") == "ended":
            return
        for condition in module_content.win_conditions:
            if not self._condition_matches(condition.when, state):
                continue
            before = state.get("phase")
            state["phase"] = "ended"
            state["ending_id"] = condition.id
            self._append_event(
                state,
                events,
                room_id=room_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                path="phase",
                before=before,
                after="ended",
                cause=f"win_condition:{condition.id}",
            )
            facts.append(condition.fact or f"触发结局 {condition.id}")
            visible.append(condition.player_visible_information or "故事进入结局。")
            return

    @staticmethod
    def _direct_visible_text(entity: Entity, action: str) -> str:
        return entity.direct_responses.get(
            action,
            entity.content or "行动完成，但没有新的可见变化。",
        )

    @staticmethod
    def _event_to_change(event: StateModifiedEvent) -> StateChange:
        return StateChange(
            path=event.payload.path,
            from_value=event.payload.from_value,
            to=event.payload.to,
            cause=event.cause,
        )

    @staticmethod
    def _result(
        *,
        success: bool,
        resolution: str,
        facts: list[str] | None = None,
        visible: list[str] | None = None,
        state_changes: list[StateChange] | None = None,
        constraints: list[str] | None = None,
    ) -> ActionResult:
        return ActionResult(
            success=success,
            resolution=resolution,
            confirmed_facts=facts or [],
            player_visible_information=visible or [],
            state_changes=state_changes or [],
            narration_constraints=constraints or [],
        )

    @staticmethod
    def _finalize(
        result: ActionResult,
        state: dict[str, Any],
        events: list[StateModifiedEvent],
    ) -> tuple[ActionResult, GameState, list[StateModifiedEvent]]:
        validated_state = GameState.model_validate(state)
        return (
            result.model_copy(deep=True),
            validated_state,
            [event.model_copy(deep=True) for event in events],
        )


class FakeAtomicEngine:
    """No-database adapter implementing context and atomic-engine ports.

    GameState lives inside this fake to model the production ownership boundary.
    TurnState never receives a copy of the authoritative state.
    """

    def __init__(self, module_content: ModuleContent, initial_state: GameState) -> None:
        self._module = module_content.model_copy(deep=True)
        self._state = initial_state.model_copy(deep=True)
        self._kernel = _RuleKernel()
        self._completed_actions: dict[str, ActionResult] = {}

    async def assemble_context(self, player_input: PlayerInput) -> TurnContext:
        self._validate_identity(player_input)
        scene = next(
            (item for item in self._module.scenes if item.id == self._state.scene_id),
            None,
        )
        if scene is None:
            raise ContractError(f"当前 Scene 不存在: {self._state.scene_id}")
        entities = {item.id: item for item in self._module.entities}
        return TurnContext(
            scene_id=scene.id,
            phase=self._state.phase,
            visible_entities=[
                VisibleEntity(
                    id=entities[entity_id].id,
                    kind=entities[entity_id].kind,
                    name=entities[entity_id].name,
                    aliases=entities[entity_id].aliases,
                    content=entities[entity_id].content,
                )
                for entity_id in scene.entity_ids
            ],
            checkpoint_options=[
                CheckpointOption(
                    id=checkpoint.id,
                    action=checkpoint.action,
                    target_id=checkpoint.target_id,
                    skills=checkpoint.skills,
                )
                for checkpoint in self._module.checkpoints
                if checkpoint.id in scene.checkpoint_ids
            ],
        )

    async def execute_action(self, request: EngineRequest) -> ActionResult:
        """Represent the production engine's single atomic transaction call."""

        self._validate_identity(request.player_input)
        client_action_id = request.player_input.client_action_id
        cached = self._completed_actions.get(client_action_id)
        if cached is not None:
            return cached.model_copy(deep=True)

        # The kernel works on a detached snapshot. Publish the new state only after
        # the complete call and output validation succeed.
        result, new_state, events = self._kernel.execute(
            room_id=request.player_input.room_id,
            player_id=request.player_input.player_id,
            actor_id=request.player_input.actor_id,
            client_action_id=request.player_input.client_action_id,
            intent=request.intent,
            module_content=self._module,
            game_state=self._state.model_copy(deep=True),
        )
        payload = result.model_dump(mode="python", by_alias=True)
        payload.update(events=events, state_version=new_state.event_sequence)
        committed = ActionResult.model_validate(payload)
        self._state = new_state
        self._completed_actions[client_action_id] = committed.model_copy(deep=True)
        return committed.model_copy(deep=True)

    def snapshot(self) -> GameState:
        """Test/demo inspection only; production callers read a materialized view."""

        return self._state.model_copy(deep=True)

    def _validate_identity(self, player_input: PlayerInput) -> None:
        if player_input.room_id != self._state.room_id:
            raise ContractError("room_id 与引擎房间不一致")
        actor = self._state.actors.get(player_input.actor_id)
        if actor is None or actor.player_id != player_input.player_id:
            raise ContractError("player_id/actor_id 未绑定到当前房间")
