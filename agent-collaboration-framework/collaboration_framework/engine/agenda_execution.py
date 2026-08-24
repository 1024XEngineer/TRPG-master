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
    AGENDA_STEP_BUDGET_EXCEEDED,
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

# 队列里的规则在模组换版之后找不到了。与 `RULE_AGENDA_UNRESUMABLE` 同源：
# 游标指向的东西不在了，半截执行比显式失败更糟。
QUEUED_RULE_NOT_FOUND = "queued_rule_not_found"

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
    # 上一次请求挂起时还没读到的事件。它们已经落库了，所以**不能**并回 `events`
    # （那个列表会被整体当成新事件写出去），只能单独排在前面消费。
    carried: list[DomainEvent] = field(default_factory=list)
    # (rule_id, source_event_id) 已经点过火的组合。一条规则对同一个事件只触发
    # 一次，跨 advance() 调用同样成立——所以它和 cursor 一样是实例状态。
    fired: set[tuple[str, str]] = field(default_factory=set)
    cursor: int = 0
    suspended: bool = False

    def __post_init__(self) -> None:
        # `_enqueue_matching` 每点一次火就正好追加一个队列项，两者严格 1:1，所以
        # `fired` 可以从 `queue` 重建，不必单独持久化一份。跨请求恢复时调用方只
        # 传得回 `queue`——不重建的话 `fired` 是空的，同一条规则会对同一个事件
        # 再触发一次（#398 验收：重试 / 重连 / 进程重启后保持幂等）。
        self.fired |= {(item.rule_id, item.source_event_id) for item in self.queue}

    @property
    def module(self) -> ModuleContentV3:
        return self.runtime.module_content

    def advance(
        self,
        state: GameState,
        events: list[DomainEvent],
    ) -> SettlementResult:
        """Settle every event appended since the last call.

        Two phases, in this order: drain whatever is already queued, then read
        one more event. `events` is appended to in place — rule effects emit
        their own events and those are themselves rule inputs — so the bound is
        re-read each pass rather than captured up front.

        入队与执行原来是同一步：`_enqueue_matching` 把刚入队的规则返回给调用方，
        调用方在一个遇挂起就 `break` 的 `for` 循环里跑它们。于是还留在那个循环里
        的规则再也无人问津——全仓库没有任何地方读 `queued` 项。一个事件匹配到两
        条规则、第一条挂起，第二条就永远不会触发。

        《追书人》的 `ghoul_crowd_sanity`（priority 180）与
        `first_sight_of_douglas`（120）——#398 失败案例 B 点名的那两条——正好匹配
        同一条 `entity.state_changed`。拆成两相之后，队列成为「还有什么没跑」的
        唯一事实源，这次请求和恢复它的那次请求读的是同一份。
        """

        while not self.suspended:
            state, ran = self._drain_queue(state, events)
            if ran:
                # 跑一条规则可能又追加了事件，也可能刚好挂起——两种情况都要
                # 回到循环顶部重新判断，而不是接着往下读事件。
                continue
            source_event = self._next_source_event(events)
            if source_event is None:
                break
            if source_event.type in AUDIT_EVENT_TYPES:
                continue
            self._enqueue_matching(state, source_event)
        return self._result(state)

    def result(self, state: GameState) -> SettlementResult:
        """当前结算状态。`fail()` 之后调用方要能重新取一次。"""

        return self._result(state)

    def _next_source_event(self, events: list[DomainEvent]) -> DomainEvent | None:
        """先还上一次请求欠的事件，再读这一次的。

        `carried` 里的事件在时间上都早于本次请求，所以排在前面。它们是按**恢复
        时**的 state 匹配的，不是发生当时的快照——房间锁与挂起的检定决策挡住了
        其他提交，所以偏差只限于「这次检定 result_routes 分支的效果」这一项。
        要做到完全精确得给每条事件存一份 state 快照，远超 #398 的范围。
        """

        if self.carried:
            return self.carried.pop(0)
        if self.cursor < len(events):
            event = events[self.cursor]
            self.cursor += 1
            return event
        return None

    def _drain_queue(
        self,
        state: GameState,
        events: list[DomainEvent],
    ) -> tuple[GameState, bool]:
        """Run the next queued item, if there is one.

        FIFO is the deterministic order: `_enqueue_matching` appends in
        `matching_event_rules` order（priority DESC, id ASC）and events are read
        in sequence, so the queue already holds the exact order #226 §4 froze.
        """

        index = next(
            (i for i, item in enumerate(self.queue) if item.status == "queued"),
            None,
        )
        if index is None:
            return state, False
        item = self.queue[index]
        rule = next(
            (
                candidate
                for candidate in self.module.rules
                if candidate.id == item.rule_id
            ),
            None,
        )
        if rule is None:
            # 模组换版之后队列里的规则不在了。半截执行比显式失败更糟。
            self._set_item(index, "failed")
            self.agenda = self.agenda.model_copy(
                update={
                    "status": "failed",
                    "failure_code": QUEUED_RULE_NOT_FOUND,
                    "current_rule_id": item.rule_id,
                    "current_branch_id": item.branch_id,
                }
            )
            self.suspended = True
            return state, False
        state, _ = self._run_rule(rule, item.source_event_id, state, events)
        return state, True

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _enqueue_matching(
        self,
        state: GameState,
        source_event: DomainEvent,
    ) -> None:
        matched = False
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
            matched = True
            self.queue.append(agenda_item_for_event(rule, source_event))
        if matched:
            self.source_event_ids.append(source_event.event_id)

    def _run_rule(
        self,
        rule: RuleSpecV3,
        source_event_id: str,
        state: GameState,
        events: list[DomainEvent],
    ) -> tuple[GameState, bool]:
        """Walk one rule. The flag is False when the Agenda stopped here.

        Takes the source event's id rather than the event itself: that is all
        this method ever needed（队列项定位 + `rule.triggered` 的 payload），and
        `AgendaItem.source_event_id` 已经持久化了。所以恢复一条 `queued` 项不需
        要把原始 `DomainEvent` 也存一份。
        """

        item_index = next(
            index
            for index, item in enumerate(self.queue)
            if item.source_event_id == source_event_id
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
                    "source_event_id": source_event_id,
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
            "failure_code": AGENDA_STEP_BUDGET_EXCEEDED,
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
        *,
        unsettled_effects: int = 0,
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
                        # 停在这条规则上，队列里排在它后面的就再没跑过。失败的
                        # Agenda 不落库，不写进 payload 就彻底查不到了。
                        "skipped_rule_ids": [
                            item.rule_id
                            for item in self.queue
                            if item.status == "queued"
                        ],
                        # 链失败之后父动作剩下的效果照常执行（失败的规则链不否决
                        # 玩家的动作），但它们不再参与规则结算——这件事必须说出来。
                        "unsettled_effect_count": unsettled_effects,
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
                # 挂起时还没读到的事件。规则在挂起**之前**已经把 `rule.triggered`
                # 和自己前置效果的事件追加进 `events` 了，游标却停在它们前面；
                # 不带走的话，恢复后拿到的是一个全新的 events 列表，这些事件就
                # 再也不会被任何规则匹配。只在途 Agenda 才落库，所以随 Agenda
                # 一起消失，不会累积。
                "carried_events": tuple(self.carried) + tuple(events[self.cursor :]),
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
