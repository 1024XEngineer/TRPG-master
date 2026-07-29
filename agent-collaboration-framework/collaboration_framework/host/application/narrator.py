"""Application-level validation for player-visible narration."""

from __future__ import annotations

import re
from typing import Literal

from collaboration_framework.contracts import ContractError
from collaboration_framework.host.ports import NarrationModelPort
from collaboration_framework.host.schemas import NarrationContext, NarrationOutput

NarrationRejectionReason = Literal[
    "outer_schema",
    "fact_scope",
    "protocol_tail",
    "schema_fragment",
]

_NARRATION_FIELD = (
    r"(?<![A-Za-z0-9_])"
    r"(?:kind|text|claimed_fact_ids|claimedFactIds|suggested_actions|suggestedActions)"
    r"(?![A-Za-z0-9_])"
)
_QUOTED_NARRATION_FIELD = rf"""(?:"|')?{_NARRATION_FIELD}(?:"|')?"""
_STRUCTURED_VALUE = r"(?:\[[\s\S]*?\]|\{[\s\S]*?\}|null)"
_QUOTED_STRING_VALUE = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
_NARRATION_FIELD_VALUE = rf"(?:{_STRUCTURED_VALUE}|{_QUOTED_STRING_VALUE}|narration|clarification)"

_STANDALONE_NARRATION_FIELD_RE = re.compile(
    rf"""
    ^[ \t]*[{{,]?[ \t]*
    {_QUOTED_NARRATION_FIELD}
    [ \t]*[:：][ \t]*
    (?:{_NARRATION_FIELD_VALUE})?
    [ \t]*[,}}]?[ \t]*(?:\r?\n[ \t]*```)?[ \t]*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

_TRAILING_NARRATION_FIELD_RE = re.compile(
    rf"""
    (?:^|[\r\n]|[。！？.!?]|(?<=\s))[ \t]*
    [{{,]?[ \t]*
    {_QUOTED_NARRATION_FIELD}
    [ \t]*[:：][ \t]*
    (?:{_NARRATION_FIELD_VALUE})?
    [ \t]*[,}}]*[ \t]*(?:\r?\n[ \t]*```)?[ \t]*$
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_TRAILING_OBJECT_FRAGMENT_RE = re.compile(
    r"""
    (?:^|[\r\n]|[。！？.!?]|(?<=\s))[ \t]*
    (?:```(?:json)?[ \t]*[\r\n]+)?
    (?P<object>\{.*)
    [ \t]*$
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_NARRATION_KIND_RE = re.compile(
    r"""(?:"|')?kind(?:"|')?[ \t]*[:：][ \t]*(?:"|')?(?:narration|clarification)(?:"|')?""",
    re.IGNORECASE,
)

_NARRATION_FIELD_KEY_RE = re.compile(
    r"""
    (?:"|')?
    (?P<field>kind|text|claimed_fact_ids|claimedFactIds|suggested_actions|suggestedActions)
    (?:"|')?
    [ \t]*[:：]
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NARRATION_FIELD_TOKEN_RE = re.compile(
    r"""(?:"|')?(kind|text|claimed_fact_ids|claimedFactIds|suggested_actions|suggestedActions)(?:"|')?""",
    re.IGNORECASE,
)

_SCHEMA_MARKER_RE = re.compile(
    r"""(?:"|')?(?:properties|required)(?:"|')?[ \t]*[:：]""",
    re.IGNORECASE,
)


class NarrationValidationError(ContractError):
    """A model candidate failed deterministic player-visible output policy."""

    def __init__(self, reason: NarrationRejectionReason) -> None:
        super().__init__("NarrationOutput 未通过玩家可见输出安全校验")
        self.reason = reason


def narration_text_rejection_reason(
    text: str,
) -> Literal["protocol_tail", "schema_fragment"] | None:
    """Return a safe category for obvious Narration protocol residue."""

    if _STANDALONE_NARRATION_FIELD_RE.search(text):
        return "protocol_tail"
    if _TRAILING_NARRATION_FIELD_RE.search(text):
        return "protocol_tail"

    object_match = _TRAILING_OBJECT_FRAGMENT_RE.search(text)
    if object_match is None:
        return None
    candidate = object_match.group("object")
    if _NARRATION_KIND_RE.search(candidate):
        return "protocol_tail"

    if _SCHEMA_MARKER_RE.search(candidate):
        field_tokens = {
            match.group(1).casefold()
            for match in _NARRATION_FIELD_TOKEN_RE.finditer(candidate)
        }
        if len(field_tokens) >= 2:
            return "schema_fragment"

    field_keys = {
        match.group("field").casefold()
        for match in _NARRATION_FIELD_KEY_RE.finditer(candidate)
    }
    if len(field_keys) >= 2:
        return "protocol_tail"
    return None


class Narrator:
    def __init__(self, model: NarrationModelPort) -> None:
        self._model = model

    async def narrate(self, context: NarrationContext) -> NarrationOutput:
        raw = await self._model.generate(context)
        try:
            output = NarrationOutput.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise NarrationValidationError("outer_schema") from exc
        allowed = {fact.id for fact in context.action_result.visible_facts}
        if not set(output.claimed_fact_ids).issubset(allowed):
            raise NarrationValidationError("fact_scope")
        rejection_reason = narration_text_rejection_reason(output.text)
        if rejection_reason is not None:
            raise NarrationValidationError(rejection_reason)
        return output
