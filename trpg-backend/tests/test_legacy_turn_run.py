from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from collaboration_framework.contracts import GetAdjudicationStatusRequest
from collaboration_framework.engine import AdjudicationEngineService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.legacy_turn_run import LegacySingleActionRecoveryAdapter
from app.models.engine import TurnRunCutoverRecord


class _Session:
    def __init__(self, window: TurnRunCutoverRecord) -> None:
        self.window = window

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def scalar(self, _query):
        return self.window


class _SessionFactory:
    def __init__(self, window: TurnRunCutoverRecord) -> None:
        self.window = window

    def __call__(self):
        return _Session(self.window)


class _Engine:
    def __init__(self, recovery) -> None:
        self.recovery = recovery
        self.calls = 0

    async def recover_action(self, _request):
        self.calls += 1
        return self.recovery


def _request() -> GetAdjudicationStatusRequest:
    return GetAdjudicationStatusRequest(
        room_id="room-1",
        player_id="player-1",
        action_request_id="action-1",
    )


def _recovery(created_at: datetime):
    return SimpleNamespace(
        created_at=created_at,
        actor_id="actor-1",
        execution=SimpleNamespace(status="awaiting_skill_choice"),
    )


@pytest.mark.asyncio
async def test_legacy_adapter_recovers_only_pre_cutover_action() -> None:
    cutover = datetime(2026, 8, 20, tzinfo=UTC)
    now = cutover + timedelta(days=1)
    recovery = _recovery(cutover - timedelta(seconds=1))
    engine = _Engine(recovery)
    adapter = LegacySingleActionRecoveryAdapter(
        engine=cast(AdjudicationEngineService, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            _SessionFactory(
                TurnRunCutoverRecord(
                    id=1,
                    cutover_at=cutover,
                    legacy_recovery_until=cutover + timedelta(days=30),
                )
            ),
        ),
        now=lambda _tz: now,
    )

    assert await adapter.recover(_request()) is recovery
    assert engine.calls == 1


@pytest.mark.asyncio
async def test_legacy_adapter_rejects_new_action_without_creating_a_run() -> None:
    cutover = datetime(2026, 8, 20, tzinfo=UTC)
    engine = _Engine(_recovery(cutover + timedelta(seconds=1)))
    adapter = LegacySingleActionRecoveryAdapter(
        engine=cast(AdjudicationEngineService, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            _SessionFactory(
                TurnRunCutoverRecord(
                    id=1,
                    cutover_at=cutover,
                    legacy_recovery_until=cutover + timedelta(days=30),
                )
            ),
        ),
        now=lambda _tz: cutover + timedelta(days=1),
    )

    assert await adapter.recover(_request()) is None
    assert engine.calls == 1


@pytest.mark.asyncio
async def test_legacy_adapter_rejects_recovery_after_window() -> None:
    cutover = datetime(2026, 8, 20, tzinfo=UTC)
    engine = _Engine(_recovery(cutover - timedelta(seconds=1)))
    adapter = LegacySingleActionRecoveryAdapter(
        engine=cast(AdjudicationEngineService, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            _SessionFactory(
                TurnRunCutoverRecord(
                    id=1,
                    cutover_at=cutover,
                    legacy_recovery_until=cutover + timedelta(days=30),
                )
            ),
        ),
        now=lambda _tz: cutover + timedelta(days=30),
    )

    assert await adapter.recover(_request()) is None
    assert engine.calls == 0
