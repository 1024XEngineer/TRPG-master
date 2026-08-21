"""RuleAgenda 卫生与失败语义在真实持久化链路上的行为（#398 §阶段一）。

框架侧的单元覆盖在 `agent-collaboration-framework/tests/test_rule_agenda_v3.py`。
这里补的是它证明不了的那一半：`rule_agendas` 活在 `GameSession.state_json` 里，
所以「只落在途 Agenda」「存量死数据被扫掉」必须在真的写过一次数据库之后再读回来
断言；`rule.agenda_failed` 也必须真的落进 `game_events` 表才算可审计。
"""

from __future__ import annotations

import copy
from collections.abc import Callable

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    AgendaItem,
    AgendaSource,
    GameState,
    RuleAgenda,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.models.engine import GameEvent, GameSession, ModuleVersion
from tests.test_engine_runtime import _start_room

# 《追书人》里唯一一条不掷骰、跑完就 stable 的 event 规则：看到墓地探访之后，
# 锁着且完好的书房窗户会被撞开。
TRIGGER_RULE = "locked_study_window_breaks"


async def _prepare_window(db: AsyncSession, room_id: str) -> str:
    """把房间摆成「触发 TRIGGER_RULE 只差最后一步」的样子，返回 actor_id。"""

    game_session = await db.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    entities = dict(state.entities)
    entities["cemetery_figure"] = {
        **entities["cemetery_figure"],
        "visit_observed": False,
    }
    entities["study_window"] = {
        **entities.get("study_window", {}),
        "locked": True,
        "broken": False,
    }
    game_session.state_json = state.model_copy(
        update={"entities": entities}, deep=True
    ).to_json_dict()
    await db.commit()
    return next(iter(state.actors))


def _observe_visit(room_id: str, player_id: str, actor_id: str, revision: str):
    return SubmitAdjudicationRequest(
        room_id=room_id,
        player_id=player_id,
        adjudication=ActionAdjudication(
            request_id="issue398-observe",
            source_revision=revision,
            actor_id=actor_id,
            summary="留意墓地里的探访",
            target=ActionTarget(kind="entity", id="cemetery_figure"),
            method=ActionMethod(family="observe", description="远远看着"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="cemetery_figure",
                    key="visit_observed",
                    value=True,
                ),
            ),
        ),
    )


def _dead_agenda(agenda_id: str, room_id: str, session: GameSession, status: str):
    return RuleAgenda(
        agenda_id=agenda_id,
        room_id=room_id,
        module_id=session.module_id,
        module_version=session.module_version,
        correlation_id=f"correlation-{agenda_id}",
        root_source=AgendaSource(kind="action", id=f"action-{agenda_id}"),
        revision=str(session.state_version),
        status=status,
        failure_code="agenda_budget_exceeded" if status == "failed" else None,
        queue=(
            AgendaItem(
                source_event_id=f"event-{agenda_id}",
                event_sequence=1,
                rule_id=TRIGGER_RULE,
                rule_priority=80,
                branch_id="default",
                status="completed" if status == "stable" else "failed",
            ),
        ),
    )


async def test_settled_agendas_never_reach_the_database(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session, room_number=93)
    room_id, player_id = room.id, players[0].id
    actor_id = await _prepare_window(db_session, room_id)

    # 存量房间里已经积下的死数据：一条跑完的、一条失败的。
    game_session = await db_session.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    stale = {
        item.agenda_id: item
        for item in (
            _dead_agenda("dead-stable", room_id, game_session, "stable"),
            _dead_agenda("dead-failed", room_id, game_session, "failed"),
        )
    }
    game_session.state_json = state.model_copy(
        update={"rule_agendas": stale}, deep=True
    ).to_json_dict()
    await db_session.commit()

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _observe_visit(room_id, player_id, actor_id, runtime.revision)
    )

    assert execution.status == "resolved"
    assert execution.rule_failure_code is None

    db_session.expire_all()
    reloaded = await db_session.get(GameSession, room_id)
    assert reloaded is not None
    committed = GameState.model_validate(reloaded.state_json)
    # 规则确实跑了。
    assert committed.entities["study_window"]["broken"] is True
    # 跑完即 stable，不落库；连带把存量死数据一起扫掉。
    assert committed.rule_agendas == {}


async def test_step_without_executor_commits_an_auditable_failure(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """把一条**能到达**的 event 规则改成停在没有执行器的 step 上。

    模组自带的 `invoke_ruleset_action` 只出现在 `temporary_insanity_leads_to_asylum`
    里，而没有任何效果会发出 `actor.temporary_insanity`——它在当前内容里根本到不了，
    所以用它无法覆盖这条路径。
    """

    room, players, _ = await _start_room(db_session, room_number=94)
    room_id, player_id = room.id, players[0].id
    actor_id = await _prepare_window(db_session, room_id)

    game_session = await db_session.get(GameSession, room_id)
    assert game_session is not None
    published = await db_session.get(
        ModuleVersion, (game_session.module_id, game_session.module_version)
    )
    assert published is not None

    content = copy.deepcopy(published.content_json)
    patched_version = f"{published.version}+issue398"
    content["version"] = patched_version
    rule = next(item for item in content["rules"] if item["id"] == TRIGGER_RULE)
    steps = rule["execution"]["steps"]
    next(step for step in steps if step["id"] == "break_window")["next_step_id"] = "apply_condition"
    steps.append(
        {
            "id": "apply_condition",
            "kind": "invoke_ruleset_action",
            "action_id": "coc7.apply_condition",
            "actor_binding": "actor",
            "parameters": {"condition": "unconscious"},
            "next_step_id": "finish",
        }
    )
    db_session.add(
        ModuleVersion(
            module_id=published.module_id,
            version=patched_version,
            world_ref=published.world_ref,
            content_schema_version=published.content_schema_version,
            content_json=content,
        )
    )
    game_session.module_version = patched_version
    await db_session.commit()

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()
    execution = await AdjudicationEngineService(store).submit(
        _observe_visit(room_id, player_id, actor_id, runtime.revision)
    )

    # 此前：execution 报 resolved，Agenda 停在 running 上，无人推进也无任何信号。
    assert execution.status == "rule_failed"
    assert execution.rule_failure_code == "step_kind_has_no_executor"
    # 动作本身成功了——是它触发的规则链没跑完，两件事分开记。
    assert execution.outcome == "success"

    db_session.expire_all()
    reloaded = await db_session.get(GameSession, room_id)
    assert reloaded is not None
    assert GameState.model_validate(reloaded.state_json).rule_agendas == {}

    failures = (
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == room_id,
                GameEvent.type == "rule.agenda_failed",
            )
        )
    ).all()
    assert len(failures) == 1
    failure = failures[0]
    assert failure.visibility == "hidden"
    assert failure.payload["failure_code"] == "step_kind_has_no_executor"
    assert failure.payload["rule_id"] == TRIGGER_RULE
    assert failure.payload["step_id"] == "apply_condition"
    assert failure.event_id in execution.event_refs
    assert failure.event_id not in execution.public_event_refs
