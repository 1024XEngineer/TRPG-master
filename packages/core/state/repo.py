"""GameStateRepo —— 对应 master §4.5 `interface GameStateRepo`。

★ 跨房间隔离唯一入口（通信铁律二，ADR-13）：characters/players/notes/events/
entity_states 一律经此读写，不绕行直查表。下游 RulesEngine/ViewProjector 全部
只操作 GameStateRepo.load() 返回的这一个内存对象。`load`/`save` 是 async——
真实实现要做真实数据库 I/O，同步接口会阻塞事件循环。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import select

from core.state.db_models import CharacterRow, PlayerRow, RoomRow
from core.state.models import GameState, PlayerState
from core.db import get_sessionmaker


@runtime_checkable
class GameStateRepo(Protocol):
    async def load(self, room_id: str) -> GameState:
        ...

    async def save(self, state: GameState) -> None:
        ...


class StubGameStateRepo:
    """骨架阶段桩实现——真实实现需要走 PostgreSQL（ADR-17）+ roomId 已验证前提。"""

    async def load(self, room_id: str) -> GameState:
        raise NotImplementedError("GameStateRepo.load: 待接入 PostgreSQL")

    async def save(self, state: GameState) -> None:
        raise NotImplementedError("GameStateRepo.save: 待接入 PostgreSQL")


class SqlAlchemyGameStateRepo:
    """真实实现（ADR-17：PostgreSQL）。"""

    async def load(self, room_id: str) -> GameState:
        async with get_sessionmaker()() as session:
            room = await session.get(RoomRow, room_id)
            if room is None:
                raise ValueError(f"room not found: {room_id}")

            player_rows = (
                await session.execute(select(PlayerRow).where(PlayerRow.room_id == room_id))
            ).scalars().all()

            players: list[PlayerState] = []
            for p in player_rows:
                if p.character_id is None:
                    continue  # 建卡未完成，尚无 location/SAN 可投影
                character = await session.get(CharacterRow, p.character_id)
                assert character is not None
                players.append(
                    PlayerState(
                        player_id=p.id,
                        character_id=character.id,
                        location=character.location,
                        san=character.derived_stats.get("SAN", 0),
                        unknown_streak=p.unknown_streak,
                    )
                )

            return GameState(
                room_id=room.id,
                module_id=room.module_pack_id,
                phase=room.phase,
                players=players,
                entity_states=room.entity_states,
                rolling_summary=room.rolling_summary,
            )

    async def save(self, state: GameState) -> None:
        async with get_sessionmaker()() as session:
            room = await session.get(RoomRow, state.room_id)
            if room is None:
                raise ValueError(f"room not found: {state.room_id}")
            room.phase = state.phase
            room.entity_states = state.entity_states
            room.rolling_summary = state.rolling_summary

            for ps in state.players:
                player = await session.get(PlayerRow, ps.player_id)
                character = await session.get(CharacterRow, ps.character_id)
                assert player is not None and character is not None
                player.unknown_streak = ps.unknown_streak
                character.location = ps.location
                character.derived_stats = {**character.derived_stats, "SAN": ps.san}

            await session.commit()
