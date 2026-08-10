"""Deterministic ModuleContent v3 single-intent ActionExecutor.

The service is deliberately separate from Host orchestration.  Tests and future
Agent adapters submit already-adjudicated commands; this module validates and
commits them without interpreting player language.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from pydantic import JsonValue

from collaboration_framework.contracts import (
    AcceptResultOption,
    ActionAdjudication,
    ActionEffect,
    AdvanceWorldTimeEffect,
    AdjudicationRecovery,
    AdjudicationExecution,
    AdjudicationStatusView,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    CommitTerminalEndingEffect,
    ConsumeEntityEffect,
    ContractError,
    EnsureRuntimeEntityEffect,
    EnsureRuntimeLocationEffect,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    HideInformationEffect,
    ItemAcquisition,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    MarkCoreResolvedEffect,
    LocationKnowledge,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    PendingCheckOption,
    PostRollDecisionRequest,
    PushOption,
    RevealInformationEffect,
    SetEndingAvailabilityEffect,
    SetVisibilityEffect,
    SpendResourceOption,
    SubmitAdjudicationRequest,
    TravelInterrupted,
    TravelResolved,
)
from collaboration_framework.contracts.adjudication import CheckDegree, CheckRoll

from .dice import DiceRoller, coc7_success_level, passes_difficulty
from .models import (
    AgendaSource,
    CheckRun,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineRuntimeSnapshot,
    GameState,
    PendingCheckDecision,
    WorldTimeState,
)
from .navigation import resolve_location_target
from .ports import EngineStore
from .timeline import advanced_to_next, next_point_after, time_advance_block_reason
from .rules_v3 import (
    agenda_item_for_event,
    agenda_status_for_walk,
    create_rule_agenda,
    effects_after_degree,
    matching_event_rules,
    pending_check_for,
    resolve_rule_option,
    walk_rule,
)


def _visibility_knowledge(
    location_id: str,
    *,
    scope: str,
    visible: bool,
    previous: LocationKnowledge | None,
) -> LocationKnowledge:
    return LocationKnowledge(
        location_id=location_id,
        scope="actor" if scope == "actor" else "party",
        existence="known" if visible else "unknown",
        localization="located" if visible else "unknown",
        access=(previous.access if visible and previous is not None else "unknown"),
        visited=bool(visible and previous and previous.visited),
        known_connection_ids=(
            previous.known_connection_ids if visible and previous is not None else ()
        ),
    )


class AdjudicationEngineService:
    """B-owned executor for one ActionAdjudication per call."""

    def __init__(self, store: EngineStore, *, dice: DiceRoller | None = None) -> None:
        self._store = store
        self._dice = dice or DiceRoller()

    async def get_status(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationStatusView:
        """Read the latest player-safe status without exposing Engine ORM state."""

        async with self._store.transaction(request.room_id) as transaction:
            command = await transaction.find_latest_adjudication_command_by_action(
                request.action_request_id
            )
            if command is None:
                return AdjudicationStatusView(
                    action_request_id=request.action_request_id,
                    status="not_submitted",
                )
            if command.request.room_id != request.room_id:
                raise ContractError("裁决状态与请求房间不一致")
            if command.request.player_id != request.player_id:
                raise ContractError("裁决状态不属于当前玩家")
            execution = command.execution
            return AdjudicationStatusView(
                action_request_id=request.action_request_id,
                status=execution.status,
                execution=execution,
            )

    async def find_active_action_for_player(
        self,
        *,
        room_id: str,
        player_id: str,
    ) -> str | None:
        """Return the action_request_id of this player's one open check, if any.

        Lets a reconnecting client discover a standalone single-action check it
        never persisted an ID for client-side (unlike ActionPlan-driven checks,
        which are already discoverable room-scoped via
        ActionPlanOrchestrator.active_for_room).
        """

        async with self._store.transaction(room_id) as transaction:
            return await transaction.find_active_action_for_player(player_id)

    async def recover_action(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationRecovery | None:
        """Recover the safe context needed to finish one persisted action.

        The latest command may be a skill or post-roll decision and therefore
        does not itself carry the original adjudication. For checked actions,
        the durable PendingCheckDecision remains the source of that frozen
        adjudication after the decision has resolved.
        """

        async with self._store.transaction(request.room_id) as transaction:
            command = await transaction.find_latest_adjudication_command_by_action(
                request.action_request_id
            )
            if command is None:
                return None
            if command.request.room_id != request.room_id:
                raise ContractError("裁决恢复状态与请求房间不一致")
            if command.request.player_id != request.player_id:
                raise ContractError("裁决恢复状态不属于当前玩家")

            adjudication = None
            if isinstance(command.request, SubmitAdjudicationRequest):
                adjudication = command.request.adjudication
            else:
                pending = await transaction.find_pending_check_by_action(
                    request.action_request_id
                )
                if pending is not None:
                    adjudication = pending.adjudication
            if adjudication is None:
                raise ContractError("裁决恢复缺少原始 ActionAdjudication")
            if adjudication.request_id != request.action_request_id:
                raise ContractError("裁决恢复的 action request id 不一致")
            if command.execution.action_request_id != request.action_request_id:
                raise ContractError("裁决恢复的 execution 不属于当前动作")
            runtime = await transaction.load_runtime()
            actor = runtime.game_state.actors.get(adjudication.actor_id)
            if actor is None or actor.player_id != request.player_id:
                raise ContractError("裁决恢复的 Actor 不属于当前玩家")

            return AdjudicationRecovery(
                action_request_id=request.action_request_id,
                actor_id=adjudication.actor_id,
                summary=adjudication.summary,
                execution=command.execution,
            )

    async def submit(self, request: SubmitAdjudicationRequest) -> AdjudicationExecution:
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            self._validate_identity(
                runtime,
                player_id=request.player_id,
                actor_id=request.adjudication.actor_id,
            )
            replay = await transaction.find_adjudication_command(
                request.adjudication.request_id
            )
            if replay is not None:
                return self._replay(request, replay, runtime.revision)
            self._require_revision(
                request.adjudication.source_revision,
                runtime.revision,
            )
            self._validate_adjudication(runtime, request.adjudication)

            if request.adjudication.check.mode == "none":
                new_state, events = self._finalize_action(
                    runtime,
                    request_id=request.adjudication.request_id,
                    adjudication=request.adjudication,
                    passed=True,
                    prefix_events=(),
                )
                execution = AdjudicationExecution(
                    request_id=request.adjudication.request_id,
                    action_request_id=request.adjudication.request_id,
                    status="resolved",
                    view_revision=str(new_state.event_sequence),
                    outcome="success",
                    event_refs=tuple(event.event_id for event in events),
                    public_event_refs=self._public_event_refs(events),
                )
                await transaction.commit_adjudication(
                    expected_revision=runtime.revision,
                    new_state=new_state,
                    events=events,
                    decision=None,
                    check_run=None,
                    completed_command=CompletedAdjudicationCommand(
                        request_id=request.adjudication.request_id,
                        request=request,
                        execution=execution,
                    ),
                )
                return execution

            existing = await transaction.find_pending_check_by_action(
                request.adjudication.request_id
            )
            if existing is not None:
                raise ContractError("action request 已存在待处理检定")
            options = self._validated_options(runtime, request.adjudication)
            decision = PendingCheckDecision(
                decision_id=self._new_id("check_decision"),
                room_id=request.room_id,
                player_id=request.player_id,
                actor_id=request.adjudication.actor_id,
                action_request_id=request.adjudication.request_id,
                source_revision=runtime.revision,
                status="awaiting_skill_choice",
                adjudication=request.adjudication,
                options=options,
            )
            event = self._event(
                runtime,
                offset=1,
                request_id=request.adjudication.request_id,
                actor_id=request.adjudication.actor_id,
                event_type="check.choice_requested",
                payload={
                    "decision_id": decision.decision_id,
                    "action_request_id": decision.action_request_id,
                    "decision_version": decision.decision_version,
                },
                visibility="private",
            )
            new_state = runtime.game_state.model_copy(
                update={"event_sequence": event.sequence},
                deep=True,
            )
            execution = AdjudicationExecution(
                request_id=request.adjudication.request_id,
                action_request_id=request.adjudication.request_id,
                status="awaiting_skill_choice",
                view_revision=str(new_state.event_sequence),
                outcome="pending",
                pending_decision=decision.player_view(),
                event_refs=(event.event_id,),
            )
            await transaction.commit_adjudication(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=(event,),
                decision=decision,
                check_run=None,
                completed_command=CompletedAdjudicationCommand(
                    request_id=request.adjudication.request_id,
                    request=request,
                    execution=execution,
                ),
            )
            return execution

    async def decide(self, request: CheckDecisionRequest) -> AdjudicationExecution:
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            replay = await transaction.find_adjudication_command(request.request_id)
            if replay is not None:
                return self._replay(request, replay, runtime.revision)
            self._require_revision(request.source_revision, runtime.revision)
            decision = await transaction.load_pending_check(request.decision_id)
            if decision is None:
                raise ContractError("PendingCheckDecision 不存在")
            self._validate_decision_owner(runtime, request.player_id, decision)
            if decision.status != "awaiting_skill_choice":
                raise ContractError("该检定已完成选择，不能再次选择或取消")
            if decision.decision_version != request.decision_version:
                raise ContractError("PendingCheckDecision version 已过期")

            if request.choice.kind == "cancel":
                event = self._event(
                    runtime,
                    offset=1,
                    request_id=request.request_id,
                    actor_id=decision.actor_id,
                    event_type="action.cancelled",
                    payload={
                        "decision_id": decision.decision_id,
                        "action_request_id": decision.action_request_id,
                    },
                )
                cancelled = decision.model_copy(
                    update={
                        "status": "cancelled",
                        "decision_version": decision.decision_version + 1,
                    },
                    deep=True,
                )
                new_state = runtime.game_state.model_copy(
                    update={"event_sequence": event.sequence},
                    deep=True,
                )
                execution = AdjudicationExecution(
                    request_id=request.request_id,
                    action_request_id=decision.action_request_id,
                    status="cancelled",
                    view_revision=str(new_state.event_sequence),
                    outcome="cancelled",
                    event_refs=(event.event_id,),
                    public_event_refs=(event.event_id,),
                )
                await transaction.commit_adjudication(
                    expected_revision=runtime.revision,
                    new_state=new_state,
                    events=(event,),
                    decision=cancelled,
                    check_run=None,
                    completed_command=CompletedAdjudicationCommand(
                        request_id=request.request_id,
                        request=request,
                        execution=execution,
                    ),
                )
                return execution

            option = next(
                (
                    item
                    for item in decision.options
                    if item.candidate_id == request.choice.candidate_id
                ),
                None,
            )
            if option is None:
                raise ContractError("candidate_id 不属于该 PendingCheckDecision")
            roll = self._roll(option.target_value, option.difficulty)
            post_options = self._post_roll_options(
                runtime,
                actor_id=decision.actor_id,
                option=option,
                roll=roll,
            )
            check_run = CheckRun(
                check_id=self._new_id("check"),
                room_id=request.room_id,
                player_id=request.player_id,
                actor_id=decision.actor_id,
                decision_id=decision.decision_id,
                action_request_id=decision.action_request_id,
                selected_candidate_id=option.candidate_id,
                selected_skill_id=option.skill_id,
                difficulty=option.difficulty,
                target_value=option.target_value,
                status=("awaiting_post_roll_decision" if post_options else "resolved"),
                roll_count=1,
                roll=roll,
                post_roll_options=post_options,
                final_result=None if post_options else roll,
                adjudication=decision.adjudication,
            )
            rolled_event = self._event(
                runtime,
                offset=1,
                request_id=request.request_id,
                actor_id=decision.actor_id,
                event_type="check.rolled",
                payload={
                    "check_id": check_run.check_id,
                    "action_request_id": decision.action_request_id,
                    "roll_count": 1,
                    "value": roll.value,
                    "degree": roll.degree,
                },
                visibility="private",
            )
            if post_options:
                rolled_decision = decision.model_copy(
                    update={
                        "status": "rolled",
                        "decision_version": decision.decision_version + 1,
                    },
                    deep=True,
                )
                new_state = runtime.game_state.model_copy(
                    update={"event_sequence": rolled_event.sequence},
                    deep=True,
                )
                execution = AdjudicationExecution(
                    request_id=request.request_id,
                    action_request_id=decision.action_request_id,
                    status="awaiting_post_roll_decision",
                    view_revision=str(new_state.event_sequence),
                    outcome="pending",
                    check_run=self._run_view(check_run),
                    event_refs=(rolled_event.event_id,),
                )
                await transaction.commit_adjudication(
                    expected_revision=runtime.revision,
                    new_state=new_state,
                    events=(rolled_event,),
                    decision=rolled_decision,
                    check_run=check_run,
                    completed_command=CompletedAdjudicationCommand(
                        request_id=request.request_id,
                        request=request,
                        execution=execution,
                    ),
                )
                return execution

            resolved_decision = decision.model_copy(
                update={
                    "status": "resolved",
                    "decision_version": decision.decision_version + 1,
                },
                deep=True,
            )
            new_state, events = self._finalize_action(
                runtime,
                request_id=request.request_id,
                adjudication=decision.adjudication,
                passed=roll.passed,
                prefix_events=(rolled_event,),
                check_run=check_run,
            )
            execution = AdjudicationExecution(
                request_id=request.request_id,
                action_request_id=decision.action_request_id,
                status="resolved",
                view_revision=str(new_state.event_sequence),
                outcome="success" if roll.passed else "failure",
                check_run=self._run_view(check_run),
                event_refs=tuple(event.event_id for event in events),
                public_event_refs=self._public_event_refs(events),
            )
            await transaction.commit_adjudication(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=events,
                decision=resolved_decision,
                check_run=check_run,
                completed_command=CompletedAdjudicationCommand(
                    request_id=request.request_id,
                    request=request,
                    execution=execution,
                ),
            )
            return execution

    async def decide_post_roll(
        self,
        request: PostRollDecisionRequest,
    ) -> AdjudicationExecution:
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            replay = await transaction.find_adjudication_command(request.request_id)
            if replay is not None:
                return self._replay(request, replay, runtime.revision)
            self._require_revision(request.source_revision, runtime.revision)
            check_run = await transaction.load_check_run(request.check_id)
            if check_run is None:
                raise ContractError("CheckRun 不存在")
            self._validate_identity(
                runtime,
                player_id=request.player_id,
                actor_id=check_run.actor_id,
            )
            if check_run.status != "awaiting_post_roll_decision":
                raise ContractError("CheckRun 已经收束")
            if check_run.version != request.check_version:
                raise ContractError("CheckRun version 已过期")
            option = next(
                (
                    item
                    for item in check_run.post_roll_options
                    if item.option_id == request.option_id
                ),
                None,
            )
            if option is None:
                raise ContractError("option_id 不属于该 CheckRun")
            if isinstance(option, PushOption) != (
                request.push_adjudication is not None
            ):
                raise ContractError("只有强推选项必须携带 push_adjudication")

            state = runtime.game_state.model_copy(deep=True)
            prefix: list[DomainEvent] = [
                self._event(
                    runtime,
                    offset=1,
                    request_id=request.request_id,
                    actor_id=check_run.actor_id,
                    event_type="check.post_roll_option_selected",
                    payload={
                        "check_id": check_run.check_id,
                        "option_id": option.option_id,
                        "kind": option.kind,
                    },
                    visibility="private",
                )
            ]
            final_roll = check_run.roll
            roll_count = check_run.roll_count
            if isinstance(option, SpendResourceOption):
                state = self._spend_luck(state, check_run.actor_id, option.cost)
                final_roll = CheckRoll(
                    value=check_run.roll.value,
                    degree=option.result_degree,
                    passed=True,
                )
                prefix.append(
                    self._event_from_state(
                        state,
                        room_id=request.room_id,
                        offset=len(prefix) + 1,
                        request_id=request.request_id,
                        actor_id=check_run.actor_id,
                        event_type="actor.resource_spent",
                        payload={"resource_id": "luck", "cost": option.cost},
                        visibility="private",
                    )
                )
            elif isinstance(option, PushOption):
                final_roll = self._roll(check_run.target_value, check_run.difficulty)
                roll_count = 2
                prefix.append(
                    self._event_from_state(
                        state,
                        room_id=request.room_id,
                        offset=len(prefix) + 1,
                        request_id=request.request_id,
                        actor_id=check_run.actor_id,
                        event_type="check.rolled",
                        payload={
                            "check_id": check_run.check_id,
                            "action_request_id": check_run.action_request_id,
                            "roll_count": 2,
                            "value": final_roll.value,
                            "degree": final_roll.degree,
                        },
                        visibility="private",
                    )
                )
            elif not isinstance(option, AcceptResultOption):
                raise ContractError("不支持的检定后选项")

            runtime_after_resource = runtime.model_copy(
                update={"game_state": state}, deep=True
            )
            resolved_run = check_run.model_copy(
                update={
                    "status": "resolved",
                    "version": check_run.version + 1,
                    "roll_count": roll_count,
                    "post_roll_options": (),
                    "final_result": final_roll,
                },
                deep=True,
            )
            decision = await transaction.load_pending_check(check_run.decision_id)
            if decision is None:
                raise ContractError("CheckRun 引用的 PendingCheckDecision 不存在")
            resolved_decision = decision.model_copy(
                update={
                    "status": "resolved",
                    "decision_version": decision.decision_version + 1,
                },
                deep=True,
            )
            new_state, events = self._finalize_action(
                runtime_after_resource,
                request_id=request.request_id,
                adjudication=check_run.adjudication,
                passed=final_roll.passed,
                prefix_events=tuple(prefix),
                check_run=resolved_run,
            )
            execution = AdjudicationExecution(
                request_id=request.request_id,
                action_request_id=check_run.action_request_id,
                status="resolved",
                view_revision=str(new_state.event_sequence),
                outcome="success" if final_roll.passed else "failure",
                check_run=self._run_view(resolved_run),
                event_refs=tuple(event.event_id for event in events),
                public_event_refs=self._public_event_refs(events),
            )
            await transaction.commit_adjudication(
                expected_revision=runtime.revision,
                new_state=new_state,
                events=events,
                decision=resolved_decision,
                check_run=resolved_run,
                completed_command=CompletedAdjudicationCommand(
                    request_id=request.request_id,
                    request=request,
                    execution=execution,
                ),
            )
            return execution

    @staticmethod
    def _public_event_refs(events: tuple[DomainEvent, ...]) -> tuple[str, ...]:
        return tuple(event.event_id for event in events if event.visibility == "public")

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
        if runtime.game_state.phase != "playing":
            raise ContractError("游戏已经结束，不能提交新裁决")

    @staticmethod
    def _require_revision(source: str, current: str) -> None:
        if source != current:
            raise ContractError("裁决基于过期 PlayerView")

    @staticmethod
    def _replay(request, completed, current_revision: str) -> AdjudicationExecution:
        if request != completed.request:
            raise ContractError("request_id 已用于不同的裁决命令")
        return completed.execution.model_copy(
            update={"view_revision": current_revision},
            deep=True,
        )

    def _validate_adjudication(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
    ) -> None:
        module = runtime.module_content
        state = runtime.game_state
        target = adjudication.target
        exists = {
            "information": target.id in runtime.canon_information_ids,
            "entity": target.id in runtime.canon_entity_ids
            or target.id in state.runtime_entities
            or target.id in state.item_instances,
            "location": target.id in runtime.canon_location_ids
            or target.id in state.runtime_locations,
            "actor": target.id in state.actors,
            "world": target.id == module.world_ref,
        }[target.kind]
        if not exists:
            raise ContractError("ActionAdjudication target 引用了不存在或隐藏的对象")
        if adjudication.rule_decision is not None:
            if not runtime.is_v3:
                raise ContractError("RuleDecision 只在 ModuleContent v3 房间可用")
            # Refuses an id the module never declared, so a model cannot invent
            # a rule or reach a branch its option does not select.
            resolve_rule_option(
                runtime.v3,
                rule_id=adjudication.rule_decision.rule_id,
                option_id=adjudication.rule_decision.option_id,
            )
        self._validate_effect_sequence(runtime, adjudication.success_effects)
        self._validate_effect_sequence(runtime, adjudication.failure_effects)
        if adjudication.check.mode != "none":
            self._validated_options(runtime, adjudication)

    def _validate_effect_sequence(
        self,
        runtime: EngineRuntimeSnapshot,
        effects: tuple[ActionEffect, ...],
    ) -> None:
        information_ids = runtime.canon_information_ids
        entity_ids = (
            runtime.canon_entity_ids
            | set(runtime.game_state.runtime_entities)
            | set(runtime.game_state.item_instances)
        )
        location_ids = runtime.canon_location_ids | set(
            runtime.game_state.runtime_locations
        )
        # Sleeping until 20:00 is several jumps in one adjudication, so each one
        # has to be checked against the clock the previous jump left behind —
        # not against the clock this action started on.
        world_time = runtime.game_state.world_time
        for effect in effects:
            self._validate_effect(
                runtime,
                effect,
                information_ids=information_ids,
                entity_ids=entity_ids,
                location_ids=location_ids,
                world_time=world_time,
            )
            if isinstance(effect, EnsureRuntimeLocationEffect):
                location_ids.add(effect.location_id)
            elif isinstance(effect, EnsureRuntimeEntityEffect):
                entity_ids.add(effect.entity_id)
            elif isinstance(effect, AdvanceWorldTimeEffect):
                world_time = advanced_to_next(runtime.v3, world_time)

    def _validated_options(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
    ) -> tuple[PendingCheckOption, ...]:
        actor = runtime.game_state.actors[adjudication.actor_id]
        skills = actor.state.get("skills")
        labels = actor.state.get("skill_labels")
        if not isinstance(skills, dict):
            raise ContractError("Actor 没有可验证的 Ruleset 技能快照")
        label_map = labels if isinstance(labels, dict) else {}
        options: list[PendingCheckOption] = []
        for candidate in adjudication.check.candidates:
            value = skills.get(candidate.skill_id)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 100
            ):
                raise ContractError(
                    f"技能候选不属于 Actor 或数值非法: {candidate.skill_id}"
                )
            label = label_map.get(candidate.skill_id)
            options.append(
                PendingCheckOption(
                    candidate_id=candidate.candidate_id,
                    skill_id=candidate.skill_id,
                    display_name=(
                        label
                        if isinstance(label, str) and label.strip()
                        else candidate.skill_id
                    ),
                    target_value=value,
                    difficulty=candidate.difficulty,
                    method_summary=candidate.method_summary,
                    player_safe_reason=candidate.player_safe_reason,
                )
            )
        return tuple(options)

    def _validate_effect(
        self,
        runtime: EngineRuntimeSnapshot,
        effect: ActionEffect,
        *,
        information_ids: set[str],
        entity_ids: set[str],
        location_ids: set[str],
        world_time: WorldTimeState | None = None,
    ) -> None:
        state = runtime.game_state
        if isinstance(effect, RevealInformationEffect | HideInformationEffect):
            if effect.information_id not in information_ids:
                raise ContractError("信息效果不能创建不存在的 Canon Information")
        elif isinstance(effect, SetVisibilityEffect):
            valid = {
                "information": information_ids,
                "entity": entity_ids,
                "location": location_ids,
            }[effect.target_kind]
            if effect.target_id not in valid:
                raise ContractError("set_visibility 引用了不存在的对象")
        elif isinstance(effect, EnterLocationEffect):
            if effect.location_id not in location_ids:
                raise ContractError("enter_location 引用了不存在的地点")
        elif isinstance(effect, EnsureRuntimeLocationEffect):
            if (
                effect.location_id in location_ids
                or effect.connected_location_id not in location_ids
            ):
                raise ContractError("Runtime Location 发生 Canon shadow 或连接引用非法")
            if (
                effect.parent_location_id is not None
                and effect.parent_location_id not in location_ids
            ):
                raise ContractError("Runtime Location parent 不存在")
        elif isinstance(effect, EnsureRuntimeEntityEffect):
            if effect.entity_id in entity_ids or effect.location_id not in location_ids:
                raise ContractError("Runtime Entity 发生 Canon shadow 或地点引用非法")
            if (
                runtime.is_v3
                and effect.entity_kind == "object"
                and (len(effect.entity_id) > 100 or len(effect.name) > 200)
            ):
                raise ContractError("Runtime Item 的 id 或名称超过 ItemInstance 上限")
        elif isinstance(
            effect, MoveEntityEffect | ChangeEntityStateEffect | ConsumeEntityEffect
        ):
            if effect.entity_id not in entity_ids:
                raise ContractError("实体效果引用不存在的 Entity")
            if isinstance(effect, MoveEntityEffect):
                if (
                    effect.location_id is not None
                    and effect.location_id not in location_ids
                ):
                    raise ContractError("move_entity 目标地点不存在")
                if (
                    effect.holder_actor_id is not None
                    and effect.holder_actor_id not in state.actors
                ):
                    raise ContractError("move_entity holder Actor 不存在")
        elif isinstance(effect, AdvanceWorldTimeEffect):
            if not runtime.is_v3:
                raise ContractError("只有 v3 房间有离散时间线")
            blocked = time_advance_block_reason(tuple(state.actors))
            if blocked is not None:
                raise ContractError(blocked)
            target, _ = next_point_after(
                runtime.v3, world_time if world_time is not None else state.world_time
            )
            if effect.to_point_id is not None and effect.to_point_id != target.id:
                raise ContractError(
                    "advance_world_time 声明的时间点不是时间线上的下一个点: "
                    f"{effect.to_point_id} != {target.id}"
                )
        elif isinstance(effect, CommitTerminalEndingEffect):
            raise ContractError("终局不能由行动效果直接提交，必须确认 EndingDraft")

    def _roll(self, target_value: int, difficulty: str) -> CheckRoll:
        value = self._dice.percentile()
        level = coc7_success_level(target_value, value)
        passed = passes_difficulty(level, difficulty)
        degree: CheckDegree = {
            "critical": "critical_success",
            "extreme": "extreme_success",
            "hard": "hard_success",
            "regular": "regular_success",
            "failure": "failure",
            "fumble": "fumble",
        }[level]  # type: ignore[assignment]
        return CheckRoll(value=value, degree=degree, passed=passed)

    @staticmethod
    def _post_roll_options(
        runtime: EngineRuntimeSnapshot,
        *,
        actor_id: str,
        option: PendingCheckOption,
        roll: CheckRoll,
    ) -> tuple[AcceptResultOption | SpendResourceOption | PushOption, ...]:
        options: list[AcceptResultOption | SpendResourceOption | PushOption] = [
            AcceptResultOption(option_id="accept-current")
        ]
        if roll.passed:
            return tuple(options)
        threshold = {
            "regular": option.target_value,
            "hard": option.target_value // 2,
            "extreme": option.target_value // 5,
        }[option.difficulty]
        actor = runtime.game_state.actors.get(actor_id)
        luck_value = actor.resources.luck if actor is not None else None
        cost = roll.value - threshold
        if (
            roll.degree != "fumble"
            and cost > 0
            and luck_value is not None
            and luck_value >= cost
        ):
            options.append(
                SpendResourceOption(
                    option_id=f"spend-luck-{cost}",
                    cost=cost,
                    result_degree={
                        "regular": "regular_success",
                        "hard": "hard_success",
                        "extreme": "extreme_success",
                    }[option.difficulty],
                )
            )
        options.append(
            PushOption(
                option_id="push-once",
                player_safe_risk_summary="再次尝试会承担更严重的失败后果",
            )
        )
        return tuple(options)

    @staticmethod
    def _spend_luck(state: GameState, actor_id: str, cost: int) -> GameState:
        actor = state.actors[actor_id]
        luck = actor.resources.luck
        if luck is None or luck < cost:
            raise ContractError("Actor 当前幸运不足，不能选择该选项")
        resources = actor.resources.model_copy(update={"luck": luck - cost}, deep=True)
        actors = dict(state.actors)
        actors[actor_id] = actor.model_copy(update={"resources": resources}, deep=True)
        return state.model_copy(update={"actors": actors}, deep=True)

    @staticmethod
    def _owned_effects(
        runtime: EngineRuntimeSnapshot,
        *,
        adjudication: ActionAdjudication,
        passed: bool,
        check_run: CheckRun | None,
    ) -> tuple[ActionEffect, ...]:
        """Whose effects commit: the rule's if one owns this action, else the Agent's.

        #226 §5 gives a named rule `effect_authority: rule` — the Agent chose the
        method, but the published rule decides what the result does. Its
        `result_routes` map the actual degree to a step, so a hard success and a
        regular success can diverge in ways an Agent-authored effect list cannot
        express.
        """

        decision = adjudication.rule_decision
        if decision is None or not runtime.is_v3:
            return (
                adjudication.success_effects if passed else adjudication.failure_effects
            )
        rule, branch_id = resolve_rule_option(
            runtime.v3,
            rule_id=decision.rule_id,
            option_id=decision.option_id,
        )
        step, _ = pending_check_for(rule, branch_id)
        if step is None or check_run is None:
            # No check in this branch: the whole chain already ran at submit time.
            return ()
        degree = (check_run.final_result or check_run.roll).degree
        return tuple(effects_after_degree(rule, step.id, degree))

    def _finalize_action(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        request_id: str,
        adjudication: ActionAdjudication,
        passed: bool,
        prefix_events: tuple[DomainEvent, ...],
        check_run: CheckRun | None = None,
    ) -> tuple[GameState, tuple[DomainEvent, ...]]:
        state = runtime.game_state.model_copy(deep=True)
        events = list(prefix_events)
        if check_run is not None:
            events.append(
                self._event_from_state(
                    state,
                    room_id=runtime.game_state.room_id,
                    offset=len(events) + 1,
                    request_id=request_id,
                    actor_id=adjudication.actor_id,
                    event_type="check.resolved",
                    payload={
                        "check_id": check_run.check_id,
                        "action_request_id": check_run.action_request_id,
                        "passed": passed,
                        "degree": (check_run.final_result or check_run.roll).degree,
                    },
                )
            )
        selected_effects = self._owned_effects(
            runtime,
            adjudication=adjudication,
            passed=passed,
            check_run=check_run,
        )
        for effect in selected_effects:
            state, emitted = self._apply_effect(
                runtime,
                state,
                effect,
                room_id=runtime.game_state.room_id,
                request_id=request_id,
                actor_id=adjudication.actor_id,
                offset=len(events) + 1,
            )
            events.extend(emitted)
        events.append(
            self._event_from_state(
                state,
                room_id=runtime.game_state.room_id,
                offset=len(events) + 1,
                request_id=request_id,
                actor_id=adjudication.actor_id,
                event_type="action.succeeded" if passed else "action.failed",
                payload={"action_request_id": adjudication.request_id},
            )
        )
        state, events = self._apply_event_rules(
            runtime,
            state=state,
            events=events,
            request_id=request_id,
            actor_id=adjudication.actor_id,
        )
        state = state.model_copy(
            update={"event_sequence": runtime.game_state.event_sequence + len(events)},
            deep=True,
        )
        return state, tuple(events)

    def _apply_event_rules(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        state: GameState,
        events: list[DomainEvent],
        request_id: str,
        actor_id: str,
    ) -> tuple[GameState, list[DomainEvent]]:
        if runtime.is_v3:
            return self._apply_v3_event_rules(
                runtime,
                state=state,
                events=events,
                request_id=request_id,
                actor_id=actor_id,
            )

        cursor = 0
        fired: set[tuple[str, str]] = set()
        while cursor < len(events):
            source_event = events[cursor]
            cursor += 1
            for rule_id, effects in self._triggered_rule_effects(
                runtime,
                state=state,
                source_event=source_event,
                actor_id=actor_id,
            ):
                fire_key = (rule_id, source_event.event_id)
                if fire_key in fired:
                    continue
                fired.add(fire_key)
                if len(events) >= 100:
                    raise ContractError("Event-driven Rule 超过单次裁决步数上限")
                events.append(
                    self._event_from_state(
                        state,
                        room_id=runtime.game_state.room_id,
                        offset=len(events) + 1,
                        request_id=request_id,
                        actor_id=actor_id,
                        event_type="rule.triggered",
                        payload={
                            "rule_id": rule_id,
                            "source_event_id": source_event.event_id,
                        },
                        visibility="hidden",
                    )
                )
                rule_runtime = runtime.model_copy(
                    update={"game_state": state}, deep=True
                )
                self._validate_effect_sequence(rule_runtime, tuple(effects))
                for effect in effects:
                    state, emitted = self._apply_effect(
                        runtime,
                        state,
                        effect,
                        room_id=runtime.game_state.room_id,
                        request_id=request_id,
                        actor_id=actor_id,
                        offset=len(events) + 1,
                    )
                    events.extend(emitted)
        return state, events

    def _apply_v3_event_rules(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        state: GameState,
        events: list[DomainEvent],
        request_id: str,
        actor_id: str,
    ) -> tuple[GameState, list[DomainEvent]]:
        """Run event Rules in queue order and persist the first blocked cursor.

        Effects and the resulting Agenda are returned in the same ``new_state``
        and therefore committed atomically by ``commit_adjudication``.
        """

        agenda = create_rule_agenda(
            agenda_id=self._new_id("agenda"),
            room_id=runtime.game_state.room_id,
            module=runtime.v3,
            correlation_id=request_id,
            root_source=AgendaSource(kind="action", id=request_id),
            revision=str(runtime.game_state.event_sequence),
        )
        queue = []
        source_event_ids: list[str] = []
        fired: set[tuple[str, str]] = set()
        cursor = 0
        suspended = False

        while cursor < len(events) and not suspended:
            source_event = events[cursor]
            cursor += 1
            # Workflow/audit signals are never gameplay Rule inputs (#226 §4).
            if source_event.type == "rule.triggered":
                continue
            rules = matching_event_rules(
                runtime.v3,
                event_type=source_event.type,
                state=state,
                actor_id=actor_id,
            )
            pending_rules = []
            for rule in rules:
                fire_key = (rule.id, source_event.event_id)
                if fire_key in fired:
                    continue
                fired.add(fire_key)
                pending_rules.append(rule)
                queue.append(agenda_item_for_event(rule, source_event))
            if pending_rules:
                source_event_ids.append(source_event.event_id)

            for rule in pending_rules:
                item_index = next(
                    index
                    for index, item in enumerate(queue)
                    if item.source_event_id == source_event.event_id
                    and item.rule_id == rule.id
                    and item.status == "queued"
                )
                queue[item_index] = queue[item_index].model_copy(
                    update={"status": "running"}
                )
                next_depth = agenda.chain_depth + 1
                max_chain_depth = min(
                    agenda.max_chain_depth, rule.limits.max_chain_depth
                )
                max_steps = min(agenda.max_steps, rule.limits.max_steps)
                agenda = agenda.model_copy(
                    update={
                        "chain_depth": next_depth,
                        "max_chain_depth": max_chain_depth,
                        "max_steps": max_steps,
                    }
                )
                if next_depth > max_chain_depth:
                    queue[item_index] = queue[item_index].model_copy(
                        update={"status": "failed"}
                    )
                    agenda = agenda.model_copy(
                        update={
                            "status": "failed",
                            "failure_code": "agenda_budget_exceeded",
                            "current_rule_id": rule.id,
                            "current_branch_id": queue[item_index].branch_id,
                        }
                    )
                    suspended = True
                    break

                walk = walk_rule(rule, branch_id=queue[item_index].branch_id)
                next_step_count = agenda.step_count + walk.step_count
                if next_step_count > max_steps:
                    queue[item_index] = queue[item_index].model_copy(
                        update={"status": "failed"}
                    )
                    agenda = agenda.model_copy(
                        update={
                            "status": "failed",
                            "failure_code": "agenda_budget_exceeded",
                            "current_rule_id": rule.id,
                            "current_branch_id": queue[item_index].branch_id,
                            "current_step_id": walk.suspended_at
                            or next(
                                branch.entry_step_id
                                for branch in rule.execution.branches
                                if branch.id == queue[item_index].branch_id
                            ),
                            "step_count": next_step_count,
                        }
                    )
                    suspended = True
                    break
                agenda = agenda.model_copy(update={"step_count": next_step_count})

                events.append(
                    self._event_from_state(
                        state,
                        room_id=runtime.game_state.room_id,
                        offset=len(events) + 1,
                        request_id=request_id,
                        actor_id=actor_id,
                        event_type="rule.triggered",
                        payload={
                            "rule_id": rule.id,
                            "source_event_id": source_event.event_id,
                            "agenda_id": agenda.agenda_id,
                        },
                        visibility="hidden",
                    )
                )
                rule_runtime = runtime.model_copy(
                    update={"game_state": state}, deep=True
                )
                self._validate_effect_sequence(rule_runtime, tuple(walk.effects))
                for effect in walk.effects:
                    state, emitted = self._apply_effect(
                        runtime,
                        state,
                        effect,
                        room_id=runtime.game_state.room_id,
                        request_id=request_id,
                        actor_id=actor_id,
                        offset=len(events) + 1,
                    )
                    events.extend(emitted)

                status = agenda_status_for_walk(rule, walk)
                if status == "stable":
                    queue[item_index] = queue[item_index].model_copy(
                        update={"status": "completed"}
                    )
                    continue
                queue[item_index] = queue[item_index].model_copy(
                    update={"status": "failed" if status == "failed" else "running"}
                )
                agenda = agenda.model_copy(
                    update={
                        "status": status,
                        "failure_code": (
                            "agenda_budget_exceeded" if status == "failed" else None
                        ),
                        "current_rule_id": rule.id,
                        "current_branch_id": queue[item_index].branch_id,
                        "current_step_id": walk.suspended_at,
                    }
                )
                suspended = True
                break

        if not queue:
            return state, events
        if not suspended:
            agenda = agenda.model_copy(
                update={
                    "status": "stable",
                    "current_rule_id": None,
                    "current_branch_id": None,
                    "current_step_id": None,
                }
            )
        final_revision = str(runtime.game_state.event_sequence + len(events))
        agenda = agenda.model_copy(
            update={
                "source_event_ids": tuple(source_event_ids),
                "queue": tuple(queue),
                "revision": final_revision,
            },
            deep=True,
        )
        agendas = dict(state.rule_agendas)
        agendas[agenda.agenda_id] = agenda
        state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
        return state, events

    @staticmethod
    def _triggered_rule_effects(
        runtime: EngineRuntimeSnapshot,
        *,
        state: GameState,
        source_event: DomainEvent,
        actor_id: str,
    ) -> list[tuple[str, list[ActionEffect]]]:
        """Rules this event fires, already reduced to the effects they commit.

        v3 rules are step graphs, so the effects are whatever the walk collects
        before it has to suspend (see engine/rules_v3.py).
        """

        if not runtime.is_v3:
            return [
                (rule.id, list(rule.effects))
                for rule in sorted(
                    (
                        rule
                        for rule in runtime.v2.event_rules
                        if rule.event_type == source_event.type
                        and all(
                            source_event.payload.get(key) == value
                            for key, value in rule.payload_matches.items()
                        )
                    ),
                    key=lambda rule: (-rule.priority, rule.id),
                )
            ]
        triggered = []
        for rule in matching_event_rules(
            runtime.v3,
            event_type=source_event.type,
            state=state,
            actor_id=actor_id,
        ):
            walk = walk_rule(rule)
            if walk.effects:
                triggered.append((rule.id, walk.effects))
        return triggered

    def _apply_effect(
        self,
        runtime: EngineRuntimeSnapshot,
        state: GameState,
        effect: ActionEffect,
        *,
        room_id: str,
        request_id: str,
        actor_id: str,
        offset: int,
    ) -> tuple[GameState, tuple[DomainEvent, ...]]:
        event_type: str | None = None
        effect_event_id: str | None = None
        payload: dict[str, JsonValue] = {}
        if isinstance(effect, NarrativeOnlyEffect):
            return state, ()
        if isinstance(effect, RevealInformationEffect | HideInformationEffect):
            reveal = isinstance(effect, RevealInformationEffect)
            if effect.scope == "party":
                facts = set(state.discovered_facts)
                (facts.add if reveal else facts.discard)(effect.information_id)
                state = state.model_copy(
                    update={"discovered_facts": tuple(sorted(facts))},
                    deep=True,
                )
            else:
                actor_facts = deepcopy(state.actor_discovered_facts)
                facts = set(actor_facts.get(actor_id, ()))
                (facts.add if reveal else facts.discard)(effect.information_id)
                actor_facts[actor_id] = tuple(sorted(facts))
                state = state.model_copy(
                    update={"actor_discovered_facts": actor_facts},
                    deep=True,
                )
            event_type = "information.revealed" if reveal else "information.hidden"
            payload = {"information_id": effect.information_id, "scope": effect.scope}
        elif isinstance(effect, SetVisibilityEffect):
            overrides = dict(state.visibility_overrides)
            # Party scope must not be keyed by the acting actor, or no other
            # actor could ever find the override again. Actor scope keeps the
            # actor id and wins over the party entry when both exist
            # (see RuleEngineService._override_allows).
            key = (
                f"actor:{actor_id}:{effect.target_kind}:{effect.target_id}"
                if effect.scope == "actor"
                else f"party:{effect.target_kind}:{effect.target_id}"
            )
            overrides[key] = effect.visible
            updates: dict[str, object] = {"visibility_overrides": overrides}
            if effect.target_kind == "location":
                knowledge_by_scope = (
                    deepcopy(state.actor_location_knowledge)
                    if effect.scope == "actor"
                    else deepcopy(state.party_location_knowledge)
                )
                if effect.scope == "actor":
                    actor_knowledge = knowledge_by_scope.setdefault(actor_id, {})
                    previous_knowledge = actor_knowledge.get(effect.target_id)
                    actor_knowledge[effect.target_id] = _visibility_knowledge(
                        effect.target_id,
                        scope="actor",
                        visible=effect.visible,
                        previous=previous_knowledge,
                    )
                    updates["actor_location_knowledge"] = knowledge_by_scope
                else:
                    previous_knowledge = knowledge_by_scope.get(effect.target_id)
                    knowledge_by_scope[effect.target_id] = _visibility_knowledge(
                        effect.target_id,
                        scope="party",
                        visible=effect.visible,
                        previous=previous_knowledge,
                    )
                    updates["party_location_knowledge"] = knowledge_by_scope
            state = state.model_copy(update=updates, deep=True)
            event_type = "visibility.changed"
            payload = {
                "target_kind": effect.target_kind,
                "target_id": effect.target_id,
                "visible": effect.visible,
                "scope": effect.scope,
            }
        elif isinstance(effect, EnterLocationEffect):
            if not runtime.is_v3:
                previous = state.scene_id
                state = state.model_copy(
                    update={"scene_id": effect.location_id}, deep=True
                )
                event_type = "location.entered"
                payload = {
                    "location_id": effect.location_id,
                    "from_location_id": previous,
                }
            else:
                resolution = resolve_location_target(
                    runtime.v3,
                    state,
                    actor_id=actor_id,
                    target_id=effect.location_id,
                )
                contexts = dict(state.actor_position_contexts)
                knowledge = dict(state.party_location_knowledge)
                previous_knowledge = knowledge.get(effect.location_id)
                if resolution.status == "known_reachable":
                    contexts.pop(actor_id, None)
                    knowledge[effect.location_id] = LocationKnowledge(
                        location_id=effect.location_id,
                        scope="party",
                        existence="known",
                        localization="located",
                        access="reachable",
                        visited=True,
                        known_connection_ids=(
                            previous_knowledge.known_connection_ids
                            if previous_knowledge is not None
                            else ()
                        ),
                    )
                    travel = TravelResolved(
                        destination_id=effect.location_id,
                        path=resolution.path,
                    )
                    state = state.model_copy(
                        update={
                            "scene_id": effect.location_id,
                            "party_location_knowledge": knowledge,
                            "actor_position_contexts": contexts,
                        },
                        deep=True,
                    )
                    event_type = "travel.resolved"
                    payload = {
                        "destination_id": travel.destination_id,
                        "path": list(travel.path),
                    }
                elif resolution.status == "known_blocked":
                    assert resolution.boundary is not None
                    assert resolution.reached_location_id is not None
                    travel = TravelInterrupted(
                        destination_id=effect.location_id,
                        current_location_id=resolution.reached_location_id,
                        path=resolution.path,
                        reached_boundary=resolution.boundary,
                    )
                    contexts[actor_id] = travel
                    knowledge[effect.location_id] = LocationKnowledge(
                        location_id=effect.location_id,
                        scope="party",
                        existence="known",
                        localization="located",
                        access="blocked",
                        visited=bool(previous_knowledge and previous_knowledge.visited),
                        known_connection_ids=(
                            previous_knowledge.known_connection_ids
                            if previous_knowledge is not None
                            else ()
                        ),
                    )
                    state = state.model_copy(
                        update={
                            "scene_id": travel.current_location_id,
                            "party_location_knowledge": knowledge,
                            "actor_position_contexts": contexts,
                        },
                        deep=True,
                    )
                    event_type = "travel.interrupted"
                    payload = {
                        "destination_id": travel.destination_id,
                        "current_location_id": travel.current_location_id,
                        "path": list(travel.path),
                        "reached_boundary": travel.reached_boundary.to_json_dict(),
                    }
                else:
                    raise ContractError(
                        resolution.safe_reason or "当前没有可确认的目标路线"
                    )
        elif isinstance(effect, EnsureRuntimeLocationEffect):
            locations = deepcopy(state.runtime_locations)
            locations[effect.location_id] = {
                "name": effect.name,
                "parent_location_id": effect.parent_location_id,
                "connected_location_id": effect.connected_location_id,
                "provenance": "agent_adjudication",
            }
            knowledge = dict(state.party_location_knowledge)
            knowledge[effect.location_id] = LocationKnowledge(
                location_id=effect.location_id,
                existence="known",
                localization="located",
                access="reachable",
            )
            state = state.model_copy(
                update={
                    "runtime_locations": locations,
                    "party_location_knowledge": knowledge,
                },
                deep=True,
            )
            event_type = "location.created"
            payload = {"location_id": effect.location_id}
        elif isinstance(effect, EnsureRuntimeEntityEffect):
            if runtime.is_v3 and effect.entity_kind == "object":
                effect_event_id = self._new_id("evt")
                revision = str(state.event_sequence + offset)
                items = deepcopy(state.item_instances)
                items[effect.entity_id] = ItemInstance(
                    id=effect.entity_id,
                    room_id=room_id,
                    origin="runtime",
                    definition_id=effect.entity_id,
                    display=ItemDisplay(name=effect.name),
                    item_component=ItemComponent(),
                    custody=ItemCustody(
                        kind="location",
                        ref_id=effect.location_id,
                        form="loose",
                    ),
                    acquisition=ItemAcquisition(
                        source_type="runtime",
                        source_id=effect.location_id,
                        player_safe_label="行动中发现",
                        event_id=effect_event_id,
                        revision=revision,
                    ),
                    created_event_id=effect_event_id,
                    last_event_id=effect_event_id,
                    updated_revision=revision,
                )
                party_knowledge = deepcopy(state.party_item_knowledge)
                party_knowledge[effect.entity_id] = ItemKnowledge(
                    item_id=effect.entity_id,
                    identity="recognized",
                )
                state = state.model_copy(
                    update={
                        "item_instances": items,
                        "party_item_knowledge": party_knowledge,
                    },
                    deep=True,
                )
            else:
                entities = deepcopy(state.runtime_entities)
                entities[effect.entity_id] = {
                    "kind": effect.entity_kind,
                    "name": effect.name,
                    "location_id": effect.location_id,
                    "provenance": "agent_adjudication",
                }
                state = state.model_copy(
                    update={"runtime_entities": entities}, deep=True
                )
            event_type = "entity.created"
            payload = {"entity_id": effect.entity_id, "location_id": effect.location_id}
        elif isinstance(effect, MoveEntityEffect):
            item = state.item_instances.get(effect.entity_id)
            if item is not None:
                effect_event_id = self._new_id("evt")
                revision = str(state.event_sequence + offset)
                custody = (
                    ItemCustody(
                        kind="actor_inventory",
                        ref_id=effect.holder_actor_id,
                        form="carried",
                    )
                    if effect.holder_actor_id is not None
                    else ItemCustody(
                        kind="location",
                        ref_id=effect.location_id,
                        form="placed",
                    )
                )
                items = deepcopy(state.item_instances)
                items[effect.entity_id] = item.model_copy(
                    update={
                        "custody": custody,
                        "version": item.version + 1,
                        "last_event_id": effect_event_id,
                        "updated_revision": revision,
                    }
                )
                updates: dict[str, object] = {"item_instances": items}
                if effect.holder_actor_id is not None:
                    actor_knowledge = deepcopy(state.actor_item_knowledge)
                    actor_knowledge.setdefault(effect.holder_actor_id, {})[
                        effect.entity_id
                    ] = ItemKnowledge(
                        item_id=effect.entity_id,
                        scope="actor",
                        identity="known",
                    )
                    updates["actor_item_knowledge"] = actor_knowledge
                else:
                    party_knowledge = deepcopy(state.party_item_knowledge)
                    party_knowledge[effect.entity_id] = ItemKnowledge(
                        item_id=effect.entity_id,
                        identity="recognized",
                    )
                    updates["party_item_knowledge"] = party_knowledge
                state = state.model_copy(update=updates, deep=True)
            else:
                runtime_entities = deepcopy(state.runtime_entities)
                entity_states = deepcopy(state.entities)
                target = runtime_entities.get(effect.entity_id)
                if target is None:
                    target = entity_states.setdefault(effect.entity_id, {})
                target["location_id"] = effect.location_id
                target["holder_actor_id"] = effect.holder_actor_id
                state = state.model_copy(
                    update={
                        "runtime_entities": runtime_entities,
                        "entities": entity_states,
                    },
                    deep=True,
                )
            event_type = "entity.moved"
            payload = {
                "entity_id": effect.entity_id,
                "location_id": effect.location_id,
                "holder_actor_id": effect.holder_actor_id,
            }
        elif isinstance(effect, ChangeEntityStateEffect):
            item = state.item_instances.get(effect.entity_id)
            if item is not None:
                effect_event_id = self._new_id("evt")
                revision = str(state.event_sequence + offset)
                values = deepcopy(item.state.values)
                values[effect.key] = effect.value
                items = deepcopy(state.item_instances)
                items[effect.entity_id] = item.model_copy(
                    update={
                        "state": item.state.model_copy(update={"values": values}),
                        "version": item.version + 1,
                        "last_event_id": effect_event_id,
                        "updated_revision": revision,
                    }
                )
                state = state.model_copy(update={"item_instances": items}, deep=True)
            else:
                runtime_entities = deepcopy(state.runtime_entities)
                entity_states = deepcopy(state.entities)
                target = runtime_entities.get(effect.entity_id)
                if target is None:
                    target = entity_states.setdefault(effect.entity_id, {})
                target[effect.key] = effect.value
                state = state.model_copy(
                    update={
                        "runtime_entities": runtime_entities,
                        "entities": entity_states,
                    },
                    deep=True,
                )
            event_type = "entity.state_changed"
            payload = {
                "entity_id": effect.entity_id,
                "key": effect.key,
                "value": effect.value,
            }
        elif isinstance(effect, ConsumeEntityEffect):
            item = state.item_instances.get(effect.entity_id)
            if item is not None:
                effect_event_id = self._new_id("evt")
                revision = str(state.event_sequence + offset)
                items = deepcopy(state.item_instances)
                items[effect.entity_id] = item.model_copy(
                    update={
                        "state": item.state.model_copy(update={"status": "retired"}),
                        "version": item.version + 1,
                        "last_event_id": effect_event_id,
                        "updated_revision": revision,
                    }
                )
                state = state.model_copy(update={"item_instances": items}, deep=True)
            else:
                runtime_entities = deepcopy(state.runtime_entities)
                entity_states = deepcopy(state.entities)
                target = runtime_entities.get(effect.entity_id)
                if target is None:
                    target = entity_states.setdefault(effect.entity_id, {})
                target["consumed"] = True
                state = state.model_copy(
                    update={
                        "runtime_entities": runtime_entities,
                        "entities": entity_states,
                    },
                    deep=True,
                )
            event_type = "entity.consumed"
            payload = {"entity_id": effect.entity_id}
        elif isinstance(effect, AdvanceWorldTimeEffect):
            advanced = advanced_to_next(runtime.v3, state.world_time)
            state = state.model_copy(update={"world_time": advanced}, deep=True)
            event_type = "time.point_entered"
            payload = {
                "point_id": advanced.current_point_id,
                "day_index": advanced.current.day_index,
                "hour_of_day": advanced.current.hour_of_day,
                "time_of_day": advanced.time_of_day,
            }
        elif isinstance(effect, MarkCoreResolvedEffect):
            state = state.model_copy(update={"core_resolved": True}, deep=True)
            event_type = "core.resolved"
        elif isinstance(effect, SetEndingAvailabilityEffect):
            state = state.model_copy(
                update={"ending_available": effect.available}, deep=True
            )
            event_type = "ending.availability_changed"
            payload = {"available": effect.available}
        elif isinstance(effect, CommitTerminalEndingEffect):
            raise ContractError("终局不能由 Rule 效果直接提交，必须确认 EndingDraft")
        if event_type is None:
            raise ContractError("未注册的高层效果")
        return state, (
            self._event_from_state(
                state,
                room_id=room_id,
                offset=offset,
                request_id=request_id,
                actor_id=actor_id,
                event_type=event_type,
                payload=payload,
                event_id=effect_event_id,
            ),
        )

    @staticmethod
    def _run_view(check_run: CheckRun):
        from collaboration_framework.contracts import CheckRunView

        return CheckRunView(
            check_id=check_run.check_id,
            action_request_id=check_run.action_request_id,
            selected_candidate_id=check_run.selected_candidate_id,
            status=check_run.status,
            version=check_run.version,
            roll_count=check_run.roll_count,
            roll=check_run.roll,
            post_roll_options=check_run.post_roll_options,
            final_result=check_run.final_result,
        )

    def _event(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        offset: int,
        request_id: str,
        actor_id: str,
        event_type: str,
        payload: dict[str, JsonValue],
        visibility: str = "public",
    ) -> DomainEvent:
        return self._event_from_state(
            runtime.game_state,
            room_id=runtime.game_state.room_id,
            offset=offset,
            request_id=request_id,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            visibility=visibility,
        )

    def _event_from_state(
        self,
        state: GameState,
        *,
        room_id: str,
        offset: int,
        request_id: str,
        actor_id: str,
        event_type: str,
        payload: dict[str, JsonValue],
        visibility: str = "public",
        event_id: str | None = None,
    ) -> DomainEvent:
        return DomainEvent(
            event_id=event_id or self._new_id("evt"),
            sequence=state.event_sequence + offset,
            type=event_type,
            room_id=room_id,
            actor_id=actor_id,
            client_action_id=request_id,
            cause=f"adjudication:{request_id}",
            visibility=visibility,
            payload=payload,
        )

    @staticmethod
    def _validate_decision_owner(
        runtime: EngineRuntimeSnapshot,
        player_id: str,
        decision: PendingCheckDecision,
    ) -> None:
        if (
            decision.room_id != runtime.game_state.room_id
            or decision.player_id != player_id
        ):
            raise ContractError("PendingCheckDecision 不属于当前玩家或房间")
        AdjudicationEngineService._validate_identity(
            runtime,
            player_id=player_id,
            actor_id=decision.actor_id,
        )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"
