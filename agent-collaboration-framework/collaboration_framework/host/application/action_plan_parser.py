"""Deterministic validation for untrusted HostTurnDecision JSON."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from collaboration_framework.contracts import (
    ActionPlan,
    ActionPlanPolicy,
    ContractError,
    HostTurnDecision,
)

_DECISION_ADAPTER = TypeAdapter(HostTurnDecision)


class HostTurnDecisionParser:
    @staticmethod
    def parse(
        raw: object,
        *,
        policy: ActionPlanPolicy | None = None,
    ) -> HostTurnDecision:
        try:
            decision = _DECISION_ADAPTER.validate_python(raw)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ContractError("HostTurnDecision 未通过结构校验") from exc
        if isinstance(decision, ActionPlan):
            (policy or ActionPlanPolicy()).require_plan(decision)
        return decision
