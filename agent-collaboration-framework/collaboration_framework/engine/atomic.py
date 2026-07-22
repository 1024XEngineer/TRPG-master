"""Functional fake for B's deterministic ActionExecutor and read projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    AllowOperationSpec,
    CheckpointSpec,
    ConditionSpec,
    ContractError,
    DefaultCheck,
    EntitySpec,
    Intent,
    MatchedTarget,
    ModifyOperationSpec,
    ModuleCheck,
    ModuleContent,
    ProjectionCheckpointOption,
    ProjectionEntity,
    ProjectionSnapshot,
    RuleSpec,
    VisibleFact,
)

from .models import (
    EngineExecutionResult,
    GameState,
    StateChange,
    StateModifiedEvent,
    StateModifiedPayload,
)


class _RuleKernel:
    """In-process demo kernel; the host never calls its internal phases."""

    def execute(
        self,
        *,
        request: ActionRequest,
        module_content: ModuleContent,
        game_state: GameState,
    ) -> tuple[EngineExecutionResult, GameState]:
        state = game_state.model_dump(mode="python", by_alias=True)
        self._validate_execution_context(request, state)
        intent = request.intent

        if intent.kind == "unknown" or not isinstance(intent.target, MatchedTarget):
            return self._finalize(
                request=request,
                resolution="unrecognized",
                outcome="not_applicable",
                confirmed_facts=(),
                visible=("没有找到与这个说法对应的当前场景目标。",),
                constraints=("不得编造目标或状态变化",),
                state=state,
                events=(),
            )

        scene = self._scene(module_content, str(state["scene_id"]))
        target_id = intent.target.id
        if target_id not in scene.entity_ids:
            return self._finalize(
                request=request,
                resolution="blocked",
                outcome="not_applicable",
                confirmed_facts=(),
                visible=("这个目标不在当前场景中。",),
                constraints=("不得声称动作已经执行",),
                state=state,
                events=(),
            )

        entity = self._entity(module_content, target_id)
        verb = intent.verb
        events: list[StateModifiedEvent] = []
        facts: list[str] = []
        visible: list[str] = []
        constraints: list[str] = []

        allowing_rule = self._allowing_rule(entity, verb, state)
        if verb in entity.refuse_ops and allowing_rule is None:
            return self._finalize(
                request=request,
                resolution="blocked",
                outcome="not_applicable",
                confirmed_facts=(f"{target_id}.{verb} 被规则拒绝",),
                visible=(entity.blocked_text or "这个行动被规则阻止了。",),
                constraints=("不得声称被拒绝的状态变化已经发生",),
                state=state,
                events=(),
            )

        fact_source: str | None = None
        if isinstance(intent.check, ModuleCheck):
            checkpoint = self._validated_checkpoint(
                module_content=module_content,
                checkpoint_id=intent.check.checkpoint_id,
                scene_id=str(state["scene_id"]),
                target_id=target_id,
                proposed_skills=intent.check.proposed_skills,
            )
            outcome_name = checkpoint.mvp_check_result
            checkpoint_outcome = getattr(checkpoint.outcomes, outcome_name)
            for operation in checkpoint_outcome.ops:
                self._apply_operation(
                    operation,
                    state,
                    events,
                    room_id=request.room_id,
                    actor_id=request.actor_id,
                    client_action_id=request.request_id,
                    cause=f"checkpoint:{checkpoint.id}",
                )
            facts.extend(checkpoint_outcome.facts)
            visible.extend(checkpoint_outcome.player_visible_information)
            constraints.extend(checkpoint_outcome.narration_constraints)
            resolution = "checkpoint"
            outcome = "success" if outcome_name == "success" else "failure"
            fact_source = f"checkpoint:{checkpoint.id}:{outcome_name}"
        elif isinstance(intent.check, DefaultCheck):
            return self._finalize(
                request=request,
                resolution="unrecognized",
                outcome="not_applicable",
                confirmed_facts=(),
                visible=("当前世界尚未提供可执行的默认检定。",),
                constraints=("不得把缺少定义的默认检定叙述为成功",),
                state=state,
                events=(),
            )
        else:
            if allowing_rule:
                for operation in allowing_rule.then:
                    if not isinstance(operation, AllowOperationSpec):
                        self._apply_operation(
                            operation,
                            state,
                            events,
                            room_id=request.room_id,
                            actor_id=request.actor_id,
                            client_action_id=request.request_id,
                            cause=f"rule:{allowing_rule.id}",
                        )
                facts.extend(allowing_rule.facts)
                visible.extend(allowing_rule.player_visible_information)
                outcome = "success"
            else:
                facts.append(f"{request.actor_id} 对 {target_id} 执行 {verb}")
                visible.append(self._direct_visible_text(entity, verb))
                outcome = "not_applicable"
            resolution = "direct"

        self._apply_win_conditions(
            module_content,
            state,
            events,
            room_id=request.room_id,
            actor_id=request.actor_id,
            client_action_id=request.request_id,
            facts=facts,
            visible=visible,
        )
        return self._finalize(
            request=request,
            resolution=resolution,
            outcome=outcome,
            confirmed_facts=tuple(facts),
            visible=tuple(visible),
            constraints=tuple(constraints),
            state=state,
            events=tuple(events),
            fact_source=fact_source,
        )

    @staticmethod
    def _validate_execution_context(
        request: ActionRequest,
        state: dict[str, Any],
    ) -> None:
        if state.get("room_id") != request.room_id:
            raise ContractError("可信 room_id 与 GameState 不一致")
        actor = state.get("actors", {}).get(request.actor_id)
        if not actor or actor.get("player_id") != request.player_id:
            raise ContractError("可信 player_id/actor_id 未绑定到当前 GameState")

    @staticmethod
    def _scene(module_content: ModuleContent, scene_id: str):
        for scene in module_content.scenes:
            if scene.id == scene_id:
                return scene
        raise ContractError(f"当前 Scene 不存在: {scene_id}")

    @staticmethod
    def _entity(module_content: ModuleContent, entity_id: str) -> EntitySpec:
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
        target_id: str,
        proposed_skills: tuple[str, ...],
    ) -> CheckpointSpec:
        for checkpoint in module_content.checkpoints:
            if checkpoint.id != checkpoint_id:
                continue
            if checkpoint.scene_id != scene_id or checkpoint.target_id != target_id:
                raise ContractError("Intent Checkpoint 与当前 Scene/target 不一致")
            if not set(proposed_skills).issubset(checkpoint.skills):
                raise ContractError("Intent proposed_skills 不属于 Checkpoint")
            # The host Agent owns semantic matching. B validates identity, scene,
            # target and skill candidates instead of re-matching free-language verbs.
            return checkpoint
        raise ContractError(f"Intent checkpoint 不存在: {checkpoint_id}")

    def _allowing_rule(
        self,
        entity: EntitySpec,
        verb: str,
        state: dict[str, Any],
    ) -> RuleSpec | None:
        rules = sorted(entity.rules, key=lambda item: -item.priority)
        for rule in rules:
            allows_action = any(
                isinstance(operation, AllowOperationSpec)
                and operation.action == verb
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

    def _condition_matches(
        self,
        condition: ConditionSpec,
        state: dict[str, Any],
    ) -> bool:
        return self._read_path(state, condition.path) == condition.equals

    def _apply_operation(
        self,
        operation: ModifyOperationSpec,
        state: dict[str, Any],
        events: list[StateModifiedEvent],
        *,
        room_id: str,
        actor_id: str,
        client_action_id: str,
        cause: str,
    ) -> None:
        if not isinstance(operation, ModifyOperationSpec):
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
            cause = f"win_condition:{condition.id}"
            before_ending = state.get("ending_id")
            state["ending_id"] = condition.id
            self._append_event(
                state,
                events,
                room_id=room_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                path="ending_id",
                before=before_ending,
                after=condition.id,
                cause=cause,
            )
            before_phase = state.get("phase")
            state["phase"] = "ended"
            self._append_event(
                state,
                events,
                room_id=room_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                path="phase",
                before=before_phase,
                after="ended",
                cause=cause,
            )
            facts.append(condition.fact or f"触发结局 {condition.id}")
            visible.append(condition.player_visible_information or "故事进入结局。")
            return

    @staticmethod
    def _direct_visible_text(entity: EntitySpec, verb: str) -> str:
        return entity.direct_responses.get(
            verb,
            entity.content or "行动完成，但没有新的可见变化。",
        )

    @staticmethod
    def _finalize(
        *,
        request: ActionRequest,
        resolution: str,
        outcome: str,
        confirmed_facts: tuple[str, ...],
        visible: tuple[str, ...],
        constraints: tuple[str, ...],
        state: dict[str, Any],
        events: tuple[StateModifiedEvent, ...],
        fact_source: str | None = None,
    ) -> tuple[EngineExecutionResult, GameState]:
        validated_state = GameState.model_validate(state)
        source = fact_source or f"action:{request.request_id}:{resolution}"
        visible_facts = tuple(
            VisibleFact(id=f"{source}:result:{index}", text=text)
            for index, text in enumerate(visible, start=1)
        )
        action_result = ActionResult(
            request_id=request.request_id,
            action_id=f"action:{request.request_id}",
            resolution=resolution,
            outcome=outcome,
            visible_facts=visible_facts,
            narration_constraints=constraints,
            view_revision=str(validated_state.event_sequence),
            event_refs=tuple(event.event_id for event in events),
        )
        execution = EngineExecutionResult(
            action_result=action_result,
            confirmed_facts=confirmed_facts,
            state_changes=tuple(
                StateChange(
                    path=event.payload.path,
                    from_value=event.payload.from_value,
                    to=event.payload.to,
                    cause=event.cause,
                )
                for event in events
            ),
            events=events,
            state_version=validated_state.event_sequence,
        )
        return execution, validated_state


@dataclass(frozen=True)
class _CompletedAction:
    request: ActionRequest
    execution: EngineExecutionResult


class FakeAtomicEngine:
    """B-owned functional fake implementing ActionExecutor and PlayerViewSource."""

    def __init__(self, module_content: ModuleContent, initial_state: GameState) -> None:
        self._module = module_content.model_copy(deep=True)
        self._state = initial_state.model_copy(deep=True)
        self._kernel = _RuleKernel()
        self._completed_actions: dict[str, _CompletedAction] = {}

    async def read(self, player_input) -> ProjectionSnapshot:
        self._validate_identity(
            player_input.room_id,
            player_input.player_id,
            player_input.actor_id,
        )
        scene = next(
            (item for item in self._module.scenes if item.id == self._state.scene_id),
            None,
        )
        if scene is None:
            raise ContractError(f"当前 Scene 不存在: {self._state.scene_id}")
        entities = {item.id: item for item in self._module.entities}
        return ProjectionSnapshot(
            room_id=self._state.room_id,
            scene_id=scene.id,
            phase=self._state.phase,
            revision=str(self._state.event_sequence),
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
                for checkpoint in self._module.checkpoints
                if checkpoint.id in scene.checkpoint_ids
            ),
        )

    async def execute(self, request: ActionRequest) -> ActionResult:
        """Represent the production engine's one atomic command boundary."""

        self._validate_identity(request.room_id, request.player_id, request.actor_id)
        cached = self._completed_actions.get(request.request_id)
        if cached is not None:
            return self._replay_result(request, cached)
        if request.source_view_revision != str(self._state.event_sequence):
            raise ContractError("ActionRequest 基于过期 PlayerView")

        execution, new_state = self._kernel.execute(
            request=request,
            module_content=self._module,
            game_state=self._state.model_copy(deep=True),
        )
        self._state = new_state
        self._completed_actions[request.request_id] = _CompletedAction(
            request=request.model_copy(deep=True),
            execution=execution.model_copy(deep=True),
        )
        return execution.action_result.model_copy(deep=True)

    def snapshot(self) -> GameState:
        """B-owned test inspection; host code must not call this method."""

        return self._state.model_copy(deep=True)

    def execution_for(self, request_id: str) -> EngineExecutionResult:
        """B/integration-test inspection; not part of the ActionExecutor port."""

        try:
            return self._completed_actions[request_id].execution.model_copy(deep=True)
        except KeyError as error:
            raise ContractError(f"动作尚未执行: {request_id}") from error

    def _replay_result(
        self,
        request: ActionRequest,
        completed: _CompletedAction,
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

        # The semantic result and Event refs remain those of the original
        # execution. view_revision is synchronization metadata for A's mandatory
        # post-action refresh, so a later retry must point at the current view.
        return completed.execution.action_result.model_copy(
            update={"view_revision": str(self._state.event_sequence)},
            deep=True,
        )

    def _validate_identity(self, room_id: str, player_id: str, actor_id: str) -> None:
        if room_id != self._state.room_id:
            raise ContractError("room_id 与引擎房间不一致")
        actor = self._state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            raise ContractError("player_id/actor_id 未绑定到当前房间")
