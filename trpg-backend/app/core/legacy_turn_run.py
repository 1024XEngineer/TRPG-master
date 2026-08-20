"""Time-bounded recovery bridge for actions created before TurnRun cutover.

This module is deliberately outside the normal ActionPlan application path. It
never creates or mutates an ActionPlanRun; it only reads the old Engine recovery
projection while the rollout window recorded in the database is still open.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from collaboration_framework.contracts import (
    AdjudicationRecovery,
    GetAdjudicationStatusRequest,
)
from collaboration_framework.engine import AdjudicationEngineService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.engine import TurnRunCutoverRecord


class LegacySingleActionRecoveryAdapter:
    def __init__(
        self,
        *,
        engine: AdjudicationEngineService,
        session_factory: async_sessionmaker[AsyncSession],
        now: Callable[..., datetime] = datetime.now,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._now = now

    async def recover(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationRecovery | None:
        async with self._session_factory() as session:
            window = await session.scalar(
                select(TurnRunCutoverRecord).where(TurnRunCutoverRecord.id == 1)
            )
        if window is None:
            return None
        now = self._now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutover_at = window.cutover_at
        recovery_until = window.legacy_recovery_until
        if cutover_at.tzinfo is None:
            cutover_at = cutover_at.replace(tzinfo=UTC)
        if recovery_until.tzinfo is None:
            recovery_until = recovery_until.replace(tzinfo=UTC)
        if now >= recovery_until:
            return None
        recovery = await self._engine.recover_action(request)
        if recovery is None:
            return None
        created_at = recovery.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if created_at >= cutover_at:
            return None
        return recovery
