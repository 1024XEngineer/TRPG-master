"""Safe deterministic evaluator for the published module expression language."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from collaboration_framework.contracts import (
    ActionRequest,
    ContractError,
    MatchedTarget,
)

_NOT = re.compile(r"!(?!=)")
_LITERALS = re.compile(r"\b(true|false|null)\b")
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_COMPARISON_OPERATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
_EXPRESSION_NAMES = frozenset(
    {
        "action",
        "actor",
        "clock",
        "entities",
        "entity",
        "party",
        "self",
        "target",
    }
)
_CONSTANT_TYPES = (str, int, float, bool, type(None))


@dataclass(frozen=True, slots=True)
class ActionExpressionView:
    actor_id: str
    target_id: str
    type: str
    declarations: frozenset[str]
    initiated_by_target: bool

    def declares(self, declaration: str) -> bool:
        return declaration in self.declarations


def expression_context(
    state: Mapping[str, Any],
    *,
    request: ActionRequest | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Build the stable variable catalog visible to module expressions."""

    entities = state.get("entities", {})
    entity_view = {
        entity_id: {"state": entity_state, **entity_state}
        for entity_id, entity_state in entities.items()
    }
    context: dict[str, Any] = {
        "entity": entity_view,
        "entities": entity_view,
        "clock": state.get(
            "clock",
            {"elapsed_minutes": 0, "time_of_day": "day", "turn": 0},
        ),
        "party": {
            "facts": state.get("discovered_facts", ()),
        },
    }
    if request is None:
        return context

    actor_record = state.get("actors", {}).get(request.actor_id, {})
    actor_state = actor_record.get("state", {})
    resources = actor_record.get("resources", {})
    conditions = tuple(actor_record.get("conditions", ()))
    context["actor"] = {
        "id": request.actor_id,
        "player_id": request.player_id,
        **actor_state,
        **resources,
        "conditions": conditions,
        "temporary_insanity": "temporary_insanity" in conditions,
        "unconscious": "unconscious" in conditions,
    }
    resolved_target: str | None = target_id
    if resolved_target is None and isinstance(request.intent.target, MatchedTarget):
        resolved_target = request.intent.target.id
    target_state = entities.get(resolved_target, {}) if resolved_target else {}
    context["target"] = {
        "id": resolved_target,
        "state": target_state,
        **target_state,
    }
    context["self"] = context["target"]
    context["action"] = ActionExpressionView(
        actor_id=request.actor_id,
        target_id=resolved_target or "",
        type=request.intent.verb,
        declarations=frozenset(request.intent.declarations),
        initiated_by_target=request.intent.initiated_by_target,
    )
    return context


