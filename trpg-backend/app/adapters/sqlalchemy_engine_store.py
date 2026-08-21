"""SQLAlchemy implementation of the rule-engine persistence port (issue #121)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime

from collaboration_framework.contracts import (
    ActionRequest,
    ContractError,
)
from collaboration_framework.engine import (
    CheckRun,
    CompletedAction,
    CompletedAdjudicationCommand,
    DomainEvent,
    EngineExecutionResult,
    EngineRuntimeSnapshot,
    EngineStore,
    EngineTransaction,
    GameState,
    PendingCheckDecision,
    RevisionConflictError,
    RuleAgenda,
    StateModifiedEvent,
)
from collaboration_framework.engine.rules_v3 import (
    agenda_claim_key,
    agenda_is_claimable,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.runtime_state import hydrate_actor_state_from_ruleset
from app.core.turn_observability import log_state_changes
from app.models.content import GameSystem
from app.models.engine import (
    ActionExecution,
    AdjudicationCommandExecution,
    CheckRunRecord,
    GameEvent,
    GameSession,
    ModuleVersion,
    PendingCheckDecisionRecord,
)
from app.models.room import Room
from app.service.module_content_cache import load_module_content

# 落库 JSON 的 schema 版本。#310 给 CheckRun / CheckRunView 各加了字段，老行没有
# 这些键，直接 model_validate 会当场失败——正卡在 awaiting_post_roll_decision 的
# 房间一提交奖惩骰决定就炸。读路径按版本升级，写路径一律写当前版本。
_CHECK_RUN_SCHEMA_VERSION = 2
_SUPPORTED_CHECK_RUN_VERSIONS = frozenset({1, _CHECK_RUN_SCHEMA_VERSION})
_ADJUDICATION_RESULT_SCHEMA_VERSION = 3
_SUPPORTED_ADJUDICATION_RESULT_VERSIONS = frozenset({1, 2, _ADJUDICATION_RESULT_SCHEMA_VERSION})


class SqlAlchemyEngineStore(EngineStore):
    """为每个规则引擎事务创建独立数据库 Session 和原子事务。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._before_commit = before_commit

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Application-only access for isolated legacy recovery reads."""

        return self._session_factory

    @asynccontextmanager
    async def transaction(self, room_id: str) -> AsyncIterator[EngineTransaction]:
        async with self._session_factory() as session:
            transaction = _SqlAlchemyEngineTransaction(
                room_id=room_id,
                session=session,
                before_commit=self._before_commit,
            )
            try:
                async with session.begin():
                    yield transaction
            finally:
                transaction.close()
            transaction.log_committed_state_changes()

    async def claim_rule_agenda(
        self,
        *,
        room_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RuleAgenda | None:
        """Lease one runnable Agenda without changing the gameplay revision."""

        if not worker_id or lease_expires_at <= now:
            raise ContractError("RuleAgenda lease 的 worker 与截止时间必须有效")
        async with self._session_factory() as session, session.begin():
            game_session = await session.scalar(
                select(GameSession).where(GameSession.room_id == room_id).with_for_update()
            )
            if game_session is None:
                raise ContractError(f"房间运行时不存在: {room_id}")
            state = GameState.model_validate(deepcopy(game_session.state_json))
            candidates = sorted(
                (
                    agenda
                    for agenda in state.rule_agendas.values()
                    if agenda_is_claimable(agenda, now=now)
                ),
                key=agenda_claim_key,
            )
            if not candidates:
                return None
            current = candidates[0]
            claimed = current.model_copy(
                update={
                    "lease_owner": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "lease_version": current.lease_version + 1,
                },
                deep=True,
            )
            agendas = dict(state.rule_agendas)
            agendas[claimed.agenda_id] = claimed
            state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
            await self._write_agenda_state(
                session,
                game_session=game_session,
                state=state,
                now=now,
            )
            return claimed

    async def checkpoint_rule_agenda(
        self,
        *,
        agenda: RuleAgenda,
        worker_id: str,
        expected_lease_version: int,
        now: datetime,
    ) -> RuleAgenda:
        """CAS a leased cursor/status update into the persisted GameState."""

        async with self._session_factory() as session, session.begin():
            game_session = await session.scalar(
                select(GameSession).where(GameSession.room_id == agenda.room_id).with_for_update()
            )
            if game_session is None:
                raise ContractError(f"房间运行时不存在: {agenda.room_id}")
            state = GameState.model_validate(deepcopy(game_session.state_json))
            current = state.rule_agendas.get(agenda.agenda_id)
            _validate_agenda_checkpoint(
                current=current,
                proposed=agenda,
                worker_id=worker_id,
                expected_lease_version=expected_lease_version,
                now=now,
            )
            terminal = agenda.status != "running"
            saved = agenda.model_copy(
                update={
                    "lease_owner": None if terminal else worker_id,
                    "lease_expires_at": None if terminal else agenda.lease_expires_at,
                    "lease_version": expected_lease_version + 1,
                },
                deep=True,
            )
            agendas = dict(state.rule_agendas)
            agendas[saved.agenda_id] = saved
            state = state.model_copy(update={"rule_agendas": agendas}, deep=True)
            await self._write_agenda_state(
                session,
                game_session=game_session,
                state=state,
                now=now,
            )
            return saved

    @staticmethod
    async def _write_agenda_state(
        session: AsyncSession,
        *,
        game_session: GameSession,
        state: GameState,
        now: datetime,
    ) -> None:
        expected = game_session.agenda_state_version
        result = await session.execute(
            update(GameSession)
            .where(
                GameSession.room_id == game_session.room_id,
                GameSession.agenda_state_version == expected,
            )
            .values(
                state_json=state.to_json_dict(),
                agenda_state_version=expected + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", None) != 1:
            raise RevisionConflictError("RuleAgenda 并发版本已变化")


def _validate_agenda_checkpoint(
    *,
    current: RuleAgenda | None,
    proposed: RuleAgenda,
    worker_id: str,
    expected_lease_version: int,
    now: datetime,
) -> None:
    if current is None:
        raise ContractError(f"RuleAgenda 不存在: {proposed.agenda_id}")
    if (
        current.lease_owner != worker_id
        or current.lease_version != expected_lease_version
        or current.lease_expires_at is None
        or current.lease_expires_at <= now
    ):
        raise RevisionConflictError("RuleAgenda lease 已失效或由其他 worker 持有")
    immutable = (
        "agenda_id",
        "room_id",
        "module_id",
        "module_version",
        "correlation_id",
        "root_source",
    )
    if any(getattr(current, name) != getattr(proposed, name) for name in immutable):
        raise ContractError("RuleAgenda checkpoint 不能改写不可变身份")
    if proposed.lease_owner != worker_id:
        raise ContractError("RuleAgenda checkpoint 的 worker 不匹配")
    if proposed.status == "running" and (
        proposed.lease_expires_at is None or proposed.lease_expires_at <= now
    ):
        raise ContractError("运行中的 RuleAgenda 必须保留有效 lease")


class _SqlAlchemyEngineTransaction(EngineTransaction):
    def __init__(
        self,
        *,
        room_id: str,
        session: AsyncSession,
        before_commit: Callable[[str], None] | None,
    ) -> None:
        self._room_id = room_id
        self._session = session
        self._before_commit = before_commit
        self._closed = False
        self._committed = False
        self._committed_events: tuple[StateModifiedEvent, ...] = ()
        self._committed_request_id: str | None = None

    async def _completed_adjudication_from_record(
        self,
        record: AdjudicationCommandExecution,
    ) -> CompletedAdjudicationCommand:
        if (
            record.request_schema_version != 1
            or record.result_schema_version not in _SUPPORTED_ADJUDICATION_RESULT_VERSIONS
        ):
            raise ContractError("不支持的裁决命令 schema version")
        if record.result_schema_version == 1:
            result_payload = {
                "execution": deepcopy(record.result_json),
                "validation": None,
                "committed_authority_level": None,
                "classification_coverage": "legacy_unknown",
            }
        else:
            result_payload = deepcopy(record.result_json)
        if record.result_schema_version < _ADJUDICATION_RESULT_SCHEMA_VERSION:
            await self._upgrade_embedded_check_run_view(result_payload)
        return CompletedAdjudicationCommand.model_validate(
            {
                "request_id": record.request_id,
                "request": deepcopy(record.request_json),
                "created_at": record.created_at,
                **result_payload,
            }
        )

    async def _upgrade_embedded_check_run_view(self, result_payload: dict) -> None:
        """把老 execution JSON 里内嵌的 CheckRunView 补齐到当前契约（#310）。

        `CheckRunView` 新增了 `selected_skill_id` / `selected_skill_name` /
        `difficulty` / `target_value`。部署之前落库的行没有这四项，直接
        `model_validate` 会当场失败——正卡在 `awaiting_post_roll_decision` 的房间
        一提交奖惩骰决定就炸，恢复路径同样读不回来。

        这四项都是同一次检定的属性，权威副本在 `check_runs` 行上（那张表原本就
        存着 skill_id / difficulty / target_value）。所以从兄弟行补，而不是编一个
        默认值：视图是投影，投影缺字段就回源头取。
        """

        execution = result_payload.get("execution")
        if not isinstance(execution, dict):
            return
        view = execution.get("check_run")
        if not isinstance(view, dict) or "selected_skill_name" in view:
            return
        check_id = view.get("check_id")
        if not isinstance(check_id, str):
            raise ContractError("老 execution JSON 的 check_run 缺少 check_id")
        source = await self.load_check_run(check_id)
        if source is None:
            raise ContractError(f"老 execution JSON 找不到对应的 check_runs 行: {check_id}")
        view["selected_skill_id"] = source.selected_skill_id
        view["selected_skill_name"] = source.selected_skill_name
        view["difficulty"] = source.difficulty
        view["target_value"] = source.target_value

    async def load_runtime(self) -> EngineRuntimeSnapshot:
        self._ensure_active()
        game_session = await self._session.get(GameSession, self._room_id)
        if game_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        if game_session.state_schema_version != 1:
            raise ContractError(
                f"不支持的 GameState schema version: {game_session.state_schema_version}"
            )

        module_version = await self._session.get(
            ModuleVersion,
            (game_session.module_id, game_session.module_version),
        )
        if module_version is None:
            raise ContractError("GameSession 引用的 ModuleVersion 不存在")
        if module_version.content_schema_version != 3:
            raise ContractError(
                f"不支持的 ModuleContent schema version: {module_version.content_schema_version}"
            )

        # 已发布的模组内容不可变，解析结果按 (module_id, version, 内容指纹)
        # 复用；返回值仍与缓存和 content_json 完全隔离 (#347 P4)。
        module_content = load_module_content(
            module_id=module_version.module_id,
            version=module_version.version,
            content_json=module_version.content_json,
        )
        if (
            module_content.module_id != module_version.module_id
            or module_content.version != module_version.version
            or module_content.world_ref != module_version.world_ref
        ):
            raise ContractError("ModuleVersion 列值与 content_json 不一致")

        game_state = GameState.model_validate(deepcopy(game_session.state_json))
        if game_state.room_id != game_session.room_id:
            raise ContractError("GameSession 与 state_json 的 room_id 不一致")
        if game_state.event_sequence != game_session.state_version:
            raise ContractError("GameSession state_version 与 GameState event_sequence 不一致")

        system = await self._session.scalar(
            select(GameSystem).where(GameSystem.world_ref == module_version.world_ref)
        )
        game_state, hydrated = _hydrate_game_state_actor_skills(
            game_state,
            ruleset=system.ruleset if system is not None else None,
        )
        if hydrated:
            state_update = await self._session.execute(
                update(GameSession)
                .where(
                    GameSession.room_id == self._room_id,
                    GameSession.state_version == game_session.state_version,
                    GameSession.agenda_state_version == game_session.agenda_state_version,
                )
                .values(
                    state_json=game_state.to_json_dict(),
                    agenda_state_version=game_session.agenda_state_version + 1,
                    updated_at=datetime.now(UTC),
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(state_update, "rowcount", None) != 1:
                raise RevisionConflictError(
                    f"房间 {self._room_id} 在运行时技能回填期间发生了并发更新"
                )
            await self._session.refresh(game_session)

        return EngineRuntimeSnapshot(
            module_id=module_version.module_id,
            module_version=module_version.version,
            module_content=module_content,
            game_state=game_state,
            revision=str(game_session.state_version),
        )

    async def find_completed_action(
        self,
        request_id: str,
    ) -> CompletedAction | None:
        self._ensure_active()
        execution = await self._session.get(
            ActionExecution,
            (self._room_id, request_id),
        )
        if execution is None:
            return None
        if execution.request_schema_version != 1:
            raise ContractError(
                f"不支持的 ActionRequest schema version: {execution.request_schema_version}"
            )
        if execution.result_schema_version != 1:
            raise ContractError(
                f"不支持的 EngineExecutionResult schema version: {execution.result_schema_version}"
            )

        request = ActionRequest.model_validate(deepcopy(execution.request_json))
        result = EngineExecutionResult.model_validate(deepcopy(execution.result_json))
        if request.room_id != execution.room_id or request.request_id != execution.request_id:
            raise ContractError("ActionExecution 列值与 request_json 不一致")
        if result.action_result.request_id != execution.request_id:
            raise ContractError("ActionExecution request_id 与结果不一致")
        if result.state_version != execution.committed_state_version:
            raise ContractError("ActionExecution committed_state_version 与结果不一致")
        return CompletedAction(request=request, execution=result)

    async def find_adjudication_command(
        self,
        request_id: str,
    ) -> CompletedAdjudicationCommand | None:
        self._ensure_active()
        record = await self._session.get(
            AdjudicationCommandExecution,
            (self._room_id, request_id),
        )
        if record is None:
            return None
        command = await self._completed_adjudication_from_record(record)
        if command.execution.view_revision != str(record.committed_state_version):
            raise ContractError("裁决命令 committed_state_version 与结果不一致")
        return command

    async def find_latest_adjudication_command_by_action(
        self,
        action_request_id: str,
    ) -> CompletedAdjudicationCommand | None:
        self._ensure_active()
        records = list(
            await self._session.scalars(
                select(AdjudicationCommandExecution)
                .where(
                    AdjudicationCommandExecution.room_id == self._room_id,
                    AdjudicationCommandExecution.action_request_id == action_request_id,
                )
                .order_by(AdjudicationCommandExecution.committed_state_version.desc())
            )
        )
        if not records:
            # Rows written before issue #225 have no indexed action_request_id;
            # inspect only those legacy rows and keep the compatibility local.
            records = list(
                await self._session.scalars(
                    select(AdjudicationCommandExecution)
                    .where(
                        AdjudicationCommandExecution.room_id == self._room_id,
                        AdjudicationCommandExecution.action_request_id.is_(None),
                    )
                    .order_by(AdjudicationCommandExecution.committed_state_version.desc())
                )
            )
        for record in records:
            command = await self._completed_adjudication_from_record(record)
            if command.execution.action_request_id != action_request_id:
                continue
            if command.execution.view_revision != str(record.committed_state_version):
                raise ContractError("裁决命令 committed_state_version 与结果不一致")
            return command
        return None

    async def find_pending_check_by_action(
        self,
        action_request_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        # 一个动作可以先后有多次检定（#398 §阶段三：规则能在效果链中间要求一次
        # 被动检定），所以这里不能再靠唯一约束保证只有一行。未结算的那一条永远
        # 优先——调用方要么在问「现在还挂着检定吗」，要么在恢复当前进度。
        record = await self._session.scalar(
            select(PendingCheckDecisionRecord)
            .where(
                PendingCheckDecisionRecord.room_id == self._room_id,
                PendingCheckDecisionRecord.action_request_id == action_request_id,
            )
            .order_by(
                PendingCheckDecisionRecord.status.notin_(("awaiting_skill_choice", "rolled")),
                PendingCheckDecisionRecord.updated_at.desc(),
            )
            .limit(1)
        )
        return self._decision_from_record(record)

    async def load_pending_check(
        self,
        decision_id: str,
    ) -> PendingCheckDecision | None:
        self._ensure_active()
        record = await self._session.get(
            PendingCheckDecisionRecord,
            (self._room_id, decision_id),
        )
        return self._decision_from_record(record)

    async def load_check_run(self, check_id: str) -> CheckRun | None:
        self._ensure_active()
        record = await self._session.get(CheckRunRecord, (self._room_id, check_id))
        if record is None:
            return None
        if record.check_schema_version not in _SUPPORTED_CHECK_RUN_VERSIONS:
            raise ContractError("不支持的 CheckRun schema version")
        payload = deepcopy(record.check_json)
        if record.check_schema_version < _CHECK_RUN_SCHEMA_VERSION:
            # v1 行没有 `selected_skill_name`（#310 新增）。老行里根本没存过显示名，
            # 唯一还原得出来的只有 skill_id——这不是「数据没到位就填个假值」，而是
            # 这条记录当年确实只有这一个可用名称。新写入一律带真实显示名。
            payload.setdefault("selected_skill_name", payload.get("selected_skill_id"))
        check_run = CheckRun.model_validate(payload)
        if (
            check_run.room_id != record.room_id
            or check_run.check_id != record.check_id
            or check_run.status != record.status
            or check_run.version != record.version
            or check_run.roll_count != record.roll_count
        ):
            raise ContractError("CheckRun 列值与 check_json 不一致")
        return check_run

    async def find_active_action_for_player(
        self,
        player_id: str,
    ) -> str | None:
        self._ensure_active()
        check_action_id = await self._session.scalar(
            select(CheckRunRecord.action_request_id)
            .where(
                CheckRunRecord.room_id == self._room_id,
                CheckRunRecord.player_id == player_id,
                CheckRunRecord.status == "awaiting_post_roll_decision",
            )
            .order_by(CheckRunRecord.updated_at.desc())
            .limit(1)
        )
        if check_action_id is not None:
            return check_action_id
        return await self._session.scalar(
            select(PendingCheckDecisionRecord.action_request_id)
            .where(
                PendingCheckDecisionRecord.room_id == self._room_id,
                PendingCheckDecisionRecord.player_id == player_id,
                PendingCheckDecisionRecord.status == "awaiting_skill_choice",
            )
            .order_by(PendingCheckDecisionRecord.updated_at.desc())
            .limit(1)
        )

    async def commit(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None:
        self._ensure_active()
        if self._committed:
            raise ContractError("同一引擎事务只能提交一次")

        expected_version = self._parse_revision(expected_revision)
        current_session = await self._session.get(GameSession, self._room_id)
        if current_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        current_state = GameState.model_validate(deepcopy(current_session.state_json))
        if current_session.state_version != expected_version:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 "
                f"{expected_revision} 更新为 {current_session.state_version}"
            )

        self._validate_commit(
            current_state=current_state,
            new_state=new_state,
            events=events,
            completed_action=completed_action,
        )

        request = completed_action.request
        existing_action = await self._session.get(
            ActionExecution,
            (self._room_id, request.request_id),
        )
        if existing_action is not None:
            raise ContractError(f"request_id 已经提交: {request.request_id}")

        event_ids = tuple(event.event_id for event in events)
        if event_ids:
            existing_event_id = await self._session.scalar(
                select(GameEvent.event_id).where(
                    GameEvent.room_id == self._room_id,
                    GameEvent.event_id.in_(event_ids),
                )
            )
            if existing_event_id is not None:
                raise ContractError(f"Event id 已在房间中存在: {existing_event_id}")

        now = datetime.now(UTC)
        room_values: dict[str, object]
        if new_state.phase == "ended":
            room_values = {
                "phase": "Completed",
                "ended_at": now,
                "updated_at": now,
            }
        else:
            room_values = {
                "phase": "InGame",
                "updated_at": now,
            }
        room_update = await self._session.execute(
            update(Room)
            .where(Room.id == self._room_id, Room.phase == "InGame")
            .values(**room_values)
        )
        if getattr(room_update, "rowcount", None) != 1:
            raise ContractError("房间当前不是可提交动作的 InGame 阶段")

        state_update = await self._session.execute(
            update(GameSession)
            .where(
                GameSession.room_id == self._room_id,
                GameSession.state_version == expected_version,
                GameSession.agenda_state_version == current_session.agenda_state_version,
            )
            .values(
                state_json=new_state.to_json_dict(),
                state_version=new_state.event_sequence,
                agenda_state_version=current_session.agenda_state_version + 1,
                updated_at=now,
            )
        )
        if getattr(state_update, "rowcount", None) != 1:
            raise RevisionConflictError(f"房间 {self._room_id} revision 已不是 {expected_revision}")

        self._session.add_all(
            [
                GameEvent(
                    room_id=self._room_id,
                    sequence=event.sequence,
                    event_id=event.event_id,
                    client_action_id=event.client_action_id,
                    type=event.type,
                    actor_id=event.actor_id,
                    visibility=event.visibility,
                    cause=event.cause,
                    event_schema_version=1,
                    payload=event.payload.to_json_dict(),
                    created_at=now,
                )
                for event in events
            ]
        )
        self._session.add(
            ActionExecution(
                room_id=self._room_id,
                request_id=request.request_id,
                request_schema_version=1,
                request_json=request.to_json_dict(),
                result_schema_version=1,
                result_json=completed_action.execution.to_json_dict(),
                committed_state_version=new_state.event_sequence,
                created_at=now,
            )
        )

        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ContractError("规则引擎提交与已持久化记录冲突") from exc

        if self._before_commit is not None:
            self._before_commit(self._room_id)
        self._committed_events = events
        self._committed_request_id = request.request_id
        self._committed = True

    async def commit_adjudication(
        self,
        *,
        expected_revision: str,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        decision: PendingCheckDecision | None,
        check_run: CheckRun | None,
        completed_command: CompletedAdjudicationCommand,
        additional_decisions: tuple[PendingCheckDecision, ...] = (),
    ) -> None:
        self._ensure_active()
        if self._committed:
            raise ContractError("同一引擎事务只能提交一次")
        expected_version = self._parse_revision(expected_revision)
        current_session = await self._session.get(GameSession, self._room_id)
        if current_session is None:
            raise ContractError(f"房间运行时不存在: {self._room_id}")
        current_state = GameState.model_validate(deepcopy(current_session.state_json))
        if current_session.state_version != expected_version:
            raise RevisionConflictError(
                f"房间 {self._room_id} revision 已从 {expected_revision} "
                f"更新为 {current_session.state_version}"
            )
        self._validate_adjudication_commit(
            current_state=current_state,
            new_state=new_state,
            events=events,
            completed_command=completed_command,
        )
        existing_command = await self._session.get(
            AdjudicationCommandExecution,
            (self._room_id, completed_command.request_id),
        )
        if existing_command is not None:
            raise ContractError(f"裁决 request_id 已经提交: {completed_command.request_id}")
        event_ids = tuple(event.event_id for event in events)
        existing_event_id = await self._session.scalar(
            select(GameEvent.event_id).where(
                GameEvent.room_id == self._room_id,
                GameEvent.event_id.in_(event_ids),
            )
        )
        if existing_event_id is not None:
            raise ContractError(f"Event id 已在房间中存在: {existing_event_id}")

        now = datetime.now(UTC)
        room_values: dict[str, object] = {
            "phase": "Completed" if new_state.phase == "ended" else "InGame",
            "updated_at": now,
        }
        if new_state.phase == "ended":
            room_values["ended_at"] = now
        room_update = await self._session.execute(
            update(Room)
            .where(Room.id == self._room_id, Room.phase == "InGame")
            .values(**room_values)
        )
        if getattr(room_update, "rowcount", None) != 1:
            raise ContractError("房间当前不是可提交裁决的 InGame 阶段")
        state_update = await self._session.execute(
            update(GameSession)
            .where(
                GameSession.room_id == self._room_id,
                GameSession.state_version == expected_version,
                GameSession.agenda_state_version == current_session.agenda_state_version,
            )
            .values(
                state_json=new_state.to_json_dict(),
                state_version=new_state.event_sequence,
                agenda_state_version=current_session.agenda_state_version + 1,
                updated_at=now,
            )
        )
        if getattr(state_update, "rowcount", None) != 1:
            raise RevisionConflictError(f"房间 {self._room_id} revision 已不是 {expected_revision}")
        self._session.add_all(
            [
                GameEvent(
                    room_id=self._room_id,
                    sequence=event.sequence,
                    event_id=event.event_id,
                    client_action_id=event.client_action_id,
                    type=event.type,
                    actor_id=event.actor_id,
                    visibility=event.visibility,
                    cause=event.cause,
                    event_schema_version=1,
                    payload=deepcopy(event.payload),
                    created_at=now,
                )
                for event in events
            ]
        )
        if decision is not None:
            await self._save_decision(decision, now)
        for extra in additional_decisions:
            await self._save_decision(extra, now)
        if check_run is not None:
            await self._save_check_run(check_run, now)
        self._session.add(
            AdjudicationCommandExecution(
                room_id=self._room_id,
                request_id=completed_command.request_id,
                action_request_id=completed_command.execution.action_request_id,
                request_schema_version=1,
                request_json=completed_command.request.to_json_dict(),
                result_schema_version=_ADJUDICATION_RESULT_SCHEMA_VERSION,
                result_json={
                    "execution": completed_command.execution.to_json_dict(),
                    "validation": (
                        completed_command.validation.to_json_dict()
                        if completed_command.validation is not None
                        else None
                    ),
                    "committed_authority_level": (completed_command.committed_authority_level),
                    "classification_coverage": (completed_command.classification_coverage),
                },
                committed_state_version=new_state.event_sequence,
                created_at=now,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ContractError("规则引擎裁决提交与已持久化记录冲突") from exc
        if self._before_commit is not None:
            self._before_commit(self._room_id)
        self._committed = True

    def close(self) -> None:
        self._closed = True

    def log_committed_state_changes(self) -> None:
        """仅在 SQLAlchemy 事务真正提交成功后输出状态修改。"""

        if not self._committed or self._committed_request_id is None:
            return
        log_state_changes(
            room_id=self._room_id,
            correlation_id=self._committed_request_id,
            events=self._committed_events,
        )

    def _ensure_active(self) -> None:
        if self._closed:
            raise ContractError("引擎事务已经关闭")

    @staticmethod
    def _parse_revision(revision: str) -> int:
        try:
            value = int(revision)
        except ValueError as exc:
            raise ContractError(f"非法 revision: {revision}") from exc
        if value < 0 or str(value) != revision:
            raise ContractError(f"非法 revision: {revision}")
        return value

    def _validate_commit(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[StateModifiedEvent, ...],
        completed_action: CompletedAction,
    ) -> None:
        if current_state.room_id != self._room_id or new_state.room_id != self._room_id:
            raise ContractError("提交的 GameState 与事务房间不一致")

        request = completed_action.request
        request_id = request.request_id
        if request.room_id != self._room_id:
            raise ContractError("CompletedAction 与事务房间不一致")
        if completed_action.execution.events != events:
            raise ContractError("CompletedAction 的 Event 与提交 Event 不一致")
        if completed_action.execution.state_version != new_state.event_sequence:
            raise ContractError("EngineExecutionResult 与 GameState 版本不一致")
        if completed_action.execution.action_result.request_id != request_id:
            raise ContractError("ActionResult 与 CompletedAction request_id 不一致")
        if completed_action.execution.action_result.event_refs != tuple(
            event.event_id for event in events
        ):
            raise ContractError("ActionResult 的 Event 引用与提交 Event 不一致")

        first_sequence = current_state.event_sequence + 1
        expected_sequences = tuple(range(first_sequence, first_sequence + len(events)))
        if tuple(event.sequence for event in events) != expected_sequences:
            raise ContractError("提交的 Event sequence 必须在房间内连续递增")
        if new_state.event_sequence != current_state.event_sequence + len(events):
            raise ContractError("GameState event_sequence 与提交 Event 数量不一致")
        if not events and new_state != current_state:
            raise ContractError("无 Event 的提交不得修改 GameState")

        event_ids = tuple(event.event_id for event in events)
        if len(event_ids) != len(set(event_ids)):
            raise ContractError("同一次提交的 Event id 必须唯一")
        for event in events:
            if event.room_id != self._room_id:
                raise ContractError("Event 与事务房间不一致")
            if event.client_action_id != request_id:
                raise ContractError("Event 与 CompletedAction request_id 不一致")
            if event.actor_id != request.actor_id:
                raise ContractError("Event 与 CompletedAction actor_id 不一致")

    def _validate_adjudication_commit(
        self,
        *,
        current_state: GameState,
        new_state: GameState,
        events: tuple[DomainEvent, ...],
        completed_command: CompletedAdjudicationCommand,
    ) -> None:
        if current_state.room_id != self._room_id or new_state.room_id != self._room_id:
            raise ContractError("提交的 GameState 与裁决事务房间不一致")
        if not events:
            raise ContractError("裁决提交必须至少产生一个领域 Event")
        first_sequence = current_state.event_sequence + 1
        expected_sequences = tuple(range(first_sequence, first_sequence + len(events)))
        if tuple(event.sequence for event in events) != expected_sequences:
            raise ContractError("领域 Event sequence 必须连续递增")
        if new_state.event_sequence != current_state.event_sequence + len(events):
            raise ContractError("GameState event_sequence 与领域 Event 数量不一致")
        event_ids = tuple(event.event_id for event in events)
        if len(event_ids) != len(set(event_ids)):
            raise ContractError("同一次裁决的 Event id 必须唯一")
        for event in events:
            if event.room_id != self._room_id:
                raise ContractError("领域 Event 与事务房间不一致")
            if event.client_action_id != completed_command.request_id:
                raise ContractError("领域 Event 与裁决命令 request_id 不一致")
        if completed_command.execution.view_revision != str(new_state.event_sequence):
            raise ContractError("裁决结果 revision 与 GameState 不一致")

    @staticmethod
    def _decision_from_record(
        record: PendingCheckDecisionRecord | None,
    ) -> PendingCheckDecision | None:
        if record is None:
            return None
        if record.decision_schema_version != 1:
            raise ContractError("不支持的 PendingCheckDecision schema version")
        decision = PendingCheckDecision.model_validate(deepcopy(record.decision_json))
        if (
            decision.room_id != record.room_id
            or decision.decision_id != record.decision_id
            or decision.action_request_id != record.action_request_id
            or decision.status != record.status
            or decision.decision_version != record.decision_version
        ):
            raise ContractError("PendingCheckDecision 列值与 decision_json 不一致")
        return decision

    async def _save_decision(
        self,
        decision: PendingCheckDecision,
        now: datetime,
    ) -> None:
        record = await self._session.get(
            PendingCheckDecisionRecord,
            (self._room_id, decision.decision_id),
        )
        if record is None:
            self._session.add(
                PendingCheckDecisionRecord(
                    room_id=self._room_id,
                    decision_id=decision.decision_id,
                    action_request_id=decision.action_request_id,
                    player_id=decision.player_id,
                    actor_id=decision.actor_id,
                    status=decision.status,
                    decision_version=decision.decision_version,
                    decision_schema_version=1,
                    decision_json=decision.to_json_dict(),
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        record.status = decision.status
        record.decision_version = decision.decision_version
        record.decision_json = decision.to_json_dict()
        record.updated_at = now

    async def _save_check_run(self, check_run: CheckRun, now: datetime) -> None:
        record = await self._session.get(
            CheckRunRecord,
            (self._room_id, check_run.check_id),
        )
        if record is None:
            self._session.add(
                CheckRunRecord(
                    room_id=self._room_id,
                    check_id=check_run.check_id,
                    decision_id=check_run.decision_id,
                    action_request_id=check_run.action_request_id,
                    player_id=check_run.player_id,
                    actor_id=check_run.actor_id,
                    status=check_run.status,
                    version=check_run.version,
                    roll_count=check_run.roll_count,
                    check_schema_version=_CHECK_RUN_SCHEMA_VERSION,
                    check_json=check_run.to_json_dict(),
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        record.status = check_run.status
        record.version = check_run.version
        record.roll_count = check_run.roll_count
        record.check_schema_version = _CHECK_RUN_SCHEMA_VERSION
        record.check_json = check_run.to_json_dict()
        record.updated_at = now


def _hydrate_game_state_actor_skills(
    game_state: GameState,
    *,
    ruleset: dict | None,
) -> tuple[GameState, bool]:
    actors = dict(game_state.actors)
    changed = False
    for actor_id, actor in game_state.actors.items():
        actor_state, actor_changed = hydrate_actor_state_from_ruleset(
            actor.state,
            ruleset,
        )
        if not actor_changed:
            continue
        actors[actor_id] = actor.model_copy(update={"state": actor_state})
        changed = True
    if not changed:
        return game_state, False
    return game_state.model_copy(update={"actors": actors}), True
