"""Driving one RuleAgenda forward across the events an action produces.

This used to be a single pass at the end of `_finalize_action`: run every
effect the action owned, then scan the whole event list once and settle the
Rules those events triggered. The scan visited events in the right order, but
it read `state` — the world `matching_event_rules` matches conditions against —
only after the last effect had already been applied. So a rule triggered by the
*first* event was matched against the world as it looked after the *last* one.

《追书人》「睡到第二天早晨」是这条缺陷的最短复现：Agent 一次提交
18:00 → 20:00 → 00:00 → 06:00 四个时间推进，`enable_night_surveillance` 的
`time_of_day_is night` 拿 06:00 的世界去判 18:00 那条 `time.point_entered`，
永远判否，夜间监视点永远开不出来（#398 §阶段二）。

修的不是遍历顺序——顺序本来就是对的。修的是结算时机必须落在**两个效果之间**，
所以这里把游标持有成可变状态，由 `_finalize_action` 反复推进：执行一个效果、
追加它的事件、`advance()`，然后才轮到下一个效果。`advance()` 看到什么，就是
那些事件发生当时的状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from collaboration_framework.contracts import ActionEffect, ModuleContentV3, RuleSpecV3

from .models import (
    AgendaItem,
    DomainEvent,
    EngineRuntimeSnapshot,
    GameState,
    RuleAgenda,
)
from .rules_v3 import (
    agenda_failure_code_for_walk,
    agenda_item_for_event,
    agenda_status_for_walk,
    matching_event_rules,
    walk_rule,
    walk_rule_from,
)

# 引擎自己发的审计信号，永远不是规则的输入（#226 §4）。
AUDIT_EVENT_TYPES = frozenset({"rule.triggered", "rule.agenda_failed"})

# 一个 Agenda 到了这两个状态就再没有推进的余地，也没有任何读者。
SETTLED_AGENDA_STATUSES = frozenset({"stable", "failed"})

SettlementStatus = Literal["stable", "suspended", "failed"]


class EffectRunner(Protocol):
    """The Engine capabilities this module needs but must not own.

    Validating and applying an effect, and minting a DomainEvent, all live on
    `AdjudicationEngineService`. Passing them in keeps this module free of the
    service and therefore testable on its own.
    """

    def validate_effects(
        self,
        runtime: EngineRuntimeSnapshot,
        effects: tuple[ActionEffect, ...],
    ) -> None: ...

    def apply_effect(
        self,
        runtime: EngineRuntimeSnapshot,
        state: GameState,
        effect: ActionEffect,
        *,
        offset: int,
    ) -> tuple[GameState, tuple[DomainEvent, ...]]: ...

    def emit_event(
        self,
        state: GameState,
        *,
        offset: int,
        event_type: str,
        payload: dict,
        visibility: str,
    ) -> DomainEvent: ...


@dataclass(frozen=True)
class SettlementResult:
    """Where the Agenda stands, and the world as of that moment."""

    state: GameState
    status: SettlementStatus
    failure_code: str | None = None

    @property
    def blocked(self) -> bool:
        """Whether the parent action must stop rather than run its next effect."""

        return self.status != "stable"


@dataclass
class RuleSettlement:
    """One Agenda, plus the cursor into the event list it is consuming.

    Held across an entire `_finalize_action`: one action produces one Agenda,
    however many effects it commits and however many rules those effects wake.
    """

    agenda: RuleAgenda
    runtime: EngineRuntimeSnapshot
    actor_id: str
    runner: EffectRunner

    queue: list[AgendaItem] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    # (rule_id, source_event_id) 已经点过火的组合。一条规则对同一个事件只触发
    # 一次，跨 advance() 调用同样成立——所以它和 cursor 一样是实例状态。
    fired: set[tuple[str, str]] = field(default_factory=set)
    cursor: int = 0
    suspended: bool = False

    @property
    def module(self) -> ModuleContentV3:
        return self.runtime.module_content

    def advance(
        self,
        state: GameState,
        events: list[DomainEvent],
    ) -> SettlementResult:
        """Settle every event appended since the last call.

        `events` is appended to in place: rule effects emit their own events,
        and those events are themselves rule inputs, so the loop's bound is
        re-read each pass rather than captured up front.
        """

        while self.cursor < len(events) and not self.suspended:
            source_event = events[self.cursor]
            self.cursor += 1
            if source_event.type in AUDIT_EVENT_TYPES:
                continue
            for rule in self._enqueue_matching(state, source_event):
                state, keep_going = self._run_rule(rule, source_event, state, events)
                if not keep_going:
                    break
        return self._result(state)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _enqueue_matching(
        self,
        state: GameState,
        source_event: DomainEvent,
    ) -> list[RuleSpecV3]:
        pending_rules: list[RuleSpecV3] = []
        for rule in matching_event_rules(
            self.module,
            event_type=source_event.type,
            state=state,
            actor_id=self.actor_id,
        ):
            fire_key = (rule.id, source_event.event_id)
            if fire_key in self.fired:
                continue
            self.fired.add(fire_key)
            pending_rules.append(rule)
            self.queue.append(agenda_item_for_event(rule, source_event))
        if pending_rules:
            self.source_event_ids.append(source_event.event_id)
        return pending_rules

    def _run_rule(
        self,
        rule: RuleSpecV3,
        source_event: DomainEvent,
        state: GameState,
        events: list[DomainEvent],
    ) -> tuple[GameState, bool]:
        """Walk one rule. The flag is False when the Agenda stopped here."""

        item_index = next(
            index
            for index, item in enumerate(self.queue)
            if item.source_event_id == source_event.event_id
            and item.rule_id == rule.id
            and item.status == "queued"
        )
        self._set_item(item_index, "running")

        next_depth = self.agenda.chain_depth + 1
        max_chain_depth = min(self.agenda.max_chain_depth, rule.limits.max_chain_depth)
        max_steps = min(self.agenda.max_steps, rule.limits.max_steps)
        self.agenda = self.agenda.model_copy(
            update={
                "chain_depth": next_depth,
                "max_chain_depth": max_chain_depth,
                "max_steps": max_steps,
            }
        )
        if next_depth > max_chain_depth:
            self._fail_budget(item_index, rule, step_id=None)
            return state, False

        walk = walk_rule(rule, branch_id=self.queue[item_index].branch_id)
        next_step_count = self.agenda.step_count + walk.step_count
        if next_step_count > max_steps:
            self._fail_budget(
                item_index,
                rule,
                step_id=walk.suspended_at
                or next(
                    branch.entry_step_id
                    for branch in rule.execution.branches
                    if branch.id == self.queue[item_index].branch_id
                ),
                step_count=next_step_count,
            )
            return state, False
        self.agenda = self.agenda.model_copy(update={"step_count": next_step_count})

        events.append(
            self.runner.emit_event(
                state,
                offset=len(events) + 1,
                event_type="rule.triggered",
                payload={
                    "rule_id": rule.id,
                    "source_event_id": source_event.event_id,
                    "agenda_id": self.agenda.agenda_id,
                },
                visibility="hidden",
            )
        )
        state = self.commit_effects(state, walk.effects, events)

        status = agenda_status_for_walk(rule, walk)
        if status == "stable":
            self._set_item(item_index, "completed")
            return state, True
        self._set_item(item_index, "failed" if status == "failed" else "running")
        self.agenda = self.agenda.model_copy(
            update={
                "status": status,
                # 失败原因来自 walk 本身（循环 / 步数 / 未知步）或它停在的 step
                # kind（四种无执行器 kind），不再一律写 agenda_budget_exceeded。
                "failure_code": (
                    agenda_failure_code_for_walk(walk) if status == "failed" else None
                ),
                "current_rule_id": rule.id,
                "current_branch_id": self.queue[item_index].branch_id,
                "current_step_id": walk.suspended_at,
            }
        )
        self.suspended = True
        return state, False

    def resume_rule(
        self,
        rule: RuleSpecV3,
        resume_step_id: str | None,
        state: GameState,
        events: list[DomainEvent],
    ) -> SettlementResult:
        """Continue the suspended rule from where its check routed it.

        `resume_step_id` is None when the authored `result_routes` says nothing
        about the degree that was rolled. That is not a failure — a branch is
        allowed to care about only some outcomes — the rule simply has nothing
        further to say and its queue item completes.
        """

        item_index = self._running_item_index(rule.id)
        if resume_step_id is None:
            self._set_item(item_index, "completed")
            self.suspended = False
            self._clear_cursor()
            return self.advance(state, events)

        walk = walk_rule_from(rule, resume_step_id)
        next_step_count = self.agenda.step_count + walk.step_count
        if next_step_count > self.agenda.max_steps:
            self._fail_budget(
                item_index,
                rule,
                step_id=walk.suspended_at or resume_step_id,
                step_count=next_step_count,
            )
            return self._result(state)
        self.agenda = self.agenda.model_copy(update={"step_count": next_step_count})
        state = self.commit_effects(state, walk.effects, events)

        status = agenda_status_for_walk(rule, walk)
        if status == "stable":
            self._set_item(item_index, "completed")
            self.suspended = False
            self._clear_cursor()
            # 恢复出来的效果本身也是事件，也可能唤醒别的规则——它们进同一个
            # Agenda，直到整条链稳定为止（#398 §目标 4）。
            return self.advance(state, events)
        self._set_item(item_index, "failed" if status == "failed" else "running")
        self.agenda = self.agenda.model_copy(
            update={
                "status": status,
                "failure_code": (
                    agenda_failure_code_for_walk(walk) if status == "failed" else None
                ),
                "current_rule_id": rule.id,
                "current_branch_id": self.queue[item_index].branch_id,
                "current_step_id": walk.suspended_at,
            }
        )
        self.suspended = True
        return self._result(state)

    def _running_item_index(self, rule_id: str) -> int:
        return next(
            index
            for index, item in enumerate(self.queue)
            if item.rule_id == rule_id and item.status == "running"
        )

    def fail(self, code: str) -> None:
        """Force the Agenda to a failed cursor the Engine could not act on.

        Used when the suspension point itself is unusable — a check profile
        this Engine does not implement, or an actor with no value to roll
        against. The alternative is raising, which would abort an action whose
        effects have already committed.
        """

        self.agenda = self.agenda.model_copy(
            update={"status": "failed", "failure_code": code}
        )
        for index, item in enumerate(self.queue):
            if item.status == "running":
                self._set_item(index, "failed")
        self.suspended = True

    def _clear_cursor(self) -> None:
        self.agenda = self.agenda.model_copy(
            update={
                "status": "running",
                "failure_code": None,
                "current_rule_id": None,
                "current_branch_id": None,
                "current_step_id": None,
                "pending_check_id": None,
            }
        )

    def commit_effects(
        self,
        state: GameState,
        effects: list[ActionEffect],
        events: list[DomainEvent],
    ) -> GameState:
        """Validate a rule's own effects against the world it sees, then run them."""

        rule_runtime = self.runtime.model_copy(update={"game_state": state}, deep=True)
        self.runner.validate_effects(rule_runtime, tuple(effects))
        for effect in effects:
            state, emitted = self.runner.apply_effect(
                self.runtime,
                state,
                effect,
                offset=len(events) + 1,
            )
            events.extend(emitted)
        return state

    def _set_item(self, index: int, status: str) -> None:
        self.queue[index] = self.queue[index].model_copy(update={"status": status})

    def _fail_budget(
        self,
        item_index: int,
        rule: RuleSpecV3,
        *,
        step_id: str | None,
        step_count: int | None = None,
    ) -> None:
        self._set_item(item_index, "failed")
        update: dict = {
            "status": "failed",
            "failure_code": "agenda_budget_exceeded",
            "current_rule_id": rule.id,
            "current_branch_id": self.queue[item_index].branch_id,
        }
        if step_id is not None:
            update["current_step_id"] = step_id
        if step_count is not None:
            update["step_count"] = step_count
        self.agenda = self.agenda.model_copy(update=update)
        self.suspended = True

    def _result(self, state: GameState) -> SettlementResult:
        if not self.queue or not self.suspended:
            return SettlementResult(state=state, status="stable")
        status: SettlementStatus = (
            "failed" if self.agenda.status == "failed" else "suspended"
        )
        return SettlementResult(
            state=state,
            status=status,
            failure_code=self.agenda.failure_code,
        )

    # ------------------------------------------------------------------ #
    # finishing
    # ------------------------------------------------------------------ #

    def finish(
        self,
        state: GameState,
        events: list[DomainEvent],
    ) -> tuple[GameState, str | None]:
        """Seal the Agenda and write only what is still in flight into `state`."""

        if not self.queue:
            return without_settled_agendas(state), None
        if not self.suspended:
            self.agenda = self.agenda.model_copy(
                update={
                    "status": "stable",
                    "current_rule_id": None,
                    "current_branch_id": None,
                    "current_step_id": None,
                }
            )
        if self.agenda.status == "failed":
            # 失败必须留下痕迹。#398 之前 Agenda 落到 failed 只是改一个字段，
            # 不发任何事件，execution 照常返回 resolved。
            events.append(
                self.runner.emit_event(
                    state,
                    offset=len(events) + 1,
                    event_type="rule.agenda_failed",
                    payload={
                        "agenda_id": self.agenda.agenda_id,
                        "failure_code": self.agenda.failure_code,
                        "rule_id": self.agenda.current_rule_id,
                        "branch_id": self.agenda.current_branch_id,
                        "step_id": self.agenda.current_step_id,
                        "source_event_ids": list(self.source_event_ids),
                    },
                    visibility="hidden",
                )
            )
        final_revision = str(self.runtime.game_state.event_sequence + len(events))
        self.agenda = self.agenda.model_copy(
            update={
                "source_event_ids": tuple(self.source_event_ids),
                "queue": tuple(self.queue),
                "revision": final_revision,
            },
            deep=True,
        )
        agendas = {
            agenda_id: item
            for agenda_id, item in state.rule_agendas.items()
            # 排除自己：`state` 里可能还留着上一次事务写下的、状态为
            # awaiting_* 的旧副本。恢复之后权威版本是手上这个，旧的必须让位，
            # 否则跑完的 Agenda 会以挂起态永远留在库里。
            if agenda_id != self.agenda.agenda_id
            and item.status not in SETTLED_AGENDA_STATUSES
        }
        if self.agenda.status not in SETTLED_AGENDA_STATUSES:
            # 只有在途 Agenda 才落库（#398 §阶段一）。
            agendas[self.agenda.agenda_id] = self.agenda
        state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
        return state, self.agenda.failure_code


def without_settled_agendas(state: GameState) -> GameState:
    """丢弃已经终态的 RuleAgenda，只留在途游标。

    存量房间的 `game_state` 里已经积了历史死数据（#398 之前无条件落库且全仓库
    没有删除路径），所以这里同时承担清理职责：任何一次会走到事件规则结算的动作
    都会顺手把它们扫掉，不需要单独的数据迁移。
    """

    live = {
        agenda_id: agenda
        for agenda_id, agenda in state.rule_agendas.items()
        if agenda.status not in SETTLED_AGENDA_STATUSES
    }
    if len(live) == len(state.rule_agendas):
        return state
    return state.model_copy(update={"rule_agendas": live}, deep=True)


__all__ = [
    "AUDIT_EVENT_TYPES",
    "SETTLED_AGENDA_STATUSES",
    "EffectRunner",
    "RuleSettlement",
    "SettlementResult",
    "SettlementStatus",
    "without_settled_agendas",
]