class ExpressionEvaluator:
    """Evaluate a deliberately small AST; Python ``eval`` is never used."""

    def evaluate(self, expression: str, context: Mapping[str, Any]) -> Any:
        tree = self._parse(expression)
        return self._evaluate_node(tree.body, context)

    def validate(self, expression: str) -> None:
        """Reject unsupported syntax before a module enters a running room."""

        self._validate_node(self._parse(expression).body)

    @staticmethod
    def _parse(expression: str) -> ast.Expression:
        normalized = expression.replace("&&", " and ").replace("||", " or ")
        normalized = _NOT.sub(" not ", normalized)
        normalized = _LITERALS.sub(
            lambda match: {
                "true": "True",
                "false": "False",
                "null": "None",
            }[match.group(1)],
            normalized,
        )
        try:
            tree = ast.parse(normalized.strip(), mode="eval")
        except SyntaxError as exc:
            raise ContractError(f"Invalid rule expression: {expression}") from exc
        if not isinstance(tree, ast.Expression):
            raise ContractError("Rule expression must contain one expression")
        return tree

    def matches(self, expression: str, context: Mapping[str, Any]) -> bool:
        result = self.evaluate(expression, context)
        if not isinstance(result, bool):
            raise ContractError("Rule expression must return a boolean")
        return result

    def _evaluate_node(self, node: ast.AST, context: Mapping[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ContractError(f"Unknown expression variable: {node.id}")
            return context[node.id]
        if isinstance(node, ast.Attribute):
            owner = self._evaluate_node(node.value, context)
            return self._attribute(owner, node.attr)
        if isinstance(node, ast.Subscript):
            owner = self._evaluate_node(node.value, context)
            key = self._evaluate_node(node.slice, context)
            try:
                return owner[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise ContractError(f"Unknown expression key: {key!r}") from exc
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._evaluate_node(value, context) for value in node.values)
            if isinstance(node.op, ast.Or):
                return any(self._evaluate_node(value, context) for value in node.values)
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate_node(node.operand, context)
            if isinstance(node.op, ast.Not):
                return not value
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
        if isinstance(node, ast.BinOp):
            operation = _BINARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise ContractError("Unsupported expression arithmetic operator")
            return operation(
                self._evaluate_node(node.left, context),
                self._evaluate_node(node.right, context),
            )
        if isinstance(node, ast.Compare):
            left = self._evaluate_node(node.left, context)
            for operator_node, comparator in zip(
                node.ops,
                node.comparators,
                strict=True,
            ):
                operation = _COMPARISON_OPERATORS.get(type(operator_node))
                if operation is None:
                    raise ContractError("Unsupported expression comparison operator")
                right = self._evaluate_node(comparator, context)
                if not operation(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "declares"
                and not node.keywords
                and len(node.args) == 1
            ):
                owner = self._evaluate_node(node.func.value, context)
                declaration = self._evaluate_node(node.args[0], context)
                if not isinstance(owner, ActionExpressionView) or not isinstance(
                    declaration,
                    str,
                ):
                    raise ContractError("action.declares expects one string")
                return owner.declares(declaration)
            raise ContractError("Unsupported expression function call")
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return tuple(self._evaluate_node(item, context) for item in node.elts)
        raise ContractError(f"Unsupported expression node: {type(node).__name__}")

    def _validate_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, _CONSTANT_TYPES):
                raise ContractError("Unsupported expression constant")
            return
        if isinstance(node, ast.Name):
            if node.id not in _EXPRESSION_NAMES:
                raise ContractError(f"Unknown expression variable: {node.id}")
            return
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ContractError("Private expression attributes are forbidden")
            self._validate_node(node.value)
            return
        if isinstance(node, ast.Subscript):
            self._validate_node(node.value)
            self._validate_node(node.slice)
            return
        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                raise ContractError("Unsupported expression boolean operator")
            for value in node.values:
                self._validate_node(value)
            return
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
                raise ContractError("Unsupported expression unary operator")
            self._validate_node(node.operand)
            return
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _BINARY_OPERATORS:
                raise ContractError("Unsupported expression arithmetic operator")
            self._validate_node(node.left)
            self._validate_node(node.right)
            return
        if isinstance(node, ast.Compare):
            if any(
                type(operation) not in _COMPARISON_OPERATORS for operation in node.ops
            ):
                raise ContractError("Unsupported expression comparison operator")
            self._validate_node(node.left)
            for comparator in node.comparators:
                self._validate_node(comparator)
            return
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "action"
                and node.func.attr == "declares"
                and not node.keywords
                and len(node.args) == 1
            ):
                self._validate_node(node.args[0])
                return
            raise ContractError("Unsupported expression function call")
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for item in node.elts:
                self._validate_node(item)
            return
        raise ContractError(f"Unsupported expression node: {type(node).__name__}")

    @staticmethod
    def _attribute(owner: Any, name: str) -> Any:
        if isinstance(owner, Mapping):
            if name not in owner:
                raise ContractError(f"Unknown expression attribute: {name}")
            return owner[name]
        if isinstance(owner, ActionExpressionView) and name in {
            "actor_id",
            "target_id",
            "type",
            "initiated_by_target",
        }:
            return getattr(owner, name)
        raise ContractError(f"Expression attribute is not accessible: {name}")
