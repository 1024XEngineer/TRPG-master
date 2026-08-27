"""被动检定在真实持久化链路上的完整往返（#398 §阶段二 + §阶段三）。

框架侧覆盖在 `agent-collaboration-framework/tests/` 的
`test_event_barrier.py`、`test_projection_v3.py` 与 `test_silver_lock_v3_fixture.py`。
这里补的是它们证明不了的那一半：

* 被动检定的 `PendingCheckDecision` 必须真的落进 `pending_check_decisions` 表，
  而那张表原本有一条「一个动作至多一个检定」的唯一约束——迁移 b8c9d0e1f2a3 把它
  放宽成「至多一个**未结算**的检定」，这条路径就是它的验收；
* 挂起的 Agenda 与父动作 continuation 必须能跨进程恢复：换一个全新的 Store
  实例（等价于进程重启）之后照样能结算并跑完剩下的效果。
"""

from __future__ import annotations

from collections.abc import Callable

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorResources,
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    SequenceDiceSource,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.models.engine import GameSession, PendingCheckDecisionRecord
from tests.test_engine_runtime import _start_room


async def _arm_first_sight(db: AsyncSession, room_id: str) -> str:
    """把房间摆成「再看一眼就会触发 first_sight_of_douglas」的样子。

    该规则先提交 `mark_seen`，随后要求一次被动理智检定；#398 之前检定静默丢失。
    """

    game_session = await db.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    actor_id = next(iter(state.actors))
    actor = state.actors[actor_id]
    entities = dict(state.entities)
    entities["cemetery_figure"] = {
        **entities["cemetery_figure"],
        "true_form_seen": False,
        # `_start_room` 的 checkpoint 预置会把它设成 True；本例要观察屏障之后的
        # 那个效果有没有被拦住，所以先放回 False。
        "willing_to_talk": False,
    }
    entities["case_tracker"] = {
        **entities["case_tracker"],
        "first_ghoul_sight_resolved": False,
    }
    game_session.state_json = state.model_copy(
        update={
            "entities": entities,
            "actors": {
                actor_id: actor.model_copy(
                    update={"resources": ActorResources(san=55, luck=50)}, deep=True
                )
            },
        },
        deep=True,
    ).to_json_dict()
    await db.commit()
    return actor_id


def _see_true_form(room_id: str, player_id: str, actor_id: str, revision: str):
    return SubmitAdjudicationRequest(
        room_id=room_id,
        player_id=player_id,
        adjudication=ActionAdjudication(
            request_id="issue398-see-true-form",
            source_revision=revision,
            actor_id=actor_id,
            summary="看清墓地里那个身影的真容",
            target=ActionTarget(kind="entity", id="cemetery_figure"),
            method=ActionMethod(family="observe", description="凑近细看"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="cemetery_figure",
                    key="true_form_seen",
                    value=True,
                ),
                # 屏障之后才该跑的那个效果：规则没结算完就不能碰它。
                ChangeEntityStateEffect(
                    entity_id="cemetery_figure",
                    key="willing_to_talk",
                    value=True,
                ),
            ),
        ),
    )


async def _committed_state(db: AsyncSession, room_id: str) -> GameState:
    """重新读回权威状态。

    `db_session.expire_all()` 之后必须真的再查一次：引擎写在另一个 session 里，
    这个 session 缓存的对象是旧的。
    """

    reloaded = await db.get(GameSession, room_id)
    assert reloaded is not None
    return GameState.model_validate(reloaded.state_json)


