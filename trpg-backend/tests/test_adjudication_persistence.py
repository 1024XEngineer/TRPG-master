from collections.abc import Callable

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    CheckDecisionRequest,
    RequiredAdjudicationCheck,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    SequenceDiceSource,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.models.engine import (
    AdjudicationCommandExecution,
    CheckRunRecord,
    GameEvent,
    PendingCheckDecisionRecord,
)
from tests.test_engine_runtime import _start_room


async def test_pending_check_and_authoritative_roll_survive_service_rebuild(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    store = engine_store_factory()
    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    information_id = sorted(runtime.canon_information_ids)[0]
    request = SubmitAdjudicationRequest(
        room_id=room.id,
        player_id=players[0].id,
        adjudication=ActionAdjudication(
            request_id="sql-action-212",
            source_revision=runtime.revision,
            actor_id=actor_id,
            summary="检查已知材料",
            target=ActionTarget(kind="information", id=information_id),
            method=ActionMethod(family="research", description="逐项核对材料"),
            check=RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="spot-candidate",
                        skill_id="spot-hidden",
                        difficulty="regular",
                        method_summary="仔细观察材料",
                        player_safe_reason="侧重发现异常细节",
                    ),
                )
            ),
        ),
    )
    pending = await AdjudicationEngineService(store).submit(request)
    assert pending.pending_decision is not None
    decision_request = CheckDecisionRequest(
        request_id="sql-choice-212",
        room_id=room.id,
        player_id=players[0].id,
        source_revision=pending.view_revision,
        decision_id=pending.pending_decision.decision_id,
        decision_version=pending.pending_decision.decision_version,
        choice=SelectCheckChoice(candidate_id="spot-candidate"),
    )

    rolled = await AdjudicationEngineService(
        engine_store_factory(),
        dice=DiceRoller(SequenceDiceSource([64])),
    ).decide(decision_request)
    replay = await AdjudicationEngineService(engine_store_factory()).decide(decision_request)

    assert rolled.check_run is not None
    assert rolled.check_run.roll.value == 64
    assert replay.check_run == rolled.check_run
    decisions = (
        await db_session.scalars(
            select(PendingCheckDecisionRecord).where(PendingCheckDecisionRecord.room_id == room.id)
        )
    ).all()
    runs = (
        await db_session.scalars(select(CheckRunRecord).where(CheckRunRecord.room_id == room.id))
    ).all()
    commands = (
        await db_session.scalars(
            select(AdjudicationCommandExecution).where(
                AdjudicationCommandExecution.room_id == room.id
            )
        )
    ).all()
    events = (
        await db_session.scalars(
            select(GameEvent).where(GameEvent.room_id == room.id).order_by(GameEvent.sequence)
        )
    ).all()
    assert [decision.status for decision in decisions] == ["rolled"]
    assert [run.check_json["roll"]["value"] for run in runs] == [64]
    assert len(commands) == 2
    assert {command.result_schema_version for command in commands} == {3}
    assert all(
        "committed_authority_level" in command.result_json
        and "classification_coverage" in command.result_json
        and "execution" in command.result_json
        for command in commands
    )
    assert all(
        "authority_level" not in command.result_json["execution"]
        and "committed_authority_level" not in command.result_json["execution"]
        for command in commands
    )
    assert [event.type for event in events] == ["check.choice_requested", "check.rolled"]


