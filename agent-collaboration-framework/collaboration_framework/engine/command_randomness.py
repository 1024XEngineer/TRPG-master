"""Prepare private randomness durably before the business transaction.

Only entropy (or an explicitly injected test stream) is prepared. Dice facts,
resources, events and continuation still commit atomically. Stable check keys
prevent changing a request id from obtaining a fresh stream after a crash.
"""

from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar
from types import CoroutineType

from collaboration_framework.contracts import (
    ContractError,
    SubmitAdjudicationRequest,
    CheckDecisionRequest,
)
from .dice import DiceRoller

ACTIVE_DICE: ContextVar[DiceRoller | None] = ContextVar(
    "adjudication_dice", default=None
)
ACTIVE_ACTION_ID: ContextVar[str | None] = ContextVar(
    "adjudication_action_id", default=None
)
P = ParamSpec("P")
T = TypeVar("T")


def recoverable_dice(
    method: Callable[P, CoroutineType[Any, Any, T]],
) -> Callable[P, CoroutineType[Any, Any, T]]:
    @wraps(method)
    async def wrapped(self, request, *args, **kwargs):
        async with self._store.transaction(request.room_id) as transaction:
            runtime = await transaction.load_runtime()
            if not any(
                actor.player_id == request.player_id
                for actor in runtime.game_state.actors.values()
            ):
                raise ContractError("IDENTITY_NOT_BOUND")
            if isinstance(request, SubmitAdjudicationRequest):
                action_id = request.adjudication.request_id
            elif isinstance(request, CheckDecisionRequest):
                decision = await transaction.load_pending_check(request.decision_id)
                action_id = decision.action_request_id if decision else None
            else:
                check = await transaction.load_check_run(request.check_id)
                action_id = check.action_request_id if check else None
        if isinstance(request, SubmitAdjudicationRequest):
            key = "action:" + request.adjudication.request_id
        elif isinstance(request, CheckDecisionRequest):
            key = f"decision:{request.decision_id}:{request.decision_version}"
        else:
            key = f"check:{request.check_id}:{request.check_version}"
        snapshot, fresh = await self._store.prepare_randomness(
            room_id=request.room_id,
            operation_key=key,
            create=self._dice.recovery_snapshot,
        )
        token = ACTIVE_DICE.set(self._dice.for_recovery(snapshot, fresh=fresh))
        action_token = ACTIVE_ACTION_ID.set(action_id)
        try:
            return await method(self, request, *args, **kwargs)
        finally:
            ACTIVE_DICE.reset(token)
            ACTIVE_ACTION_ID.reset(action_token)

    return wrapped
