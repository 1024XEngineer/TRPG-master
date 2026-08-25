"""排定与取消运行时定时任务，以及它们插出来的临时时间点（#245 §5 / #415 §阶段四）。

时间线本身只认模组声明的默认点。定时任务要落在「12 点和 18 点之间的 15:00」
这种作者没声明过的时刻上，靠的是往 `GameState.time_occurrences` 里插一个
**一次性 occurrence**，再让 `ordered_points` 把它混进默认点重排。

三条不变量决定了这里的形状：

1. **任务绑 occurrence，不绑时刻。** 同日同小时的多个任务共享一个 occurrence，
   所以取消其中一个既不该动其他任务，也不该动那个点。
2. **目标恰好是默认点时不建临时 occurrence。** 建了就等于同一刻来两次。
3. **目标不能晚于 `terminal_point`。** 越界的任务永远不会到期，留着就是一条
   静默失效的剧情线；在创建时就拒绝比在到期时发现好。
"""

from __future__ import annotations

import json
from hashlib import blake2s

from collaboration_framework.contracts import (
    CancelTimeTaskStep,
    ContractError,
    CreateTimeTaskStep,
    ModuleContentV3,
    TimeTaskTargetSpec,
    segment_at_hour,
)

from .models import GameState, RuntimeTimeTask, TimePointOccurrence, WorldTimePoint
from .timeline import ordered_points, terminal_reached

# 目标晚于终点。任务永远不会到期，所以创建时就拒绝（#415 §阶段二）。
INVALID_TIME_TASK_TARGET = "invalid_time_task_target"


def runtime_task_id(rule_id: str, task_key: str, bindings: dict) -> str:
    """同一条规则 + 同一个 key + 同一组绑定 = 同一个任务。

    id 从内容推导而不是随机生成，重试才不会排出第二个一模一样的任务，
    `cancel_time_task` 也才定位得到——它手上只有 key 和 bindings。
    """

    digest = blake2s(
        json.dumps([rule_id, task_key, bindings], sort_keys=True, ensure_ascii=False).encode(),
        digest_size=8,
    ).hexdigest()
    return f"task_{digest}"


def _occurrence_id(day_index: int, hour_of_day: int) -> str:
    """同日同小时落在同一个 occurrence 上——这就是任务间共享点的机制。"""

    return f"occ_d{day_index}_h{hour_of_day:02d}"


