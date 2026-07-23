"""SQLAlchemy 持久化适配器：RoomSession、GameState 与 Module revision。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Scenario, ScenarioRevision
from app.models.event import Event
from app.models.replay import GameStateSnapshot, RoomSession
from app.models.room import Character, Room
from app.module_runtime import ModuleLoader, RuntimeModule
from app.runtime.state import GameState


class RuntimeStateNotFoundError(LookupError):
    pass


class SQLAlchemyGameStateStore:
    async def active_session(self, db: AsyncSession, room_id: str) -> RoomSession | None:
        return await db.scalar(
            select(RoomSession)
            .where(RoomSession.room_id == room_id, RoomSession.status == "active")
            .order_by(RoomSession.created_at.desc())
        )

    async def start_room(
        self,
        db: AsyncSession,
        *,
        room: Room,
        character: Character,
    ) -> tuple[RoomSession, GameState, RuntimeModule]:
        if room.scenario_id is None:
            raise RuntimeStateNotFoundError("房间尚未选择模组")
        scenario = await db.get(Scenario, room.scenario_id)
        if scenario is None or scenario.current_revision_id is None:
            raise RuntimeStateNotFoundError("模组没有可运行 revision")
        revision = await db.get(ScenarioRevision, scenario.current_revision_id)
        if revision is None or revision.status != "ready":
            raise RuntimeStateNotFoundError("模组 revision 不可运行")

        existing = await self.active_session(db, room.id)
        if existing is not None:
            state = await self.load(db, existing.id)
            return existing, state, self.runtime_module(revision)

        session = RoomSession(
            room_id=room.id,
            scenario_revision_id=revision.id,
            status="active",
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        runtime_module = self.runtime_module(revision)
        state = GameState.create(
            room_id=room.id,
            room_session_id=session.id,
            scenario_revision_id=revision.id,
            runtime_module=runtime_module,
            character=character,
        )
        state.event_sequence = 1
        db.add(
            GameStateSnapshot(
                room_session_id=session.id,
                revision=state.revision,
                state=state.model_dump(mode="json"),
            )
        )
        db.add(
            Event(
                room_id=room.id,
                room_session_id=session.id,
                player_id=character.player_id,
                sequence=1,
                event_type="game.started",
                payload={
                    "sceneId": state.current_scene_id,
                    "moduleId": scenario.id,
                },
                visibility="room",
                state_revision=state.revision,
            )
        )
        await db.flush()
        return session, state, runtime_module

    async def load(self, db: AsyncSession, room_session_id: str) -> GameState:
        snapshot = await db.scalar(
            select(GameStateSnapshot).where(
                GameStateSnapshot.room_session_id == room_session_id
            )
        )
        if snapshot is None:
            raise RuntimeStateNotFoundError("游戏状态不存在")
        state = GameState.model_validate(snapshot.state)
        # revision 同时存在于索引列和 JSON；以索引列为准，避免旧数据漂移。
        state.revision = snapshot.revision
        return state

    async def snapshot(
        self, db: AsyncSession, room_session_id: str
    ) -> GameStateSnapshot:
        snapshot = await db.scalar(
            select(GameStateSnapshot)
            .where(GameStateSnapshot.room_session_id == room_session_id)
            .with_for_update()
        )
        if snapshot is None:
            raise RuntimeStateNotFoundError("游戏状态不存在")
        return snapshot

    async def module_for_session(
        self, db: AsyncSession, room_session: RoomSession
    ) -> RuntimeModule:
        if room_session.scenario_revision_id is None:
            raise RuntimeStateNotFoundError("游戏会话没有绑定模组 revision")
        revision = await db.get(ScenarioRevision, room_session.scenario_revision_id)
        if revision is None:
            raise RuntimeStateNotFoundError("模组 revision 不存在")
        return self.runtime_module(revision)

    @staticmethod
    def runtime_module(revision: ScenarioRevision) -> RuntimeModule:
        return ModuleLoader().load_dict(
            revision.package_json,
            checksum=revision.checksum,
            # revision 已在发布/种子阶段通过权利门禁；进行中的房间必须可重放。
            allow_uncleared=True,
        )
