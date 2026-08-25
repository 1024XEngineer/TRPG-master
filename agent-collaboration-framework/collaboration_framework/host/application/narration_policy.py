"""Shared policy for player-visible narration text."""

from __future__ import annotations

import re
from typing import Literal

NarrationRejectionReason = Literal[
    "protocol_tail",
    "schema_fragment",
    "subject_ownership",
    "atmosphere_repeat",
]

_NARRATION_FIELD = (
    r"(?<![A-Za-z0-9_])"
    r"(?:kind|text|claimed_fact_ids|claimedFactIds|claimed_evidence_refs|"
    r"claimedEvidenceRefs|suggested_actions|suggestedActions)"
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

_ESCAPED_TEXT_TAIL_RE = re.compile(
    rf"""
    ["'][ \t]*,[ \t]*
    {_QUOTED_NARRATION_FIELD}
    [ \t]*[:：]
    """,
    re.IGNORECASE | re.VERBOSE,
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
    (?P<field>kind|text|claimed_fact_ids|claimedFactIds|claimed_evidence_refs|
    claimedEvidenceRefs|suggested_actions|suggestedActions)
    (?:"|')?
    [ \t]*[:：]
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NARRATION_FIELD_TOKEN_RE = re.compile(
    r"""(?:"|')?(kind|text|claimed_fact_ids|claimedFactIds|claimed_evidence_refs|claimedEvidenceRefs|suggested_actions|suggestedActions)(?:"|')?""",
    re.IGNORECASE,
)

_SCHEMA_MARKER_RE = re.compile(
    r"""(?:"|')?(?:properties|required)(?:"|')?[ \t]*[:：]""",
    re.IGNORECASE,
)

_QUOTED_SPAN_DELIMITERS = {
    "“": "”",
    "「": "」",
    "『": "』",
    "‘": "’",
    '"': '"',
    "'": "'",
    "《": "》",
}
_FIRST_PERSON_RE = re.compile(r"[我咱]")
_SECOND_PERSON_RE = re.compile(r"您(?!们)|你(?!们)")


def normalize_narration_text(text: str) -> str:
    """Convert model-emitted literal newline escapes to canonical LF characters."""

    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


_SENTENCE_END_CHARS = "。！？!?…"
_SENTENCE_CLOSING_CHARS = "」』”’\"')）】"

_NARRATION_PIECE_RE = re.compile(
    rf"[^{_SENTENCE_END_CHARS}]*[{_SENTENCE_END_CHARS}]+[{_SENTENCE_CLOSING_CHARS}]*\s*"
    rf"|[^{_SENTENCE_END_CHARS}]+"
)

# 只用来挡住"……"、"好。"这种退化片段。定得再高会把正常的短句（"陈探员此刻
# 就在这里。"）并进前一段，短叙事会整段塌成单片、退回非流式。
_MIN_CHUNK_CHARS = 6


def split_narration_chunks(text: str, *, min_chars: int = _MIN_CHUNK_CHARS) -> tuple[str, ...]:
    """Split already-validated narration text at sentence boundaries.

    Only for progressive delivery of text that has *already* passed
    the caller has validated. Never use it to emit unvalidated model output: a
    fragment carries no independent safety guarantee, so the caller must have
    validated the whole narration first.

    Concatenating the result reproduces ``text`` byte for byte — clients that
    accumulate chunks must end up with exactly the persisted narration. Pieces
    shorter than ``min_chars`` are merged forward so a stray "……" does not
    become its own chunk.
    """

    if not text:
        return ()

    chunks: list[str] = []
    buffer = ""
    for match in _NARRATION_PIECE_RE.finditer(text):
        buffer += match.group(0)
        if len(buffer.strip()) >= min_chars:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        if chunks:
            chunks[-1] += buffer
        else:
            chunks.append(buffer)
    return tuple(chunks)


def narration_text_rejection_reason(
    text: str,
) -> Literal["protocol_tail", "schema_fragment"] | None:
    """Return a safe category for obvious Narration protocol residue."""

    if _STANDALONE_NARRATION_FIELD_RE.search(text):
        return "protocol_tail"
    if _TRAILING_NARRATION_FIELD_RE.search(text):
        return "protocol_tail"
    if _ESCAPED_TEXT_TAIL_RE.search(text):
        return "protocol_tail"

    object_match = _TRAILING_OBJECT_FRAGMENT_RE.search(text)
    if object_match is None:
        return None
    candidate = object_match.group("object")
    if _NARRATION_KIND_RE.search(candidate):
        return "protocol_tail"

    if _SCHEMA_MARKER_RE.search(candidate):
        field_tokens = {
            match.group(1).casefold() for match in _NARRATION_FIELD_TOKEN_RE.finditer(candidate)
        }
        if len(field_tokens) >= 2:
            return "schema_fragment"

    field_keys = {
        match.group("field").casefold() for match in _NARRATION_FIELD_KEY_RE.finditer(candidate)
    }
    if len(field_keys) >= 2:
        return "protocol_tail"
    return None


def narration_subject_rejection_reason(
    text: str,
    *,
    addressing_mode: Literal["second_person", "named_actor"] = "second_person",
) -> Literal["subject_ownership"] | None:
    """Reject first-person ownership in prose while preserving quoted speech.

    In named_actor mode, also reject unquoted second-person references to the
    acting character. Quoted dialogue may still contain 你/您.
    """

    quoted = [False] * len(text)
    for opening, closing in _QUOTED_SPAN_DELIMITERS.items():
        start: int | None = None
        for index, character in enumerate(text):
            if opening == closing:
                if character != opening:
                    continue
                if start is None:
                    start = index
                else:
                    quoted[start : index + 1] = [True] * (index + 1 - start)
                    start = None
                continue
            if character == opening and start is None:
                start = index
            elif character == closing and start is not None:
                quoted[start : index + 1] = [True] * (index + 1 - start)
                start = None

    prose = "".join(character for index, character in enumerate(text) if not quoted[index])
    if _FIRST_PERSON_RE.search(prose):
        return "subject_ownership"
    if addressing_mode == "named_actor" and _SECOND_PERSON_RE.search(prose):
        return "subject_ownership"
    return None


_ATMOSPHERE_OPENING_MIN_CHARS = 12
_ATMOSPHERE_TIME_AFTERNOON_RE = re.compile(r"午后|下午|正午")
_ATMOSPHERE_TIME_MORNING_RE = re.compile(r"清晨|黎明|晨光|凌晨")
_ATMOSPHERE_TIME_DUSK_RE = re.compile(r"黄昏|傍晚")
_ATMOSPHERE_TIME_NIGHT_RE = re.compile(r"夜里|夜晚|夜色|深夜")
_ATMOSPHERE_LIGHT_RE = re.compile(r"阳光|月光|光线|日光|灯光|烛光|夜色如墨|的光")
_ATMOSPHERE_WINDOW_RE = re.compile(r"百叶窗|窗棂|玻璃窗|窗户")
_ATMOSPHERE_SILENCE_RE = re.compile(r"死一般的寂静|死寂|沉浸在")
_ATMOSPHERE_TIME_KEYS = frozenset({"afternoon", "morning", "dusk", "night"})
_ATMOSPHERE_SETTING_KEYS = frozenset({"light", "window", "silence"})


def _first_narration_sentence(text: str) -> str:
    stripped = text.strip()
    for index, character in enumerate(stripped):
        if character in _SENTENCE_END_CHARS:
            return stripped[: index + 1].strip()
    return stripped[:40].strip()


def _opening_window(text: str, *, sentences: int) -> str:
    stripped = text.strip()
    seen = 0
    for index, character in enumerate(stripped):
        if character in _SENTENCE_END_CHARS:
            seen += 1
            if seen >= sentences:
                return stripped[: index + 1].strip()
    return stripped[:160].strip()


def _atmosphere_keys(text: str) -> frozenset[str]:
    keys: set[str] = set()
    if _ATMOSPHERE_TIME_AFTERNOON_RE.search(text):
        keys.add("afternoon")
    if _ATMOSPHERE_TIME_MORNING_RE.search(text):
        keys.add("morning")
    if _ATMOSPHERE_TIME_DUSK_RE.search(text):
        keys.add("dusk")
    if _ATMOSPHERE_TIME_NIGHT_RE.search(text):
        keys.add("night")
    if _ATMOSPHERE_LIGHT_RE.search(text):
        keys.add("light")
    if _ATMOSPHERE_WINDOW_RE.search(text):
        keys.add("window")
    if _ATMOSPHERE_SILENCE_RE.search(text):
        keys.add("silence")
    return frozenset(keys)


def narration_atmosphere_rejection_reason(
    text: str,
    previous_published_narration: str | None,
) -> Literal["atmosphere_repeat"] | None:
    """Reject recopying or paraphrasing the previous turn's scene-setting opening.

    Callers pass None when there is no prior published narration; this then
    returns None so an opening or first arrival can establish the shot. Quoted
    speech is not stripped: an atmospheric opener is wrong even if it later
    quotes an NPC.
    """

    if not previous_published_narration or not text.strip():
        return None
    new_first = _first_narration_sentence(text)
    old_first = _first_narration_sentence(previous_published_narration)
    if len(new_first) >= _ATMOSPHERE_OPENING_MIN_CHARS:
        if new_first == old_first:
            return "atmosphere_repeat"
        shorter, longer = sorted((new_first, old_first), key=len)
        if len(shorter) >= _ATMOSPHERE_OPENING_MIN_CHARS and longer.startswith(shorter):
            return "atmosphere_repeat"
    new_open = _opening_window(text, sentences=2)
    old_open = _opening_window(previous_published_narration, sentences=3)
    shared = _atmosphere_keys(new_open) & _atmosphere_keys(old_open)
    if (shared & _ATMOSPHERE_TIME_KEYS) and (shared & _ATMOSPHERE_SETTING_KEYS):
        return "atmosphere_repeat"
    return None