async def test_checks_persisted_before_the_skill_name_field_still_load(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """部署前落库、正卡在奖惩骰决定上的检定必须还能读回来（#310 review 指出）。

    `CheckRun` 新增了 `selected_skill_name`，`CheckRunView` 新增了四个字段。老行
    没有这些键，读路径若直接 `model_validate` 就会当场炸——玩家一提交奖惩骰决定
    就失败，恢复路径同样读不回来。这里把真实写出来的行**降级**回老格式，再走一
    遍读取。
    """

    room, players, _ = await _start_room(db_session, prepare_checkpoint=False)
    store = engine_store_factory()
    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
    actor_id = next(
        actor_id
        for actor_id, actor in runtime.game_state.actors.items()
        if actor.player_id == players[0].id
    )
    information_id = sorted(runtime.canon_information_ids)[0]
    submitted = await AdjudicationEngineService(store).submit(
        SubmitAdjudicationRequest(
            room_id=room.id,
            player_id=players[0].id,
            adjudication=ActionAdjudication(
                request_id="legacy-action-310",
                source_revision=runtime.revision,
                actor_id=actor_id,
                summary="检查已知材料",
                target=ActionTarget(kind="information", id=information_id),
                method=ActionMethod(family="research", description="逐项核对材料"),
                check=RequiredAdjudicationCheck(
                    candidates=(
                        SkillCheckCandidate(
                            candidate_id="spot-candidate",
                            skill_id="spot-hidden",
                            difficulty="regular",
                            method_summary="仔细观察材料",
                            player_safe_reason="侧重发现异常细节",
                        ),
                    )
                ),
            ),
        )
    )
    assert submitted.pending_decision is not None
    rolled = await AdjudicationEngineService(
        engine_store_factory(),
        dice=DiceRoller(SequenceDiceSource([64])),
    ).decide(
        CheckDecisionRequest(
            request_id="legacy-choice-310",
            room_id=room.id,
            player_id=players[0].id,
            source_revision=submitted.view_revision,
            decision_id=submitted.pending_decision.decision_id,
            decision_version=submitted.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot-candidate"),
        )
    )
    assert rolled.check_run is not None

    # 把行降级成本次改动之前的样子。
    run_record = (
        await db_session.scalars(select(CheckRunRecord).where(CheckRunRecord.room_id == room.id))
    ).one()
    legacy_check_json = dict(run_record.check_json)
    legacy_check_json.pop("selected_skill_name")
    run_record.check_json = legacy_check_json
    run_record.check_schema_version = 1

    command_records = (
        await db_session.scalars(
            select(AdjudicationCommandExecution).where(
                AdjudicationCommandExecution.room_id == room.id
            )
        )
    ).all()
    for command_record in command_records:
        result_json = dict(command_record.result_json)
        execution = result_json.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("check_run"), dict):
            view = dict(execution["check_run"])
            for field in (
                "selected_skill_id",
                "selected_skill_name",
                "difficulty",
                "target_value",
            ):
                view.pop(field, None)
            result_json["execution"] = {**execution, "check_run": view}
            command_record.result_json = result_json
        command_record.result_schema_version = 2
    await db_session.commit()

    # 读路径要能把老行升上来，而不是抛 ValidationError。
    reloaded_store = engine_store_factory()
    async with reloaded_store.transaction(room.id) as transaction:
        reloaded_run = await transaction.load_check_run(rolled.check_run.check_id)
        replayed = await transaction.find_adjudication_command("legacy-choice-310")

    assert reloaded_run is not None
    # 老行从没存过显示名，唯一还原得出来的就是 skill_id。
    assert reloaded_run.selected_skill_name == reloaded_run.selected_skill_id
    assert reloaded_run.target_value == rolled.check_run.target_value
    assert reloaded_run.roll.value == 64

    assert replayed is not None
    assert replayed.execution.check_run is not None
    # 内嵌视图从兄弟行补齐，而不是编默认值：target_value / difficulty 都是老行本来
    # 就存着的真值。显示名两张行当年都没存过，所以只能落到 skill_id——生产上这两
    # 张行必然同为老数据，这就是真实情形。
    assert replayed.execution.check_run.target_value == rolled.check_run.target_value
    assert replayed.execution.check_run.difficulty == rolled.check_run.difficulty
    assert replayed.execution.check_run.selected_skill_id == rolled.check_run.selected_skill_id
    assert replayed.execution.check_run.selected_skill_name == rolled.check_run.selected_skill_id
