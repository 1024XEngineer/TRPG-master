"""Deterministic ModuleContent v3 single-intent ActionExecutor.

The service is deliberately separate from Host orchestration.  Tests and future
Agent adapters submit already-adjudicated commands; this module validates and
commits them without interpreting player language.
"""

from __future__ import annotations

import logging
from typing import Literal, NoReturn
from uuid import uuid4

from pydantic import JsonValue

from collaboration_framework.contracts import (
    AcceptResultOption,
    ActionAdjudication,
    ActionEffect,
    ActionTarget,
    AdjudicationExecution,
    AdjudicationRecovery,
    AdjudicationStatusView,
    AdvanceWorldTimeEffect,
    CheckDecisionRequest,
    ContractError,
    GetAdjudicationStatusRequest,
    NarrationEvidence,
    PendingCheckOption,
    PostRollDecisionRequest,
    PushOption,
    SpendResourceOption,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.adjudication import CheckDegree, CheckRoll
from collaboration_framework.contracts.validation import (
    AdjudicationValidationError,
    AuthorityLevel,
    ClassificationCoverage,
    EffectValidationDetail,
    Repairability,
    ValidationResult,
)
from collaboration_framework.registry import effects as effect_registry

from .dice import DiceRoller, coc7_success_level, passes_difficulty
from .models import (
    AgendaSource,
    CheckRun,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineRuntimeSnapshot,
    GameState,
    PendingCheckDecision,
)
from .navigation import resolve_location_target
from .persistent_results import (
    committed_results_from_events,
    is_public_standard_state,
    validate_persistent_effects,
)
from .ports import EngineStore
from .projection_v3 import project_v3
from .rules_v3 import (
    agenda_item_for_event,
    agenda_status_for_walk,
    agent_match_scope_admits,
    create_rule_agenda,
    effects_after_degree,
    entity_state,
    matching_event_rules,
    pending_check_for,
    resolve_rule_option,
    walk_rule,
)
from .timeline import advanced_to_next, next_point_after, time_advance_block_reason

logger = logging.getLogger(__name__)

# The engine logic `registry/effects.py` needs but may not import: it is a leaf
# so that `module` can read the same tables at publish time (#347, and
# docs/architecture.md §6 forbidding `module -> engine`).
_EFFECT_SERVICES = effect_registry.EffectServices(
    resolve_location_target=resolve_location_target,
    advanced_to_next=advanced_to_next,
    next_point_after=next_point_after,
    time_advance_block_reason=time_advance_block_reason,
    is_public_standard_state=is_public_standard_state,
)


def _target_kinds_matching(
    runtime: EngineRuntimeSnapshot,
    target_id: str,
) -> frozenset[str]:
    """`target_id` 在哪些 kind 的集合里存在。

    `ActionTarget.kind` 决定去哪个集合查 id，这里把五个集合全查一遍，供存在性
    校验和 kind 归一共用同一份定义。
    """

    state = runtime.game_state
    matches = {
        "information": target_id in runtime.canon_information_ids,
        "entity": target_id in runtime.canon_entity_ids
        or target_id in state.runtime_entities
        or target_id in state.item_instances,
        "location": target_id in runtime.canon_location_ids
        or target_id in state.runtime_locations,
        "actor": target_id in state.actors,
        "world": target_id == runtime.module_content.world_ref,
    }
    return frozenset(kind for kind, hit in matches.items() if hit)


def _normalize_target_kind(
    runtime: EngineRuntimeSnapshot,
    adjudication: ActionAdjudication,
) -> ActionAdjudication:
    """`kind` 填错但 `id` 唯一可辨时改写 `kind`，其余情况原样返回。

    模型经常把 NPC 写成 `kind="actor"`——`state.actors` 只有玩家角色，NPC 一律在
    entity 侧，于是整个回合以 `TARGET_NOT_FOUND` 失败，玩家原样重发又能过。引擎
    自己把这条拒绝标成 `auto_repairable` / `fault="agent"`，但答案本来就在引擎
    手里：`id` 已经唯一确定了对象，错的只是那个分类标签，不必再问模型一次。

    只在**恰好一个**其它 kind 命中时归一。零命中仍然拒绝；多个 kind 同时命中而
    `kind` 不在其中时也拒绝——跨集合撞名的归一是猜，不能猜。

    归一不放宽可见性边界：能碰到的对象集合与直接写对 `kind` 完全一致。
    """

    target = adjudication.target
    matched = _target_kinds_matching(runtime, target.id)
    if target.kind in matched or len(matched) != 1:
        return adjudication
    (resolved,) = matched
    logger.warning(
        "adjudication_target_kind_normalized",
        extra={
            "room_id": runtime.game_state.room_id,
            "target_id": target.id,
            "declared_kind": target.kind,
            "resolved_kind": resolved,
            "request_id": adjudication.request_id,
        },
    )
    return adjudication.model_copy(
        update={"target": ActionTarget(kind=resolved, id=target.id)}
    )


class AdjudicationEngineService:
    """B-owned executor for one ActionAdjudication per call."""

    def __init__(self, store: EngineStore, *, dice: DiceRoller | None = None) -> None:
        self._store = store
        self._dice = dice or DiceRoller()

    @staticmethod
    def _reject_validation(
        code: str,
        *,
        repairability: Repairability,
        fault: Literal["agent", "player", "engine"],
        player_safe_reason: str,
        internal_reason: str | None = None,
        classification_coverage: ClassificationCoverage = "partial_validation_failure",
    ) -> NoReturn:
        raise AdjudicationValidationError(
            ValidationResult(
                status="rejected",
                code=code,
                repairability=repairability,
                fault=fault,
                player_safe_reason=player_safe_reason,
                classification_coverage=classification_coverage,
                internal_reason=internal_reason,
            )
        )

    @staticmethod
    def _level_rank(level: AuthorityLevel) -> int:
        return int(level[1:])

    @classmethod
    def _max_level(cls, levels: tuple[AuthorityLevel, ...]) -> AuthorityLevel | None:
        return max(levels, key=cls._level_rank, default=None)

    @staticmethod
    def _accepted_validation(
        *,
        authority_level: AuthorityLevel | None,
        affected_effects: tuple[EffectValidationDetail, ...],
        classification_coverage: ClassificationCoverage = "complete",
    ) -> ValidationResult:
        return ValidationResult(
            status="accepted",
            authority_level=authority_level,
            code="OK",
            player_safe_reason="裁决已通过确定性校验",
            affected_effects=affected_effects,
            classification_coverage=classification_coverage,
        )

    @classmethod
    def _classify_effects(
        cls,
        runtime: EngineRuntimeSnapshot,
        effects: tuple[ActionEffect, ...],
        *,
        branch: Literal["success", "failure", "selected"],
        check_floor: bool = False,
    ) -> tuple[AuthorityLevel | None, tuple[EffectValidationDetail, ...]]:
        """Classify only Agent-owned effects; Rule-owned effects are explicit.

        The per-type authority rules live in `registry/effects.py` (#347); what
        stays here is the sequence walk and the detail record it builds.
        """

        details: list[EffectValidationDetail] = []
        levels: list[AuthorityLevel] = ["L3"] if check_floor else []
        classification = effect_registry.classification_context(runtime)

        for index, effect in enumerate(effects):
            level, target_ref = effect_registry.classify(effect, classification)
            levels.append(level)
            details.append(
                EffectValidationDetail(
                    branch=branch,
                    effect_index=index,
                    effect_type=effect.type,
                    authority_level=level,
                    target_ref=target_ref,
                )
            )
        return cls._max_level(tuple(levels)), tuple(details)

    def _build_submission_validation(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
    ) -> tuple[ValidationResult, AuthorityLevel | None]:
        if adjudication.rule_decision is not None and runtime.is_v3:
            success_level, success_details = self._classify_effects(
                runtime,
                adjudication.success_effects,
                branch="success",
                check_floor=adjudication.check.mode != "none",
            )
            failure_level, failure_details = self._classify_effects(
                runtime,
                adjudication.failure_effects,
                branch="failure",
                check_floor=adjudication.check.mode != "none",
            )
            authority_level = self._max_level(
                tuple(
                    level
                    for level in (success_level, failure_level)
                    if level is not None
                )
            )
            return (
                self._accepted_validation(
                    authority_level=authority_level,
                    affected_effects=success_details + failure_details,
                    classification_coverage="rule_effects_excluded",
                ),
                None,
            )

        if adjudication.check.mode == "none":
            authority_level, effects = self._classify_effects(
                runtime,
                adjudication.success_effects,
                branch="selected",
                check_floor=False,
            )
            return (
                self._accepted_validation(
                    authority_level=authority_level,
                    affected_effects=effects,
                ),
                authority_level,
            )

        success_level, success_details = self._classify_effects(
            runtime,
            adjudication.success_effects,
            branch="success",
            check_floor=True,
        )
        failure_level, failure_details = self._classify_effects(
            runtime,
            adjudication.failure_effects,
            branch="failure",
            check_floor=True,
        )
        authority_level = self._max_level(
            tuple(
                level for level in (success_level, failure_level) if level is not None
            )
        )
        return (
            self._accepted_validation(
                authority_level=authority_level,
                affected_effects=success_details + failure_details,
            ),
            None,
        )

    def _build_resolution_validation(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
        *,
        selected_effects: tuple[ActionEffect, ...],
        rule_effects_excluded: bool,
    ) -> tuple[ValidationResult, AuthorityLevel | None]:
        level, details = self._classify_effects(
            runtime,
            selected_effects,
            branch="selected",
            check_floor=adjudication.check.mode != "none",
        )
        coverage = "rule_effects_excluded" if rule_effects_excluded else "complete"
        return (
            self._accepted_validation(
                authority_level=level,
                affected_effects=details,
                classification_coverage=coverage,
            ),
            None if rule_effects_excluded else level,
        )

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
                created_at=command.created_at,
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
            # 归一要贯穿这次提交的余下部分——重放比对、规则范围匹配、效果校验和
            # 持久化用的都是 `request.adjudication`。
            #
            # 尤其**必须**排在重放比对之前：`_replay` 比的是整个 request，而落库的
            # 是归一后的那份；客户端重试原样重发未归一的报文（响应丢失时正是如此），
            # 放在比对之后会让每一条被本特性修好的请求反而丢掉幂等，报
            # REQUEST_ID_REUSED。
            request = request.model_copy(
                update={
                    "adjudication": _normalize_target_kind(
                        runtime,
                        request.adjudication,
                    )
                }
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
            proposal_validation, proposal_committed_level = (
                self._build_submission_validation(
                    runtime,
                    request.adjudication,
                )
            )

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
                    narration_evidence=self._narration_evidence(
                        runtime,
                        new_state=new_state,
                        events=events,
                        player_id=request.player_id,
                        actor_id=request.adjudication.actor_id,
                    ),
                    committed_results=committed_results_from_events(events),
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
                        validation=proposal_validation,
                        committed_authority_level=proposal_committed_level,
                        classification_coverage=proposal_validation.classification_coverage,
                    ),
                )
                return execution

            existing = await transaction.find_pending_check_by_action(
                request.adjudication.request_id
            )
            if existing is not None:
                self._reject_validation(
                    "DECISION_ALREADY_SETTLED",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="该行动已经存在待处理检定",
                )
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
                    validation=proposal_validation,
                    committed_authority_level=None,
                    classification_coverage=proposal_validation.classification_coverage,
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
                self._reject_validation(
                    "DECISION_ALREADY_SETTLED",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="该检定选择已经失效或完成",
                    internal_reason="该检定已完成选择，不能再次选择或取消",
                )
            self._validate_decision_owner(runtime, request.player_id, decision)
            if decision.status != "awaiting_skill_choice":
                self._reject_validation(
                    "DECISION_ALREADY_SETTLED",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="该检定选择已经失效或完成",
                    internal_reason="该检定已完成选择，不能再次选择或取消",
                )
            if decision.decision_version != request.decision_version:
                self._reject_validation(
                    "DECISION_VERSION_STALE",
                    repairability="retry_with_latest_revision",
                    fault="player",
                    player_safe_reason="检定选择已更新，请刷新后重试",
                )

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
                self._reject_validation(
                    "OPTION_NOT_IN_MENU",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="所选检定方式不在当前可用列表中",
                )
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
                selected_skill_name=option.display_name,
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
                narration_evidence=self._narration_evidence(
                    runtime,
                    new_state=new_state,
                    events=events,
                    player_id=decision.player_id,
                    actor_id=decision.actor_id,
                ),
                committed_results=committed_results_from_events(events),
            )
            rule_effects_excluded = (
                decision.adjudication.rule_decision is not None and runtime.is_v3
            )
            selected_effects = (
                ()
                if rule_effects_excluded
                else (
                    decision.adjudication.success_effects
                    if roll.passed
                    else decision.adjudication.failure_effects
                )
            )
            validation, committed_level = self._build_resolution_validation(
                runtime,
                decision.adjudication,
                selected_effects=selected_effects,
                rule_effects_excluded=rule_effects_excluded,
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
                    validation=validation,
                    committed_authority_level=committed_level,
                    classification_coverage=validation.classification_coverage,
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
                self._reject_validation(
                    "DECISION_ALREADY_SETTLED",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="该检定已经失效或完成",
                )
            self._validate_identity(
                runtime,
                player_id=request.player_id,
                actor_id=check_run.actor_id,
            )
            if check_run.status != "awaiting_post_roll_decision":
                self._reject_validation(
                    "DECISION_ALREADY_SETTLED",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="该检定已经失效或完成",
                )
            if check_run.version != request.check_version:
                self._reject_validation(
                    "DECISION_VERSION_STALE",
                    repairability="retry_with_latest_revision",
                    fault="player",
                    player_safe_reason="检定结果已更新，请刷新后重试",
                )
            option = next(
                (
                    item
                    for item in check_run.post_roll_options
                    if item.option_id == request.option_id
                ),
                None,
            )
            if option is None:
                self._reject_validation(
                    "OPTION_NOT_IN_MENU",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="所选处理方式不在当前可用列表中",
                )
            if isinstance(option, PushOption) != (
                request.push_adjudication is not None
            ):
                self._reject_validation(
                    "OPTION_NOT_IN_MENU",
                    repairability="hard_reject",
                    fault="player",
                    player_safe_reason="检定后处理参数与当前选项不一致",
                )

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
                self._reject_validation(
                    "EFFECT_NOT_REGISTERED",
                    repairability="hard_reject",
                    fault="engine",
                    player_safe_reason="规则引擎无法处理当前检定选项",
                )

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
                    "resolution_kind": (
                        "spend_luck"
                        if isinstance(option, SpendResourceOption)
                        else "push"
                        if isinstance(option, PushOption)
                        else "accept_result"
                    ),
                    "luck_spent": option.cost
                    if isinstance(option, SpendResourceOption)
                    else None,
                },
                deep=True,
            )
            decision = await transaction.load_pending_check(check_run.decision_id)
            if decision is None:
                self._reject_validation(
                    "EFFECT_NOT_REGISTERED",
                    repairability="hard_reject",
                    fault="engine",
                    player_safe_reason="规则引擎缺少当前检定的恢复状态",
                )
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
                narration_evidence=self._narration_evidence(
                    runtime_after_resource,
                    new_state=new_state,
                    events=events,
                    player_id=decision.player_id,
                    actor_id=decision.actor_id,
                ),
                committed_results=committed_results_from_events(events),
            )
            rule_effects_excluded = (
                check_run.adjudication.rule_decision is not None and runtime.is_v3
            )
            selected_effects = (
                ()
                if rule_effects_excluded
                else (
                    check_run.adjudication.success_effects
                    if final_roll.passed
                    else check_run.adjudication.failure_effects
                )
            )
            validation, committed_level = self._build_resolution_validation(
                runtime_after_resource,
                check_run.adjudication,
                selected_effects=selected_effects,
                rule_effects_excluded=rule_effects_excluded,
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
                    validation=validation,
                    committed_authority_level=committed_level,
                    classification_coverage=validation.classification_coverage,
                ),
            )
            return execution

    @staticmethod
    def _public_event_refs(events: tuple[DomainEvent, ...]) -> tuple[str, ...]:
        return tuple(event.event_id for event in events if event.visibility == "public")

    @staticmethod
    def _narration_evidence(
        runtime: EngineRuntimeSnapshot,
        *,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        player_id: str,
        actor_id: str,
    ) -> tuple[NarrationEvidence, ...]:
        """Project newly discovered entities through the final player-safe view."""

        if not runtime.is_v3:
            return ()
        candidate_events = tuple(
            event
            for event in events
            if (
                event.visibility == "public"
                and event.type == "entity.state_changed"
                and event.payload.get("key") == "discovered"
                and event.payload.get("value") is True
                and isinstance(event.payload.get("entity_id"), str)
                and entity_state(
                    runtime.game_state,
                    event.payload["entity_id"],
                ).get("discovered")
                is not True
            )
        )
        if not candidate_events:
            return ()
        final_runtime = runtime.model_copy(
            update={
                "game_state": new_state,
                "revision": str(new_state.event_sequence),
            },
            deep=True,
        )
        visible = {
            item.id: item
            for item in project_v3(
                final_runtime,
                player_id=player_id,
                actor_id=actor_id,
            ).scene.visible_entities
        }
        evidence: list[NarrationEvidence] = []
        for event in candidate_events:
            entity_id = event.payload.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            projected = visible.get(entity_id)
            if projected is None:
                continue
            evidence.append(
                NarrationEvidence(
                    ref=event.event_id,
                    kind="entity_discovered",
                    subject_id=projected.id,
                    subject_name=projected.name,
                    subject_aliases=projected.aliases,
                    description=projected.description,
                    required_in_narration=True,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _validate_identity(
        runtime: EngineRuntimeSnapshot,
        *,
        player_id: str,
        actor_id: str,
    ) -> None:
        actor = runtime.game_state.actors.get(actor_id)
        if actor is None or actor.player_id != player_id:
            AdjudicationEngineService._reject_validation(
                "IDENTITY_NOT_BOUND",
                repairability="hard_reject",
                fault="player",
                player_safe_reason="当前玩家不能控制该局内角色",
            )
        if runtime.game_state.phase != "playing":
            AdjudicationEngineService._reject_validation(
                "SESSION_ENDED",
                repairability="hard_reject",
                fault="player",
                player_safe_reason="游戏已经结束，不能提交新裁决",
            )

    @staticmethod
    def _require_revision(source: str, current: str) -> None:
        if source != current:
            AdjudicationEngineService._reject_validation(
                "SOURCE_REVISION_STALE",
                repairability="retry_with_latest_revision",
                fault="player",
                player_safe_reason="动作基于过期的玩家视图，请刷新后重试",
            )

    @staticmethod
    def _replay(request, completed, current_revision: str) -> AdjudicationExecution:
        if request != completed.request:
            AdjudicationEngineService._reject_validation(
                "REQUEST_ID_REUSED",
                repairability="hard_reject",
                fault="player",
                player_safe_reason="请求标识已经用于另一条裁决命令",
            )
        return completed.execution.model_copy(
            update={"view_revision": current_revision},
            deep=True,
        )

    def _validate_adjudication(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
    ) -> None:
        state = runtime.game_state
        target = adjudication.target
        if target.kind not in _target_kinds_matching(runtime, target.id):
            self._reject_validation(
                "TARGET_NOT_FOUND",
                repairability="auto_repairable",
                fault="agent",
                player_safe_reason="当前目标不可用于这次行动",
                internal_reason="ActionAdjudication target 引用了不存在或隐藏的对象",
            )
        if adjudication.rule_decision is not None:
            if not runtime.is_v3:
                self._reject_validation(
                    "RULE_OUT_OF_SCOPE",
                    # 规则真实存在，只是 Agent 绑定了错误的动作族或目标；允许使用
                    # 最新 PlayerView 重裁决一次，不应直接把内部错误抛给玩家。
                    repairability="auto_repairable",
                    fault="agent",
                    player_safe_reason="当前行动不能使用该规则选项",
                )
            # Refuses an id the module never declared, so a model cannot invent
            # a rule or reach a branch its option does not select.
            rule, _ = resolve_rule_option(
                runtime.v3,
                rule_id=adjudication.rule_decision.rule_id,
                option_id=adjudication.rule_decision.option_id,
            )
            # 存在性不等于「此时此地可用」。候选菜单是按当前场景发布的，提交时
            # 必须用同一个谓词重新绑定：否则模型可以点名另一个地点的规则，把它
            # 的后果带到这里来 —— 范围校验等于交给了模型自觉。
            if not agent_match_scope_admits(
                rule,
                location_id=state.scene_id,
                action_family=adjudication.method.family,
                target_kind=adjudication.target.kind,
                target_id=adjudication.target.id,
            ):
                # 可自动修复，不是死路。菜单是按「玩家站在哪」发布的，这里才
                # 第一次用上 method.family 和 target —— 也就是说模型看得到的
                # 候选，提交时完全可能不适用（#313：在 neighborhood 说「跟邻居
                # 打个招呼」，菜单里有 question_neighbors，但它只认
                # family=interview + target=lyla）。这是 fault="agent" 的错，
                # 而放弃 rule_decision 就能变回一次普通叙事裁决，没有任何理由
                # 让玩家的回合直接死在这里。
                self._reject_validation(
                    "RULE_OUT_OF_SCOPE",
                    repairability="auto_repairable",
                    fault="agent",
                    player_safe_reason="当前行动不能使用该规则选项",
                    internal_reason=(
                        "RuleDecision 超出当前可用范围: "
                        f"{adjudication.rule_decision.rule_id}"
                    ),
                )
        else:
            # 自由行动的完整性必须在创建待检定、掷骰或写入事件之前完成；规则路径
            # 的效果由模组拥有，因此仍允许模型 success_effects 为空。
            persistent_problem = validate_persistent_effects(adjudication)
            if persistent_problem is not None:
                self._reject_validation(
                    persistent_problem.code,
                    repairability="auto_repairable",
                    fault="agent",
                    player_safe_reason=persistent_problem.player_safe_reason,
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
        """Walk one atomic sequence, checking each effect against the ids in
        scope at that point.

        The linker-style two-pass resolution of #347 §4.3: the vocabulary starts
        as what the published module and current state already contain, and each
        accepted effect folds its `writes` in before the next one is checked.
        That is what makes "create the room, then walk into it" legal inside one
        adjudication while still refusing a reference to something nothing
        created.
        """

        vocabulary = effect_registry.ValidationVocabulary(
            information_ids=runtime.canon_information_ids,
            entity_ids=(
                runtime.canon_entity_ids
                | set(runtime.game_state.runtime_entities)
                | set(runtime.game_state.item_instances)
            ),
            location_ids=(
                runtime.canon_location_ids | set(runtime.game_state.runtime_locations)
            ),
            # ``holder_actor_id`` is inventory custody, not a generic entity
            # position.  Track real portable item instances separately from the
            # wider entity vocabulary so a Canon prop/NPC cannot acquire a
            # holder-only shadow state that PlayerView.inventory will never read.
            # A v3 runtime object becomes portable as soon as an earlier effect in
            # this same atomic sequence creates it.
            portable_item_ids=set(runtime.game_state.item_instances),
            actor_ids=set(runtime.game_state.actors),
            # Sleeping until 20:00 is several jumps in one adjudication, so each
            # one has to be checked against the clock the previous jump left
            # behind — not against the clock this action started on.
            world_time=runtime.game_state.world_time,
        )
        for effect in effects:
            self._validate_effect(runtime, effect, vocabulary=vocabulary)
            effect_registry.absorb_writes(effect, vocabulary, is_v3=runtime.is_v3)
            if isinstance(effect, AdvanceWorldTimeEffect):
                vocabulary.world_time = advanced_to_next(
                    runtime.v3, vocabulary.world_time
                )

    def _validated_options(
        self,
        runtime: EngineRuntimeSnapshot,
        adjudication: ActionAdjudication,
    ) -> tuple[PendingCheckOption, ...]:
        actor = runtime.game_state.actors[adjudication.actor_id]
        skills = actor.state.get("skills")
        labels = actor.state.get("skill_labels")
        if not isinstance(skills, dict):
            self._reject_validation(
                "SKILL_NOT_AVAILABLE",
                repairability="auto_repairable",
                fault="agent",
                player_safe_reason="当前角色没有可用于这次检定的能力",
            )
        # CoC7 的属性检定（搬开石板掷 STR、闪避掷 DEX）和技能检定用同一套 d100
        # 判定，但属性存在 `attributes` 而不是 `skills` 里。只查 skills 会让作者
        # 写好的 STR 检定在提交时被判成「技能不属于 Actor」——《追书人》搬石板
        # 那一步正是这样卡死的，而它是进入地穴的唯一门禁。
        attributes = actor.state.get("attributes")
        attribute_map = attributes if isinstance(attributes, dict) else {}
        attribute_labels = actor.state.get("attribute_labels")
        label_map = {
            **(attribute_labels if isinstance(attribute_labels, dict) else {}),
            **(labels if isinstance(labels, dict) else {}),
        }
        options: list[PendingCheckOption] = []
        for candidate in adjudication.check.candidates:
            value = skills.get(candidate.skill_id)
            if value is None:
                value = attribute_map.get(candidate.skill_id)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 100
            ):
                self._reject_validation(
                    "SKILL_NOT_AVAILABLE",
                    repairability="auto_repairable",
                    fault="agent",
                    player_safe_reason="当前角色没有可用于这次检定的能力",
                    internal_reason=(
                        f"技能候选不属于 Actor 或数值非法: {candidate.skill_id}"
                    ),
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
        vocabulary: effect_registry.ValidationVocabulary,
    ) -> None:
        """Refuse an ill-formed effect; the per-type rules live in the registry."""

        effect_registry.validate(effect, vocabulary, runtime, _EFFECT_SERVICES)

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
            AdjudicationEngineService._reject_validation(
                "RESOURCE_INSUFFICIENT",
                repairability="requires_player_choice",
                fault="player",
                player_safe_reason="当前资源不足，请选择其他处理方式",
            )
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
        if step is not None:
            if check_run is None:
                # 分支要求掷骰，裁决却没带检定：拒绝提交后果，而不是当作成功。
                return ()
            degree = (check_run.final_result or check_run.roll).degree
            return tuple(effects_after_degree(rule, step.id, degree))

        walk = walk_rule(rule, branch_id=branch_id)
        if walk.completed:
            # 这条分支不掷骰，整条链就是它的后果 —— 规则依然独占这些效果。
            #
            # 这里过去返回 ()，注释写的是「链在提交时已经跑过了」，但没有任何地方
            # 跑它：Agenda 只装 event 规则，agent_match 的决定只经过这里。于是纯
            # 效果规则被静默吞掉，《追书人》整条地穴终局都不产生任何后果。
            return tuple(walk.effects)

        # 既不是检定、也没走到终点：停在 invoke_ruleset_action、循环、未知步或
        # 预算耗尽上。这类分支要靠 RuleAgenda 恢复才能跑完，而恢复侧还没有生产
        # worker。只提交走过的那一半会把世界留在半截状态（例如昏迷没生效，却已经
        # 标记见过身影），比什么都不做更糟——所以明确拒绝，让它可见地失败。
        AdjudicationEngineService._reject_validation(
            "RULE_BUDGET_EXCEEDED",
            repairability="hard_reject",
            fault="engine",
            player_safe_reason="规则处理暂时无法完成",
            internal_reason=(
                f"Rule {rule.id} 的分支 {branch_id} 停在 {walk.suspended_kind} 上，"
                "当前没有可恢复的执行器，拒绝提交半截后果"
            ),
            classification_coverage="rule_effects_excluded",
        )

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
                    self._reject_validation(
                        "RULE_BUDGET_EXCEEDED",
                        repairability="hard_reject",
                        fault="engine",
                        player_safe_reason="规则处理暂时无法完成",
                    )
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
        """Execute one already-validated effect.

        The per-type state changes live in `registry/effects.py` (#347); what
        stays here is the flow skeleton — handing the handler its context and
        turning what it reports into a DomainEvent. A registration that declares
        `emits_event=False` (only `narrative_only` today) commits state without
        recording one.
        """

        result = effect_registry.apply(
            effect,
            effect_registry.ApplyContext(
                runtime=runtime,
                state=state,
                services=_EFFECT_SERVICES,
                room_id=room_id,
                request_id=request_id,
                actor_id=actor_id,
                offset=offset,
            ),
        )
        if result.event_type is None:
            return result.state, ()
        return result.state, (
            self._event_from_state(
                result.state,
                room_id=room_id,
                offset=offset,
                request_id=request_id,
                actor_id=actor_id,
                event_type=result.event_type,
                payload=result.payload,
                event_id=result.event_id,
            ),
        )

    @staticmethod
    def _run_view(check_run: CheckRun):
        from collaboration_framework.contracts import CheckRunView

        return CheckRunView(
            check_id=check_run.check_id,
            action_request_id=check_run.action_request_id,
            selected_candidate_id=check_run.selected_candidate_id,
            selected_skill_id=check_run.selected_skill_id,
            selected_skill_name=check_run.selected_skill_name,
            difficulty=check_run.difficulty,
            target_value=check_run.target_value,
            status=check_run.status,
            version=check_run.version,
            roll_count=check_run.roll_count,
            roll=check_run.roll,
            post_roll_options=check_run.post_roll_options,
            final_result=check_run.final_result,
            resolution_kind=check_run.resolution_kind,
            luck_spent=check_run.luck_spent,
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
            AdjudicationEngineService._reject_validation(
                "IDENTITY_NOT_BOUND",
                repairability="hard_reject",
                fault="player",
                player_safe_reason="当前玩家不能处理该检定",
            )
        AdjudicationEngineService._validate_identity(
            runtime,
            player_id=player_id,
            actor_id=decision.actor_id,
        )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"