def resolve_target(
    module_content: ModuleContentV3,
    state: GameState,
    target: TimeTaskTargetSpec,
) -> WorldTimePoint:
    """把作者写的目标解析成一个绝对时刻。

    相对目标按**当前**世界时钟推算，所以解析必须发生在提交那一刻，不能在
    walk 的时候提前算好——中间可能还有别的效果推进了时间。
    """

    if target.point_id is not None:
        point = next(
            (item for item in ordered_points(module_content) if item.id == target.point_id),
            None,
        )
        if point is None:
            raise ContractError(
                f"{INVALID_TIME_TASK_TARGET}: 目标点不在模组时间线上: {target.point_id}"
            )
        return _next_occurrence_of_hour(state, point.hour_of_day)

    assert target.hour_of_day is not None  # 契约保证二选一
    if target.relative:
        absolute = state.world_time.current.absolute_hour + target.hour_of_day
        return WorldTimePoint(day_index=absolute // 24, hour_of_day=absolute % 24)
    assert target.day_index is not None  # 契约保证绝对目标必须带 day_index
    return WorldTimePoint(day_index=target.day_index, hour_of_day=target.hour_of_day)


def _next_occurrence_of_hour(state: GameState, hour_of_day: int) -> WorldTimePoint:
    """绑定默认点时取**下一次**到达它，不是今天那一次。

    「明晚 18 点」和「今天 18 点」在 18:01 是同一个 point id，只有当前时刻能
    区分它们；已经过去的那一次绑上去就永远不会到期。
    """

    today = WorldTimePoint(day_index=state.world_time.current.day_index, hour_of_day=hour_of_day)
    if today.absolute_hour > state.world_time.current.absolute_hour:
        return today
    return WorldTimePoint(day_index=today.day_index + 1, hour_of_day=hour_of_day)


def _refuse_beyond_terminal(
    module_content: ModuleContentV3,
    moment: WorldTimePoint,
) -> None:
    """终点之后的任务在创建时拒绝；恰好等于终点时允许绑定。"""

    terminal = module_content.time_policy.terminal_point
    if terminal is None:
        return
    terminal_point = next(
        item for item in ordered_points(module_content) if item.id == terminal.point_id
    )
    terminal_hour = terminal.day_index * 24 + terminal_point.hour_of_day
    if moment.absolute_hour > terminal_hour:
        raise ContractError(
            f"{INVALID_TIME_TASK_TARGET}: 目标晚于模组时间线的终点: "
            f"D{moment.day_index} {moment.hour_of_day:02d}:00"
        )


def create_time_task(
    module_content: ModuleContentV3,
    state: GameState,
    step: CreateTimeTaskStep,
    *,
    rule_id: str,
) -> tuple[GameState, RuntimeTimeTask, TimePointOccurrence | None]:
    """排一个任务，必要时插一个临时 occurrence。

    返回的第三项是**新建**的 occurrence；目标恰好落在默认点上、或者同一刻已经
    有别的任务时为 None——两种情况都不该再造一个重复的点。
    """

    if terminal_reached(module_content, state.world_time):
        raise ContractError(
            f"{INVALID_TIME_TASK_TARGET}: 时间线已经走到终点，不能再排定时任务"
        )

    moment = resolve_target(module_content, state, step.task.target)
    _refuse_beyond_terminal(module_content, moment)

    occurrence_id = _occurrence_id(moment.day_index, moment.hour_of_day)
    occurrences = dict(state.time_occurrences)
    created: TimePointOccurrence | None = None

    lands_on_default_point = any(
        item.hour_of_day == moment.hour_of_day for item in ordered_points(module_content)
    )
    # 目标恰好是默认点时直接绑那一次到达；同一刻已经有别的任务时复用它排出来
    # 的那个点。两种情况都不该再造一个重复 occurrence。
    if not lands_on_default_point and occurrence_id not in occurrences:
        created = TimePointOccurrence(
            occurrence_id=occurrence_id,
            point_id=None,
            day_index=moment.day_index,
            hour_of_day=moment.hour_of_day,
            time_segment=segment_at_hour(moment.hour_of_day),
            origin="time_task",
        )
        occurrences[occurrence_id] = created

    task = RuntimeTimeTask(
        task_id=runtime_task_id(rule_id, step.task.task_key, step.task.bindings),
        task_key=step.task.task_key,
        rule_id=rule_id,
        branch_id=step.task.on_due_branch_id,
        occurrence_id=occurrence_id,
        priority=step.task.priority,
        visibility=step.task.visibility,
        bindings=step.task.bindings,
    )
    tasks = dict(state.time_tasks)
    existing = tasks.get(task.task_id)
    if existing is not None and existing.status == "scheduled":
        # 同一条规则用同一组绑定重复排同一个任务：幂等，不排第二个。
        return state, existing, None
    tasks[task.task_id] = task
    return (
        state.model_copy(
            update={"time_tasks": tasks, "time_occurrences": occurrences}, deep=True
        ),
        task,
        created,
    )


def cancel_time_task(
    state: GameState,
    step: CancelTimeTaskStep,
    *,
    rule_id: str,
) -> tuple[GameState, RuntimeTimeTask | None]:
    """按 key + bindings 取消一个任务，必要时收回它独占的临时 occurrence。

    取消一个任务不影响同点其他任务；只有该点**所有**任务都取消、且该点尚未
    进入时，才把 occurrence 一并移除。
    """

    task_id = runtime_task_id(rule_id, step.task_key, step.bindings)
    task = state.time_tasks.get(task_id)
    if task is None or task.status != "scheduled":
        # 取消一个不存在或已经结算过的任务不是错误：规则可能在两条路径上都
        # 写了取消，先到的那条已经做完了。
        return state, None

    tasks = dict(state.time_tasks)
    tasks[task_id] = task.model_copy(
        update={"status": "cancelled", "cancel_reason_code": step.reason_code}
    )

    occurrences = dict(state.time_occurrences)
    occurrence = occurrences.get(task.occurrence_id)
    still_scheduled = any(
        item.occurrence_id == task.occurrence_id and item.status == "scheduled"
        for item in tasks.values()
    )
    if occurrence is not None and occurrence.origin == "time_task" and not still_scheduled:
        del occurrences[task.occurrence_id]

    return (
        state.model_copy(
            update={"time_tasks": tasks, "time_occurrences": occurrences}, deep=True
        ),
        tasks[task_id],
    )


def active_occurrences(state: GameState) -> tuple[TimePointOccurrence, ...]:
    """还有任务等着的临时点，按绝对时刻排序。"""

    live = {
        task.occurrence_id for task in state.time_tasks.values() if task.status == "scheduled"
    }
    return tuple(
        sorted(
            (item for item in state.time_occurrences.values() if item.occurrence_id in live),
            key=lambda item: item.absolute_hour,
        )
    )


def due_tasks(state: GameState, occurrence_id: str) -> tuple[RuntimeTimeTask, ...]:
    """某个 occurrence 上待结算的任务，按 priority 再按 task_id 稳定排序。

    顺序必须稳定：同点多任务的结算结果不能随字典遍历漂移，否则断线恢复重放
    出来的世界和第一次跑出来的不一样。
    """

    return tuple(
        sorted(
            (
                task
                for task in state.time_tasks.values()
                if task.occurrence_id == occurrence_id and task.status == "scheduled"
            ),
            key=lambda task: (task.priority, task.task_id),
        )
    )


__all__ = [
    "INVALID_TIME_TASK_TARGET",
    "active_occurrences",
    "cancel_time_task",
    "create_time_task",
    "due_tasks",
    "resolve_target",
    "runtime_task_id",
]
