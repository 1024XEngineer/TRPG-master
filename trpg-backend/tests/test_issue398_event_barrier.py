"""事件屏障在真实持久化链路上的行为（#398 §阶段二）。

框架侧覆盖在 `agent-collaboration-framework/tests/test_event_barrier.py`。这里
重跑同一个场景，但走 `SqlAlchemyEngineStore` 和真实发布的模组内容——「按事件
发生时的状态匹配」如果只在内存 fixture 上成立，对线上房间没有意义。

E2E 层覆盖不到这个场景：Fake planner 一次只授权一个 `advance_world_time`
（`DeterministicHostTurnDecisionModel` 认「等到下一个时间点」这一句），而缺陷
恰恰只在**一次动作提交多跳**时才显形。多跳裁决只能由真实模型产出，所以确定性
覆盖落在这一层。
"""

from __future__ import annotations

from collections.abc import Callable

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import AdjudicationEngineService, GameState
from collaboration_framework.engine.models import WorldTimePoint, WorldTimeState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.models.engine import GameEvent, GameSession
from tests.test_engine_runtime import _start_room

# 《追书人》的时间线是 00 / 06 / 12 / 18 / 20，夜间为 18:00–06:00。
# 中午躺下、睡到第二天早晨要跨过 18 → 20 → 00 → 06，其中前三个点是夜里。
SLEEP_UNTIL_MORNING = ("hour_18", "hour_20", "hour_00", "hour_06")


async def _noon_with_surveillance_closed(db: AsyncSession, room_id: str) -> str:
    game_session = await db.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    entities = dict(state.entities)
    entities["case_tracker"] = {
        **entities["case_tracker"],
        "surveillance_available": False,
    }
    game_session.state_json = state.model_copy(
        update={
            "entities": entities,
            "world_time": WorldTimeState(
                current_point_id="hour_12",
                current=WorldTimePoint(day_index=0, hour_of_day=12),
            ),
        },
        deep=True,
    ).to_json_dict()
    await db.commit()
    return next(iter(state.actors))


async def _committed_state(db: AsyncSession, room_id: str) -> GameState:
    """重新读回权威状态。

    `db_session.expire_all()` 之后必须真的再查一次：引擎写在另一个 session 里，
    这个 session 缓存的对象是旧的。
    """

    reloaded = await db.get(GameSession, room_id)
    assert reloaded is not None
    return GameState.model_validate(reloaded.state_json)


async def test_night_rule_matches_the_snapshot_of_its_own_time_point(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session, room_number=97)
    room_id, player_id = room.id, players[0].id
    actor_id = await _noon_with_surveillance_closed(db_session, room_id)

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        SubmitAdjudicationRequest(
            room_id=room_id,
            player_id=player_id,
            adjudication=ActionAdjudication(
                request_id="issue398-sleep",
                source_revision=runtime.revision,
                actor_id=actor_id,
                summary="睡到第二天早晨",
                target=ActionTarget(kind="location", id="thomas_office"),
                method=ActionMethod(family="rest", description="和衣睡下"),
                check=NoAdjudicationCheck(),
                success_effects=tuple(
                    AdvanceWorldTimeEffect(to_point_id=point) for point in SLEEP_UNTIL_MORNING
                ),
            ),
        )
    )

    assert execution.status == "resolved"
    db_session.expire_all()
    committed = await _committed_state(db_session, room_id)
    # 四跳都跑完了，世界确实到了第二天早晨。
    assert committed.world_time.current_point_id == "hour_06"
    assert committed.world_time.current.day_index == 1
    # 而 18:00 那一跳按**当时**的世界匹配，夜间监视点开了出来。
    # 修好之前这里是 False：终态是 06:00，`time_of_day_is night` 判否，于是
    # 叙事只能写成「安稳睡到早晨」。
    assert committed.entities["case_tracker"]["surveillance_available"] is True

    triggered = (
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == room_id,
                GameEvent.type == "rule.triggered",
            )
        )
    ).all()
    night_rule = [
        event for event in triggered if event.payload["rule_id"] == "enable_night_surveillance"
    ]
    # 三个夜间点，但规则自己的 `surveillance_available == false` 前置条件
    # 只让它触发一次——屏障没有把「每个事件重新匹配」变成「同一条规则跑三遍」。
    assert len(night_rule) == 1
    source = next(
        event
        for event in (
            await db_session.scalars(select(GameEvent).where(GameEvent.room_id == room_id))
        ).all()
        if event.event_id == night_rule[0].payload["source_event_id"]
    )
    assert source.type == "time.point_entered"
    assert source.payload["point_id"] == "hour_18"