async def test_passive_check_persists_and_resumes_across_a_store_restart(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session, room_number=95)
    room_id, player_id = room.id, players[0].id
    actor_id = await _arm_first_sight(db_session, room_id)

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _see_true_form(room_id, player_id, actor_id, runtime.revision)
    )

    # 规则要求的检定真的到了玩家面前，而不是静默丢失。
    assert execution.status == "awaiting_skill_choice"
    pending = execution.pending_decision
    assert pending is not None
    assert len(pending.options) == 1
    assert pending.options[0].display_name == "理智"
    assert pending.options[0].target_value == 55
    assert pending.allow_cancel is False

    db_session.expire_all()
    committed = await _committed_state(db_session, room_id)
    # 检定之前的效果照常提交……
    assert committed.entities["cemetery_figure"]["true_form_seen"] is True
    assert committed.entities["case_tracker"]["first_ghoul_sight_resolved"] is True
    # ……屏障之后的那个被拦下了，连同 continuation 一起存进了 Agenda。
    assert committed.entities["cemetery_figure"]["willing_to_talk"] is False
    agenda = next(iter(committed.rule_agendas.values()))
    assert agenda.status == "awaiting_passive_check"
    assert agenda.pending_check_id == pending.decision_id
    assert agenda.parent_continuation is not None
    assert len(agenda.parent_continuation.remaining_effects) == 1
    assert agenda.parent_continuation.completion_emitted is False

    # 这条决策必须真的落库。同一个 action_request_id 上出现**第二条**决策的
    # 场景由 `test_two_open_decisions_...` 单独覆盖——那才是迁移 b8c9d0e1f2a3
    # 真正放开的能力。
    records = (
        await db_session.scalars(
            select(PendingCheckDecisionRecord).where(
                PendingCheckDecisionRecord.room_id == room_id,
                PendingCheckDecisionRecord.action_request_id == "issue398-see-true-form",
            )
        )
    ).all()
    assert len(records) == 1
    assert records[0].status == "awaiting_skill_choice"

    # 换一个全新的 Store 实例：等价于结算发生在另一个进程里。
    rolled = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([12]))
    ).decide(
        CheckDecisionRequest(
            request_id="issue398-san-roll",
            room_id=room_id,
            player_id=player_id,
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    assert rolled.status == "awaiting_post_roll_decision"
    assert rolled.check_run is not None
    assert rolled.check_run.selected_skill_name == "理智"

    resolved = await AdjudicationEngineService(engine_store_factory()).decide_post_roll(
        PostRollDecisionRequest(
            request_id="issue398-san-accept",
            room_id=room_id,
            player_id=player_id,
            source_revision=rolled.view_revision,
            check_id=rolled.check_run.check_id,
            check_version=rolled.check_run.version,
            option_id="accept-current",
        )
    )

    assert resolved.status == "resolved"
    db_session.expire_all()
    settled = await _committed_state(db_session, room_id)
    # Agenda 稳定之后，父动作剩下的效果接着跑完。
    assert settled.entities["cemetery_figure"]["willing_to_talk"] is True
    # 游标跑完就不该留在 state 里（#398 §阶段一）。
    assert settled.rule_agendas == {}


async def test_a_replayed_check_decision_does_not_run_the_rule_twice(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """重试 / 重连必须幂等：同一个 request_id 不得让规则效果跑第二遍。"""

    room, players, _ = await _start_room(db_session, room_number=96)
    room_id, player_id = room.id, players[0].id
    actor_id = await _arm_first_sight(db_session, room_id)

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _see_true_form(room_id, player_id, actor_id, runtime.revision)
    )
    pending = execution.pending_decision
    assert pending is not None

    request = CheckDecisionRequest(
        request_id="issue398-san-roll",
        room_id=room_id,
        player_id=player_id,
        source_revision=execution.view_revision,
        decision_id=pending.decision_id,
        decision_version=pending.decision_version,
        choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
    )
    first = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([12]))
    ).decide(request)
    replay = await AdjudicationEngineService(engine_store_factory()).decide(request)

    assert replay.check_run == first.check_run
    assert replay.event_refs == first.event_refs


async def _arm_two_rules_on_one_event(db: AsyncSession, room_id: str) -> str:
    """摆成「一条 entity.state_changed 同时点着两条规则」的局面。

    `ghoul_crowd_sanity`（priority 180）与 `first_sight_of_douglas`（120）的触发
    条件互不相干，所以任何一条 `entity.state_changed` 都会同时命中两者——这正是
    #398 失败案例 B。
    """

    game_session = await db.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    actor_id = next(iter(state.actors))
    actor = state.actors[actor_id]
    entities = dict(state.entities)
    entities["ghoul_crowd"] = {**entities.get("ghoul_crowd", {}), "revealed": True}
    entities["cemetery_figure"] = {
        **entities["cemetery_figure"],
        "true_form_seen": True,
    }
    entities["case_tracker"] = {
        **entities["case_tracker"],
        "crowd_sight_resolved": False,
        "first_ghoul_sight_resolved": False,
    }
    entities["favorite_grave"] = {
        **entities.get("favorite_grave", {}),
        "examined": False,
    }
    game_session.state_json = state.model_copy(
        update={
            "entities": entities,
            "actors": {
                actor_id: actor.model_copy(
                    update={"resources": ActorResources(san=55, luck=50)}, deep=True
                )
            },
        },
        deep=True,
    ).to_json_dict()
    await db.commit()
    return actor_id


