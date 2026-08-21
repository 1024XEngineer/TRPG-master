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

    # 这条决策必须真的落库。原来的 uq_pending_check_decisions_room_action 唯一
    # 约束会在这里炸掉——父动作虽然没掷骰，但同一个 action_request_id 上先后
    # 出现两条决策的能力正是迁移 b8c9d0e1f2a3 放开的。
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
