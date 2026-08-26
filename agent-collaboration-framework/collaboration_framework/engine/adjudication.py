"""Deterministic ModuleContent v3 single-intent ActionExecutor.

The service is deliberately separate from Host orchestration.  Tests and future
Agent adapters submit already-adjudicated commands; this module validates and
commits them without interpreting player language.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    CheckRunView,
    CheckStep,
    ContractError,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    NarrationEvidence,
    PendingCheckOption,
    PostRollDecisionRequest,
    PushOption,
    RuleCheckSpec,
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
from collaboration_framework.registry import check_profiles as check_profile_registry
from collaboration_framework.registry import effects as effect_registry

from .agenda_execution import RuleSettlement, SettlementResult
from .dice import DiceRoller, coc7_success_level, passes_difficulty
from .models import (
    AgendaParentContinuation,
    AgendaSource,
    CheckRun,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineRuntimeSnapshot,
    GameState,
    PendingCheckDecision,
    RuleCheckOrigin,
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
    agent_match_admits,
    create_rule_agenda,
    effects_after_degree,
    entity_state,
    pending_check_for,
    resolve_rule_option,
    walk_rule,
)
from .time_tasks import active_occurrences, settle_due_tasks
from .timeline import advanced_to_next, next_point_after, time_advance_block_reason

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionFinalization:
    """一次动作提交完效果、结算完规则之后的全部产物。

    在 #398 之前这里是一个 `(state, events)` 二元组。规则链现在有三种收场
    ——跑完、失败、挂在一次被动检定上——每一种调用方都要区别对待，元组已经
    表达不下了。
    """

    state: GameState
    events: tuple[DomainEvent, ...]
    agenda_failure_code: str | None = None
    # 非空即：规则要求一次检定，这次动作到此暂停，等玩家掷完骰再从同一个
    # Agenda 恢复。
    pending_decision: PendingCheckDecision | None = None


class _SettlementRunner:
    """Hands `RuleSettlement` the three Engine capabilities it needs.

    The settler owns *when* a rule's effects run; the service still owns *how*.
    Binding room/request/actor once here keeps the settler's call sites free of
    arguments that never vary within one action.
    """

    def __init__(
        self,
        service: AdjudicationEngineService,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        actor_id: str,
    ) -> None:
        self._service = service
        self._room_id = runtime.game_state.room_id
        self._request_id = request_id
        self._actor_id = actor_id

    def validate_effects(
        self,
        runtime: EngineRuntimeSnapshot,
        effects: tuple[ActionEffect, ...],
    ) -> None:
        self._service._validate_effect_sequence(runtime, effects)

    def apply_effect(
        self,
        runtime: EngineRuntimeSnapshot,
        state: GameState,
        effect: ActionEffect,
        *,
        offset: int,
    ) -> tuple[GameState, tuple[DomainEvent, ...]]:
        return self._service._apply_effect(
            runtime,
            state,
            effect,
            room_id=self._room_id,
            request_id=self._request_id,
            actor_id=self._actor_id,
            offset=offset,
        )

    def emit_event(
        self,
        state: GameState,
        *,
        offset: int,
        event_type: str,
        payload: dict,
        visibility: str = "public",
    ) -> DomainEvent:
        return self._service._event_from_state(
            state,
            room_id=self._room_id,
            offset=offset,
            request_id=self._request_id,
            actor_id=self._actor_id,
            event_type=event_type,
            payload=payload,
            visibility=visibility,
        )


# The engine logic `registry/effects.py` needs but may not import: it is a leaf
# so that `module` can read the same tables at publish time (#347, and
# docs/architecture.md §6 forbidding `module -> engine`).
_EFFECT_SERVICES = effect_registry.EffectServices(
    resolve_location_target=resolve_location_target,
    advanced_to_next=advanced_to_next,
    next_point_after=next_point_after,
    active_occurrences=active_occurrences,
    settle_due_tasks=settle_due_tasks,
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


def _target_persistent_capability(
    runtime: EngineRuntimeSnapshot,
    target_id: str,
) -> tuple[str | None, frozenset[str] | None]:
    """返回目标的真实类型及模组声明的可写状态键。

    该能力快照只在 Host 处理持久结果拒绝时使用；不把隐藏状态投影给模型，
    也不替模型决定最终效果。运行时临时实体没有预声明状态键，视为不可写。
    """

    for entity in runtime.module_content.entities:
        if entity.id == target_id:
            return entity.kind, frozenset(entity.state)
    if target_id in runtime.game_state.runtime_entities:
        payload = runtime.game_state.runtime_entities[target_id]
        kind = payload.get("kind")
        return (kind if kind in {"npc", "object"} else "object"), frozenset()
    if target_id in runtime.game_state.item_instances:
        return "object", frozenset()
    if target_id in runtime.game_state.actors:
        return "actor", frozenset(runtime.game_state.actors[target_id].state)
    if target_id in runtime.canon_location_ids or target_id in runtime.game_state.runtime_locations:
        return "location", None
    if target_id in runtime.canon_information_ids:
        return "information", None
    return None, None


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
        generic_fallback_allowed: bool = False,
    ) -> NoReturn:
        raise AdjudicationValidationError(
            ValidationResult(
                status="rejected",
                code=code,
                repairability=repairability,
                fault=fault,
                player_safe_reason=player_safe_reason,
                generic_fallback_allowed=generic_fallback_allowed,
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
        if adjudication.rule_decision is not None:
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

    async def load_action_adjudication(
        self,
        *,
        room_id: str,
        action_request_id: str,
    ) -> ActionAdjudication | None:
        """Return the frozen ActionAdjudication for one action, if it still exists."""

        async with self._store.transaction(room_id) as transaction:
            pending = await transaction.find_pending_check_by_action(action_request_id)
            if pending is not None:
                return pending.adjudication
            command = await transaction.find_latest_adjudication_command_by_action(
                action_request_id
            )
            if command is None:
                return None
            if isinstance(command.request, SubmitAdjudicationRequest):
                return command.request.adjudication
            return None

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
        """提交普通裁决；多人共享时间仍必须先经过应用层全员确认。"""

        return await self._submit(request, consent_player_ids=None)

    async def submit_with_time_consent(
        self,
        request: SubmitAdjudicationRequest,
        *,
        consent_player_ids: tuple[str, ...],
    ) -> AdjudicationExecution:
        """在应用层已冻结并收集全员同意后提交原裁决。

        Engine 会再次对比当前 Actor 对应的玩家集合，防止成员变化后复用
        旧授权。该入口不对 Agent 或客户端暴露。
        """

        return await self._submit(
            request,
            consent_player_ids=tuple(sorted(consent_player_ids)),
            scene_consent_player_ids=None,
        )

    async def submit_with_scene_consent(
        self,
        request: SubmitAdjudicationRequest,
        *,
        consent_player_ids: tuple[str, ...],
    ) -> AdjudicationExecution:
        """在应用层已冻结并收集全员同意后提交场景切换裁决。"""

        return await self._submit(
            request,
            consent_player_ids=None,
            scene_consent_player_ids=tuple(sorted(consent_player_ids)),
        )

    async def _submit(
        self,
        request: SubmitAdjudicationRequest,
        *,
        consent_player_ids: tuple[str, ...] | None,
        scene_consent_player_ids: tuple[str, ...] | None = None,
    ) -> AdjudicationExecution:
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
            allow_party_time_advance = False
            allow_party_scene_transition = False
            if consent_player_ids is not None:
                current_players = tuple(
                    sorted({actor.player_id for actor in runtime.game_state.actors.values()})
                )
                if consent_player_ids != current_players or len(current_players) <= 1:
                    self._reject_validation(
                        "TIME_CONSENT_STALE",
                        repairability="requires_player_choice",
                        fault="player",
                        player_safe_reason="房间成员已变化，需要重新确认时间推进",
                    )
                allow_party_time_advance = True
            if scene_consent_player_ids is not None:
                current_players = tuple(
                    sorted({actor.player_id for actor in runtime.game_state.actors.values()})
                )
                if scene_consent_player_ids != current_players or len(current_players) <= 1:
                    self._reject_validation(
                        "SCENE_CONSENT_STALE",
                        repairability="requires_player_choice",
                        fault="player",
                        player_safe_reason="房间成员已变化，需要重新确认场景切换",
                    )
                allow_party_scene_transition = True
            self._validate_adjudication(
                runtime,
                request.adjudication,
                allow_party_time_advance=allow_party_time_advance,
                # 带检定的 EnterLocation 此时还不会落世界：先过检定，再由应用层开确认。
                allow_party_scene_transition=(
                    allow_party_scene_transition
                    or request.adjudication.check.mode != "none"
                ),
            )
            proposal_validation, proposal_committed_level = (
                self._build_submission_validation(
                    runtime,
                    request.adjudication,
                )
            )

            if request.adjudication.check.mode == "none":
                final = self._finalize_action(
                    runtime,
                    request_id=request.adjudication.request_id,
                    adjudication=request.adjudication,
                    passed=True,
                    player_id=request.player_id,
                    prefix_events=(),
                    allow_party_scene_transition=allow_party_scene_transition,
                )
                new_state, events = final.state, final.events
                execution = self._execution_for(
                    runtime,
                    final,
                    request_id=request.adjudication.request_id,
                    action_request_id=request.adjudication.request_id,
                    outcome="success",
                    player_id=request.player_id,
                    actor_id=request.adjudication.actor_id,
                )
                await transaction.commit_adjudication(
                    expected_revision=runtime.revision,
                    new_state=new_state,
                    events=events,
                    decision=final.pending_decision,
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
                if not decision.allow_cancel:
                    # 规则强制的检定没有取消路由：`CheckStep` 不像
                    # `AdjudicatedCheckStep` 那样带 `cancel_step_id`，取消它就是
                    # 把 Agenda 永久卡在这里（#398 §阶段三）。
                    self._reject_validation(
                        "CHECK_NOT_CANCELLABLE",
                        repairability="requires_player_choice",
                        fault="player",
                        player_safe_reason="这次检定由规则强制，必须先完成",
                    )
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
            rule_check = self._rule_check_spec(runtime, decision)
            post_options = self._post_roll_options(
                runtime,
                actor_id=decision.actor_id,
                option=option,
                roll=roll,
                allow_push=rule_check is None or rule_check.allow_push is not False,
                allow_luck=rule_check is None or rule_check.allow_luck is not False,
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
            final = self._settle_check(
                runtime,
                request_id=request.request_id,
                decision=decision,
                check_run=check_run,
                passed=roll.passed,
                prefix_events=(rolled_event,),
            )
            new_state, events = final.state, final.events
            execution = self._execution_for(
                runtime,
                final,
                request_id=request.request_id,
                action_request_id=decision.action_request_id,
                outcome="success" if roll.passed else "failure",
                player_id=decision.player_id,
                actor_id=decision.actor_id,
                check_run=self._run_view(check_run),
            )
            rule_effects_excluded = decision.adjudication.rule_decision is not None
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
                additional_decisions=(
                    () if final.pending_decision is None else (final.pending_decision,)
                ),
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
            final = self._settle_check(
                runtime_after_resource,
                request_id=request.request_id,
                decision=decision,
                check_run=resolved_run,
                passed=final_roll.passed,
                prefix_events=tuple(prefix),
            )
            new_state, events = final.state, final.events
            execution = self._execution_for(
                runtime_after_resource,
                final,
                request_id=request.request_id,
                action_request_id=check_run.action_request_id,
                outcome="success" if final_roll.passed else "failure",
                player_id=decision.player_id,
                actor_id=decision.actor_id,
                check_run=self._run_view(resolved_run),
            )
            rule_effects_excluded = check_run.adjudication.rule_decision is not None
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
                additional_decisions=(
                    () if final.pending_decision is None else (final.pending_decision,)
                ),
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

    def _execution_for(
        self,
        runtime: EngineRuntimeSnapshot,
        final: ActionFinalization,
        *,
        request_id: str,
        action_request_id: str,
        outcome: str,
        player_id: str,
        actor_id: str,
        check_run: CheckRunView | None = None,
    ) -> AdjudicationExecution:
        """把一次结算的产物投影成 execution，三条提交路径共用。

        规则要求了检定时，这次动作还没结束——状态复用既有的
        `awaiting_skill_choice`，玩家看到的是同一个检定面板。已经提交的效果照常
        进 evidence 与 committed_results：它们是真的发生了，只是行动还没走完。
        """

        common = {
            "request_id": request_id,
            "action_request_id": action_request_id,
            "view_revision": str(final.state.event_sequence),
            "event_refs": tuple(event.event_id for event in final.events),
            "public_event_refs": self._public_event_refs(final.events),
            "narration_evidence": self._narration_evidence(
                runtime,
                new_state=final.state,
                events=final.events,
                player_id=player_id,
                actor_id=actor_id,
            ),
            "committed_results": committed_results_from_events(final.events),
        }
        if final.pending_decision is not None:
            return AdjudicationExecution(
                **common,
                status="awaiting_skill_choice",
                outcome="pending",
                pending_decision=final.pending_decision.player_view(),
                # 规则可以在玩家自己那次掷骰刚结算完之后马上再要一次检定。丢掉
                # `check_run` 的话 `ws.py::_emit_check_result` 会直接短路：不发
                # `check.result`、不落 `events`，replay 与 recent-history 里都没有
                # 这一掷。玩家看到的是一个新骰子面板，而刚才那次掷骰不存在。
                check_run=check_run,
            )
        return AdjudicationExecution(
            **common,
            status=self._settled_status(final.agenda_failure_code),
            rule_failure_code=final.agenda_failure_code,
            outcome=outcome,
            check_run=check_run,
        )

    @staticmethod
    def _settled_status(agenda_failure_code: str | None) -> str:
        """`resolved`，除非这次动作触发的规则链没能跑完。

        两者都是终态、都已提交效果；区别只是后者必须把「规则链停在哪」说出来，
        而不是像 #398 之前那样静默返回 `resolved`。
        """

        return "resolved" if agenda_failure_code is None else "rule_failed"

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
        *,
        allow_party_time_advance: bool = False,
        allow_party_scene_transition: bool = False,
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
            # Refuses an id the module never declared, so a model cannot invent
            # a rule or reach a branch its option does not select.
            rule, _ = resolve_rule_option(
                runtime.module_content,
                rule_id=adjudication.rule_decision.rule_id,
                option_id=adjudication.rule_decision.option_id,
            )
            # 存在性不等于「此时此地可用」。候选菜单是按当前场景发布的，提交时
            # 必须用同一个谓词重新绑定：否则模型可以点名另一个地点的规则，把它
            # 的后果带到这里来。action_family 是开放词表，仅作语义参考，不参与
            # 这里的硬拒绝；地点、目标类型、目标 ID 和 when 才是权威范围。
            if not agent_match_admits(
                rule,
                state=state,
                actor_id=adjudication.actor_id,
                location_id=state.scene_id,
                action_family=adjudication.method.family,
                target_kind=adjudication.target.kind,
                target_id=adjudication.target.id,
            ):
                # 可自动修复，不是死路。target 或结构范围不匹配时，
                # 放弃 rule_decision 就能变回一次普通叙事裁决；单纯的 family
                # 词汇差异不会进入此分支（#453）。
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
            target_kind, target_state_keys = _target_persistent_capability(
                runtime,
                adjudication.target.id,
            )
            persistent_problem = validate_persistent_effects(
                adjudication,
                target_kind=target_kind,
                target_state_keys=target_state_keys,
            )
            if persistent_problem is not None:
                if persistent_problem.allow_generic_fallback:
                    # 只记录可降级候选；原始裁决仍然拒绝，最终是否收窄由 Host
                    # 的语义保持检查决定，Engine 不替模型改写意图。
                    logger.info(
                        "persistent_effect_generic_fallback_candidate",
                        extra={
                            "target_kind": target_kind,
                            "persistence_intent": adjudication.persistence_intent,
                        },
                    )
                self._reject_validation(
                    persistent_problem.code,
                    repairability="auto_repairable",
                    fault="agent",
                    player_safe_reason=persistent_problem.player_safe_reason,
                    generic_fallback_allowed=persistent_problem.allow_generic_fallback,
                )
        self._validate_effect_sequence(
            runtime,
            adjudication.success_effects,
            allow_party_time_advance=allow_party_time_advance,
            allow_party_scene_transition=allow_party_scene_transition,
        )
        self._validate_effect_sequence(
            runtime,
            adjudication.failure_effects,
            allow_party_time_advance=allow_party_time_advance,
            allow_party_scene_transition=allow_party_scene_transition,
        )
        if adjudication.check.mode != "none":
            self._validated_options(runtime, adjudication)

    def _validate_effect_sequence(
        self,
        runtime: EngineRuntimeSnapshot,
        effects: tuple[ActionEffect, ...],
        *,
        allow_party_time_advance: bool = False,
        allow_party_scene_transition: bool = False,
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
            allow_party_time_advance=allow_party_time_advance,
            allow_party_scene_transition=allow_party_scene_transition,
        )
        for effect in effects:
            self._validate_effect(runtime, effect, vocabulary=vocabulary)
            effect_registry.absorb_writes(effect, vocabulary)
            if isinstance(effect, AdvanceWorldTimeEffect):
                vocabulary.world_time = advanced_to_next(
                    runtime.module_content,
                    vocabulary.world_time,
                    active_occurrences(runtime.game_state),
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
            # CoC7 幸运是 ActorResources 上会消耗、会持久化的权威资源，不是
            # skills/attributes 中的一项。作者态主动规则仍用统一的
            # SkillCheckCandidate 形状表达它；只在解析目标值时接回资源，避免
            # 《追书人》的幸运检定被误判成角色没有这个“技能”。
            if value is None and candidate.skill_id == "luck":
                value = actor.resources.luck
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
            label = (
                "幸运"
                if candidate.skill_id == "luck"
                else label_map.get(candidate.skill_id)
            )
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
        allow_push: bool = True,
        allow_luck: bool = True,
    ) -> tuple[AcceptResultOption | SpendResourceOption | PushOption, ...]:
        """奖惩骰菜单。`allow_push` / `allow_luck` 只有规则拥有的检定才会传。

        `RuleCheckSpec` 一直带着这两个字段，但在 #398 之前零消费者——被动检定
        根本还没接通，所以一条规则说不出「这次不许 push」。两个字段默认 None，
        调用方译成 True，所以现有内容行为不变。
        """

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
            allow_luck
            and roll.degree != "fumble"
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
        if allow_push:
            options.append(
                PushOption(
                    option_id="push-once",
                    player_safe_risk_summary="再次尝试会承担更严重的失败后果",
                )
            )
        return tuple(options)

    @staticmethod
    def _rule_check_spec(
        runtime: EngineRuntimeSnapshot,
        decision: PendingCheckDecision,
    ) -> RuleCheckSpec | None:
        """规则拥有的检定回它的 spec；玩家自己发起的检定回 None。

        `rule_origin` 非空即「这是规则拥有的检定」，游标足够把 `CheckStep` 找回
        来——`_resume_rule_check` 做的是同一件事。`PendingCheckOption` 只带得动
        技能与目标值，带不动出处，所以在调用点解析而不是塞进 option。
        """

        origin = decision.rule_origin
        if origin is None:
            return None
        rule = next(
            (item for item in runtime.module_content.rules if item.id == origin.rule_id),
            None,
        )
        if rule is None:
            return None
        step = next(
            (item for item in rule.execution.steps if item.id == origin.step_id),
            None,
        )
        return step.check if isinstance(step, CheckStep) else None

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
        if decision is None:
            return (
                adjudication.success_effects if passed else adjudication.failure_effects
            )
        rule, branch_id = resolve_rule_option(
            runtime.module_content,
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
        player_id: str,
        prefix_events: tuple[DomainEvent, ...],
        check_run: CheckRun | None = None,
        allow_party_scene_transition: bool = False,
    ) -> ActionFinalization:
        """Commit this action's effects and settle the Rules they triggered.

        The effects no longer all run first. Each one commits, its events are
        settled against the world *as it is at that moment*, and only a stable
        Rule chain lets the next effect run (#398 §阶段二). An action can
        therefore end suspended, with the rest of its effects parked on the
        Agenda as a continuation.
        """

        state = runtime.game_state.model_copy(deep=True)
        events = list(prefix_events)
        if check_run is not None:
            events.append(
                self._check_resolved_event(
                    state,
                    runtime=runtime,
                    request_id=request_id,
                    actor_id=adjudication.actor_id,
                    check_run=check_run,
                    passed=passed,
                    offset=len(events) + 1,
                )
            )
        selected_effects = self._owned_effects(
            runtime,
            adjudication=adjudication,
            passed=passed,
            check_run=check_run,
        )
        if not allow_party_scene_transition and len(runtime.game_state.actors) > 1:
            selected_effects = tuple(
                effect
                for effect in selected_effects
                if not isinstance(effect, EnterLocationEffect)
            )
        settlement = self._new_settlement(
            runtime, request_id=request_id, actor_id=adjudication.actor_id
        )
        continuation = AgendaParentContinuation(
            passed=passed,
            remaining_effects=selected_effects,
        )
        return self._drive_continuation(
            runtime,
            settlement=settlement,
            state=state,
            events=events,
            continuation=continuation,
            request_id=request_id,
            adjudication=adjudication,
            player_id=player_id,
            result=None,
        )

    def _settle_check(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        request_id: str,
        decision: PendingCheckDecision,
        check_run: CheckRun,
        passed: bool,
        prefix_events: tuple[DomainEvent, ...],
    ) -> ActionFinalization:
        """检定结算完之后走哪条路，取决于这次检定是谁的。

        玩家自己的行动检定：提交 Agent 裁决好的 success/failure 效果。
        规则拥有的被动检定：回到挂起的 Agenda，按 `result_routes` 走它的分支，
        Agent 不再参与后果裁决（#226 §5）。
        """

        if decision.rule_origin is not None:
            return self._resume_rule_check(
                runtime,
                request_id=request_id,
                decision=decision,
                check_run=check_run,
                passed=passed,
                prefix_events=prefix_events,
            )
        return self._finalize_action(
            runtime,
            request_id=request_id,
            adjudication=decision.adjudication,
            passed=passed,
            player_id=decision.player_id,
            prefix_events=prefix_events,
            check_run=check_run,
        )

    def _resume_rule_check(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        request_id: str,
        decision: PendingCheckDecision,
        check_run: CheckRun,
        passed: bool,
        prefix_events: tuple[DomainEvent, ...],
    ) -> ActionFinalization:
        """检定结算完，从**同一个 Agenda** 的 `result_routes` 分支接着走。

        这是被动检定与主动检定最本质的差别：主动检定结算的是 Agent 裁决好的
        success/failure 效果；被动检定结算的是规则自己的分支，Agent 不再参与
        后果裁决（#226 §5）。
        """

        origin = decision.rule_origin
        assert origin is not None
        state = runtime.game_state.model_copy(deep=True)
        events = [
            *prefix_events,
            self._check_resolved_event(
                state,
                runtime=runtime,
                request_id=request_id,
                actor_id=decision.actor_id,
                check_run=check_run,
                passed=passed,
                offset=len(prefix_events) + 1,
            ),
        ]
        agenda = state.rule_agendas.get(origin.agenda_id)
        rule = next(
            (
                item
                for item in runtime.module_content.rules
                if item.id == origin.rule_id
            ),
            None,
        )
        step = (
            next(
                (item for item in rule.execution.steps if item.id == origin.step_id),
                None,
            )
            if rule is not None
            else None
        )
        if agenda is None or rule is None or not isinstance(step, CheckStep):
            # 游标指向的东西不在了——模组被换版、或者 Agenda 已被别的路径收掉。
            # 半截恢复比显式失败更糟，所以这里直接拒绝。
            self._reject_validation(
                "RULE_AGENDA_UNRESUMABLE",
                repairability="hard_reject",
                fault="engine",
                player_safe_reason="规则处理暂时无法完成",
                internal_reason=(
                    f"Agenda {origin.agenda_id} 的游标 "
                    f"{origin.rule_id}/{origin.step_id} 无法恢复"
                ),
                classification_coverage="rule_effects_excluded",
            )
        settlement = RuleSettlement(
            agenda=agenda,
            runtime=runtime,
            actor_id=decision.actor_id,
            runner=_SettlementRunner(self, runtime, request_id, decision.actor_id),
            queue=list(agenda.queue),
            source_event_ids=list(agenda.source_event_ids),
            carried=list(agenda.carried_events),
            suspended=True,
        )
        degree = (check_run.final_result or check_run.roll).degree
        result = settlement.resume_rule(
            rule, step.result_routes.get(degree), state, events
        )
        continuation = agenda.parent_continuation or AgendaParentContinuation(
            passed=passed,
            completion_emitted=True,
        )
        return self._drive_continuation(
            runtime,
            settlement=settlement,
            state=result.state,
            events=events,
            continuation=continuation,
            request_id=request_id,
            adjudication=decision.adjudication,
            player_id=decision.player_id,
            result=result,
        )

    def _drive_continuation(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        settlement: RuleSettlement,
        state: GameState,
        events: list[DomainEvent],
        continuation: AgendaParentContinuation,
        request_id: str,
        adjudication: ActionAdjudication,
        player_id: str,
        result: SettlementResult | None,
    ) -> ActionFinalization:
        """跑完父动作还欠的那部分，再把 Agenda 封存。

        首次提交和检定恢复走的是同一条路：区别只在于进来时 continuation 里还剩
        多少效果、完成事件发过没有。
        """

        actor_id = adjudication.actor_id
        remaining = continuation.remaining_effects
        completion_emitted = continuation.completion_emitted
        if result is None or not result.blocked:
            state, result, remaining = self._drive_with_barrier(
                settlement,
                state,
                events,
                remaining,
                runtime=runtime,
                request_id=request_id,
                actor_id=actor_id,
            )
        if not result.blocked and not completion_emitted:
            state, result = self._complete_parent_action(
                settlement,
                state,
                events,
                runtime=runtime,
                request_id=request_id,
                adjudication=adjudication,
                passed=continuation.passed,
            )
            completion_emitted = True

        pending_decision: PendingCheckDecision | None = None
        if result.status == "suspended":
            # 规则链还没稳定，父动作剩下的效果不能就这么丢掉，也不能抢在规则
            # 前面跑完——存进 Agenda，等恢复时接着来（#398 §阶段二）。
            settlement.agenda = settlement.agenda.model_copy(
                update={
                    "parent_continuation": continuation.model_copy(
                        update={
                            "remaining_effects": remaining,
                            "completion_emitted": completion_emitted,
                        }
                    )
                }
            )
            pending_decision = self._passive_check_decision(
                runtime,
                settlement=settlement,
                state=state,
                adjudication=adjudication,
                player_id=player_id,
            )
            if pending_decision is None:
                # 挂起点没能变成一个真的能掷的检定——`_passive_check_decision`
                # 已经把 Agenda 打成 failed 了，重新取一次结果走下面的终态分支。
                result = settlement.result(state)

        unsettled_effects = 0
        if result.status == "failed":
            # 规则链失败是规则侧的问题，不构成对玩家动作的否决。#398 的零回归
            # 要求写得很直白：「新增执行屏障不得改变无阻塞动作的既有结果」——
            # 屏障管的是结算时机，不是否决权。屏障之前这些效果本来就会全部执行。
            #
            # 在此之前它们被静默丢弃，而 execution 照样报 outcome=success，
            # ActionPlan 于是踩着一个只做了一半的世界继续往下走。
            #
            # Agenda 已是终态，`advance()` 不会再前进，所以这些效果不再参与规则
            # 结算——数量写进审计事件，不当作没发生过。
            state, unsettled_effects = self._apply_effects_unsettled(
                state,
                events,
                remaining,
                runtime=runtime,
                request_id=request_id,
                actor_id=actor_id,
            )
            remaining = ()
            if not completion_emitted:
                events.append(
                    self._completion_event(
                        state,
                        runtime=runtime,
                        request_id=request_id,
                        adjudication=adjudication,
                        passed=continuation.passed,
                        offset=len(events) + 1,
                    )
                )
                completion_emitted = True

        state, agenda_failure_code = settlement.finish(
            state, events, unsettled_effects=unsettled_effects
        )
        state = state.model_copy(
            update={"event_sequence": runtime.game_state.event_sequence + len(events)},
            deep=True,
        )
        return ActionFinalization(
            state=state,
            events=tuple(events),
            agenda_failure_code=agenda_failure_code,
            pending_decision=pending_decision,
        )

    def _check_resolved_event(
        self,
        state: GameState,
        *,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        actor_id: str,
        check_run: CheckRun,
        passed: bool,
        offset: int,
    ) -> DomainEvent:
        return self._event_from_state(
            state,
            room_id=runtime.game_state.room_id,
            offset=offset,
            request_id=request_id,
            actor_id=actor_id,
            event_type="check.resolved",
            payload={
                "check_id": check_run.check_id,
                "action_request_id": check_run.action_request_id,
                "passed": passed,
                "degree": (check_run.final_result or check_run.roll).degree,
            },
        )

    def _passive_check_decision(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        settlement: RuleSettlement,
        state: GameState,
        adjudication: ActionAdjudication,
        player_id: str,
    ) -> PendingCheckDecision | None:
        """把 `CheckStep(initiation_kind="passive_rule")` 接到既有检定工作流上。

        在 #398 之前，Agenda 挂到 `awaiting_passive_check` 上就没了下文——这个
        状态在 `trpg-backend/app` 与 `collaboration_framework/host` 下 grep 零
        命中。表现是规则在检定前的效果照常提交、**检定本身静默丢失**：世界推进
        了，骰子没出现。

        被动检定与主动检定的差别只有两处，其余整条链路（PendingCheckDecision →
        CheckRun → WebSocket → CheckWorkflowPanel）原样复用：

        * `options` 只有一条，由规则的 check spec 写死，Agent 不再选技能；
        * `allow_cancel=False`——`CheckStep` 不像 `AdjudicatedCheckStep` 那样带
          `cancel_step_id`，规则强制的检定没有取消路由。
        """

        agenda = settlement.agenda
        if agenda.status != "awaiting_passive_check":
            # 事件规则挂在了别的边界上。`awaiting_active_check` /
            # `awaiting_presentation` / `awaiting_player_input` 都没有任何东西
            # 会推进（#405 已把后两者从登记表层面改成直接 failed，这里兜住剩下
            # 的一种）。直接 return None 的话 `agenda_failure_code` 是空的，
            # execution 报 resolved，而一个永远不会动的 Agenda 留在库里——正是
            # #398 §目标 5 要消灭的静默挂死。
            #
            # 事件规则走不到这里是有依据的：两个线上模组的 26 处 active check
            # 与唯一一处 adjudicated_check 全在 agent_match 规则里，而
            # `matching_event_rules` 只筛 EventTriggerSpec。
            settlement.fail(f"rule_boundary_unsupported:{agenda.status}")
            return None
        rule = next(
            (
                item
                for item in runtime.module_content.rules
                if item.id == agenda.current_rule_id
            ),
            None,
        )
        step = (
            next(
                (
                    item
                    for item in rule.execution.steps
                    if item.id == agenda.current_step_id
                ),
                None,
            )
            if rule is not None
            else None
        )
        if rule is None or not isinstance(step, CheckStep):
            settlement.fail("passive_check_step_not_found")
            return None

        if step.check.actor_binding != "actor":
            # 引擎只会替行动者掷骰。把绑定解析成真实角色是新能力（#347 §4.8 明确
            # 排除），但静默替错人掷骰比不掷更糟：那会让规则拿着别人的属性走
            # `result_routes`，而且没有任何痕迹。
            settlement.fail("rule_check_actor_binding_unsupported")
            return None

        option = self._passive_check_option(state, adjudication.actor_id, step)
        if option is None:
            # 停在一个引擎读不出目标值的检定上。此前这类情况会静默挂着；现在
            # 它和其他「引擎做不到」一样显式失败并留痕（#398 §阶段一）。
            settlement.fail("check_profile_unavailable")
            return None

        source_event_id = next(
            (
                item.source_event_id
                for item in settlement.queue
                if item.rule_id == rule.id and item.status == "running"
            ),
            None,
        )
        if source_event_id is None:
            settlement.fail("passive_check_step_not_found")
            return None

        decision = PendingCheckDecision(
            decision_id=self._new_id("check_decision"),
            room_id=runtime.game_state.room_id,
            player_id=player_id,
            actor_id=adjudication.actor_id,
            # 沿用父动作的 request id：ActionPlan 的当前步骤、重连恢复和命令
            # 日志都以它为键。数据库那条「一个动作至多一次检定」的唯一约束因此
            # 放宽成「至多一次**未结算**的检定」（见 b8c9d0e1f2a3 迁移）。
            action_request_id=adjudication.request_id,
            source_revision=runtime.revision,
            status="awaiting_skill_choice",
            adjudication=adjudication,
            options=(option,),
            rule_origin=RuleCheckOrigin(
                agenda_id=agenda.agenda_id,
                rule_id=rule.id,
                branch_id=agenda.current_branch_id or "default",
                step_id=step.id,
                source_event_id=source_event_id,
            ),
            allow_cancel=False,
        )
        settlement.agenda = agenda.model_copy(
            update={"pending_check_id": decision.decision_id}
        )
        return decision

    def _passive_check_option(
        self,
        state: GameState,
        actor_id: str,
        step: CheckStep,
    ) -> PendingCheckOption | None:
        """规则自己指定技能，所以菜单只有一条。

        这是 `RuleCheckSpec.profile_id` / `parameters` 的第一个真实消费者——在
        此之前这两个字段除契约、测试与 build 脚本外零消费者。
        """

        profile = check_profile_registry.registration_for(step.check.profile_id)
        if profile is None:
            return None
        actor = state.actors.get(actor_id)
        if actor is None:
            return None
        target_value = getattr(actor.resources, profile.resource, None)
        if not isinstance(target_value, int) or not 0 <= target_value <= 100:
            return None
        return PendingCheckOption(
            candidate_id=f"rule:{step.id}",
            skill_id=profile.resource,
            display_name=profile.display_name,
            target_value=target_value,
            difficulty=step.check.difficulty or profile.default_difficulty,
            method_summary=profile.method_summary,
            player_safe_reason=profile.player_safe_reason,
        )

    def _drive_with_barrier(
        self,
        settlement: RuleSettlement,
        state: GameState,
        events: list[DomainEvent],
        effects: tuple[ActionEffect, ...],
        *,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        actor_id: str,
    ) -> tuple[GameState, SettlementResult, tuple[ActionEffect, ...]]:
        """执行一个效果 → 提交它的事件 → 立即结算该事件的规则 → 再下一个。

        返回停下时的 state、最后一次结算结果，以及**还没执行**的效果。

        先结算一次再进循环：`check.rolled` / `check.resolved` 这些前置事件同样
        是规则输入，它们的规则也必须在第一个效果之前就位。
        """

        result = settlement.advance(state, events)
        if result.blocked:
            return result.state, result, effects
        state = result.state
        for index, effect in enumerate(effects):
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
            result = settlement.advance(state, events)
            state = result.state
            if result.blocked:
                return state, result, effects[index + 1 :]
        return state, result, ()

    def _complete_parent_action(
        self,
        settlement: RuleSettlement,
        state: GameState,
        events: list[DomainEvent],
        *,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        adjudication: ActionAdjudication,
        passed: bool,
    ) -> tuple[GameState, SettlementResult]:
        """Agenda 稳定之后才发完成事件，然后结算它自己触发的规则。

        `action.succeeded` 是「这次行动到此为止」的断言。规则链还挂着的时候发它
        就是在说谎——#398 §阶段二 明确要求 Agenda 未稳定前不得发布它。
        """

        events.append(
            self._completion_event(
                state,
                runtime=runtime,
                request_id=request_id,
                adjudication=adjudication,
                passed=passed,
                offset=len(events) + 1,
            )
        )
        settled = settlement.advance(state, events)
        return settled.state, settled

    def _completion_event(
        self,
        state: GameState,
        *,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        adjudication: ActionAdjudication,
        passed: bool,
        offset: int,
    ) -> DomainEvent:
        """只造事件，不结算。

        规则链已经失败时也要发这条——动作确实到此为止了——但那时 Agenda 是终态，
        再调一次 `advance()` 只会立刻返回，写成结算是在假装还在结算。
        """

        return self._event_from_state(
            state,
            room_id=runtime.game_state.room_id,
            offset=offset,
            request_id=request_id,
            actor_id=adjudication.actor_id,
            event_type="action.succeeded" if passed else "action.failed",
            payload={"action_request_id": adjudication.request_id},
        )

    def _apply_effects_unsettled(
        self,
        state: GameState,
        events: list[DomainEvent],
        effects: tuple[ActionEffect, ...],
        *,
        runtime: EngineRuntimeSnapshot,
        request_id: str,
        actor_id: str,
    ) -> tuple[GameState, int]:
        """执行父动作剩下的效果，但不再结算它们唤醒的规则。

        只在规则链已经 `failed` 时走这里。Agenda 是终态、没有恢复的余地，所以
        没有「同一个 Agenda」可以继续收这些事件；硬造一个新的等于让一条失败的
        规则链自己复活。效果照跑（否则玩家的动作被一条坏规则否决了一半），
        数量记进 `rule.agenda_failed` 的 `unsettled_effect_count`。
        """

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
        return state, len(effects)

    def _new_settlement(
        self,
        runtime: EngineRuntimeSnapshot,
        *,
        request_id: str,
        actor_id: str,
    ) -> RuleSettlement:
        return RuleSettlement(
            agenda=create_rule_agenda(
                agenda_id=self._new_id("agenda"),
                room_id=runtime.game_state.room_id,
                module=runtime.module_content,
                correlation_id=request_id,
                root_source=AgendaSource(kind="action", id=request_id),
                revision=str(runtime.game_state.event_sequence),
            ),
            runtime=runtime,
            actor_id=actor_id,
            runner=_SettlementRunner(self, runtime, request_id, actor_id),
        )

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
        emitted = [
            self._event_from_state(
                result.state,
                room_id=room_id,
                offset=offset,
                request_id=request_id,
                actor_id=actor_id,
                event_type=result.event_type,
                payload=result.payload,
                event_id=result.event_id,
            )
        ]
        # 附带事件与主事件同一次提交，序号顺延。`time.task_due` 走这条路：
        # 到期是「进入这一刻」的一部分，不是它之后的另一次写入。
        for index, extra in enumerate(result.extra_events, start=1):
            emitted.append(
                self._event_from_state(
                    result.state,
                    room_id=room_id,
                    offset=offset + index,
                    request_id=request_id,
                    actor_id=actor_id,
                    event_type=extra.event_type,
                    payload=extra.payload,
                    visibility=extra.visibility,
                )
            )
        return result.state, tuple(emitted)

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