async def test_two_open_decisions_never_coexist_on_one_action(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """迁移 b8c9d0e1f2a3 的真正验收：一个动作先后挂两次检定。

    旧约束 `uq_pending_check_decisions_room_action` 把「一个动作至多一个检定」
    写死在 schema 里。真正要守的不变量是「同一个动作不能同时挂着两个**未结算**
    的检定」，所以迁移换成了只在 `awaiting_skill_choice` / `rolled` 上生效的条件
    唯一索引。

    要逼出这条路径，得让同一个动作先后要两次检定：第一条决策必须在第二条插入的
    **同一个事务**里被改成 `resolved`（`commit_adjudication` 的
    `additional_decisions` 就是干这个的），否则条件唯一索引当场炸。

    在此之前这条路径在任何一层都没有覆盖：原来那条测试断言 `len(records) == 1`，
    而单独一行在旧约束下同样成立。
    """

    room, players, _ = await _start_room(db_session, room_number=96)
    room_id, player_id = room.id, players[0].id
    actor_id = await _arm_two_rules_on_one_event(db_session, room_id)

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    action_id = "issue398-two-checks"
    execution = await AdjudicationEngineService(store).submit(
        SubmitAdjudicationRequest(
            room_id=room_id,
            player_id=player_id,
            adjudication=ActionAdjudication(
                request_id=action_id,
                source_revision=runtime.revision,
                actor_id=actor_id,
                summary="细看那座常去的坟",
                target=ActionTarget(kind="entity", id="favorite_grave"),
                method=ActionMethod(family="observe", description="俯身细看"),
                check=NoAdjudicationCheck(),
                success_effects=(
                    ChangeEntityStateEffect(entity_id="favorite_grave", key="examined", value=True),
                ),
            ),
        )
    )

    # 优先级高的先挂起。
    assert execution.status == "awaiting_skill_choice"
    first = execution.pending_decision
    assert first is not None

    rolled = await AdjudicationEngineService(
        engine_store_factory(), dice=DiceRoller(SequenceDiceSource([12]))
    ).decide(
        CheckDecisionRequest(
            request_id="issue398-two-checks-roll-1",
            room_id=room_id,
            player_id=player_id,
            source_revision=execution.view_revision,
            decision_id=first.decision_id,
            decision_version=first.decision_version,
            choice=SelectCheckChoice(candidate_id=first.options[0].candidate_id),
        )
    )
    assert rolled.check_run is not None
    second = await AdjudicationEngineService(engine_store_factory()).decide_post_roll(
        PostRollDecisionRequest(
            request_id="issue398-two-checks-accept-1",
            room_id=room_id,
            player_id=player_id,
            source_revision=rolled.view_revision,
            check_id=rolled.check_run.check_id,
            check_version=rolled.check_run.version,
            option_id="accept-current",
        )
    )

    # 第二条规则接着挂起——同一个动作上的第二次检定。
    assert second.status == "awaiting_skill_choice"
    assert second.pending_decision is not None
    assert second.pending_decision.decision_id != first.decision_id
    # 刚掷完的那一骰必须跟着回去，否则 `ws._emit_check_result` 会短路，
    # 玩家看到一个新骰子面板而刚才那次掷骰不存在。
    assert second.check_run is not None
    assert second.check_run.status == "resolved"

    db_session.expire_all()
    records = (
        await db_session.scalars(
            select(PendingCheckDecisionRecord).where(
                PendingCheckDecisionRecord.room_id == room_id,
                PendingCheckDecisionRecord.action_request_id == action_id,
            )
        )
    ).all()
    # 两条决策共享一个 action_request_id——旧的唯一约束会在这里炸。
    assert len(records) == 2
    open_records = [
        record for record in records if record.status in {"awaiting_skill_choice", "rolled"}
    ]
    # 而条件唯一索引要守的那条仍然成立：未结算的只有一条。
    assert len(open_records) == 1
    assert open_records[0].decision_id == second.pending_decision.decision_id

    # `find_pending_check_by_action` 的新排序必须挑出未结算的那条。
    lookup_store = engine_store_factory()
    async with lookup_store.transaction(room_id) as transaction:
        found = await transaction.find_pending_check_by_action(action_id)
    assert found is not None
    assert found.decision_id == second.pending_decision.decision_id


async def test_decisions_written_before_the_origin_split_still_load(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """#483 拆开 `RuleCheckOrigin` 之后，部署前落库的检定必须还能读回来。

    出处（rule/branch/step）与恢复游标（agenda/source_event）拆开时，后两个字段
    从必填变成可选。老行五个字段齐全，新模型照样读得动——这条把 schema version
    压回 1 走一遍读路径，确认版本检查放行、`resumes_agenda` 仍然为真，也就是被动
    检定结算后照旧回 Agenda 走 `result_routes`，而不是被当成主动检定。
    """

    room, players, _ = await _start_room(db_session, room_number=97)
    room_id, player_id = room.id, players[0].id
    actor_id = await _arm_first_sight(db_session, room_id)

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _see_true_form(room_id, player_id, actor_id, runtime.revision)
    )
    pending = execution.pending_decision
    assert pending is not None

    db_session.expire_all()
    record = (
        await db_session.scalars(
            select(PendingCheckDecisionRecord).where(
                PendingCheckDecisionRecord.room_id == room_id,
                PendingCheckDecisionRecord.decision_id == pending.decision_id,
            )
        )
    ).one()
    # 被动路径写出来的 JSON 本来就是老格式（五个字段齐全），把版本号压回 1 就等价
    # 于一条部署前的行。
    origin = dict(record.decision_json["rule_origin"])
    assert set(origin) == {
        "agenda_id",
        "rule_id",
        "branch_id",
        "step_id",
        "source_event_id",
    }
    record.decision_schema_version = 1
    await db_session.commit()

    async with engine_store_factory().transaction(room_id) as transaction:
        reloaded = await transaction.load_pending_check(pending.decision_id)
    assert reloaded is not None
    assert reloaded.rule_origin is not None
    # 恢复游标还在 —— 被动检定结算后仍旧回 Agenda，不会走主动路径的 _finalize_action。
    assert reloaded.rule_origin.resumes_agenda is True
    assert reloaded.rule_origin.agenda_id == origin["agenda_id"]
    assert reloaded.rule_origin.source_event_id == origin["source_event_id"]
