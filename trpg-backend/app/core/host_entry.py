"""Private A1 router for ordinary keeper interactions.

The router deliberately works on a small, ID-free public projection.  It is not
an alternative rules engine: anything that might change authoritative state is
delegated to the existing ActionPlan application.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from collaboration_framework.contracts import PlayerView
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

HostEntryRoute = Literal["direct_response", "delegate_to_legacy"]
HOST_ENTRY_FALLBACK = "我暂时没能准确接住这句话，请重新说明你想做什么。"
HOST_ENTRY_MAX_TEXT = 1000
HOST_ENTRY_MAX_HISTORY = 6
HOST_ENTRY_MAX_CHARS = 6000


class HostEntryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: HostEntryRoute
    text: str | None = Field(default=None, max_length=HOST_ENTRY_MAX_TEXT)

    @model_validator(mode="after")
    def validate_route_text(self) -> HostEntryDecision:
        if self.route == "direct_response":
            if not isinstance(self.text, str) or not self.text.strip():
                raise ValueError("direct_response 必须包含非空 text")
            self.text = self.text.strip()
        elif self.text not in (None, ""):
            raise ValueError("delegate_to_legacy 不得包含 text")
        return self


class HostPublicHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "player_message",
        "npc_dialogue",
        "keeper_narration",
        "direct_response",
    ]
    speaker: str | None = Field(default=None, max_length=120)
    text: str = Field(min_length=1, max_length=1200)


class HostPublicContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_scene: str = Field(default="", max_length=1200)
    public_location: str | None = Field(default=None, max_length=600)
    public_time: str | None = Field(default=None, max_length=120)
    visible_characters: tuple[str, ...] = Field(default=(), max_length=32)
    visible_environment: tuple[str, ...] = Field(default=(), max_length=64)
    recent_history: tuple[HostPublicHistoryEntry, ...] = Field(
        default=(), max_length=HOST_ENTRY_MAX_HISTORY
    )
    current_keeper_text: str = Field(min_length=1, max_length=2000)

    def to_model_payload(self) -> dict[str, object]:
        """Return the exact allow-listed payload sent to a model."""

        return self.model_dump(mode="json")


class HostPublicContextProjector:
    """Project only public, human-readable fields from ``PlayerView``."""

    def __init__(
        self, *, max_turns: int = HOST_ENTRY_MAX_HISTORY, max_chars: int = HOST_ENTRY_MAX_CHARS
    ):
        self.max_turns = max(1, min(max_turns, HOST_ENTRY_MAX_HISTORY))
        self.max_chars = max(2, max_chars)

    def project(
        self,
        player_view: PlayerView,
        *,
        current_keeper_text: str,
        public_history: Sequence[HostPublicHistoryEntry | Mapping[str, object]] = (),
    ) -> HostPublicContext:
        scene = player_view.scene
        scene_parts = [
            _strip_internal_tokens(part)
            for part in (scene.name, scene.description)
            if isinstance(part, str) and part.strip()
        ]
        scene_parts.extend(
            _strip_internal_tokens(detail.text)
            for detail in scene.narrative_details
            if isinstance(detail.text, str) and detail.text.strip()
        )
        location = None
        if player_view.location_context is not None:
            breadcrumbs = player_view.location_context.breadcrumbs
            if breadcrumbs:
                location = " / ".join(item.name for item in breadcrumbs)
        characters = tuple(
            dict.fromkeys(
                [
                    (
                        f"{actor.name}: {getattr(actor, 'status_summary', '')}"
                        if getattr(actor, "status_summary", "")
                        else actor.name
                    )
                    for actor in scene.visible_actors
                ]
                + [entity.name for entity in scene.visible_entities if entity.kind == "npc"]
            )
        )
        environment = tuple(
            dict.fromkeys(
                [
                    _strip_internal_tokens(
                        entity.name + (f": {entity.description}" if entity.description else "")
                    )
                    for entity in scene.visible_entities
                ]
                + [_strip_internal_tokens(detail.text) for detail in scene.narrative_details]
            )
        )
        entries: list[HostPublicHistoryEntry] = []
        for raw in public_history:
            try:
                entry = (
                    raw
                    if isinstance(raw, HostPublicHistoryEntry)
                    else HostPublicHistoryEntry.model_validate(raw)
                )
            except ValidationError:
                continue
            clean_text = _strip_internal_tokens(entry.text)
            if not clean_text:
                continue
            entries.append(
                entry.model_copy(
                    update={
                        "speaker": _strip_internal_tokens(entry.speaker) if entry.speaker else None,
                        "text": clean_text,
                    }
                )
            )
        # Keep the newest bounded entries and then enforce the character budget deterministically.
        entries = entries[-self.max_turns :]
        while entries and sum(len(item.text) for item in entries) > self.max_chars:
            entries.pop(0)
        return HostPublicContext(
            public_scene="\n".join(scene_parts)[:1200],
            public_location=location,
            public_time=scene.time,
            visible_characters=characters[:32],
            visible_environment=environment[:64],
            recent_history=tuple(entries),
            current_keeper_text=(
                _strip_internal_tokens(current_keeper_text.strip()) or current_keeper_text.strip()
            ),
        )


class HostEntryModel(Protocol):
    async def generate(self, context: HostPublicContext) -> Mapping[str, object]: ...


class DeterministicHostEntryModel:
    """Offline fake model.  It is injectable and intentionally conservative."""

    async def generate(self, context: HostPublicContext) -> Mapping[str, object]:
        text = context.current_keeper_text.strip()
        if _looks_like_ordinary_interaction(text):
            return {"route": "direct_response", "text": "对方礼貌地点了点头。"}
        return {"route": "delegate_to_legacy", "text": None}


class HostDirectResponseSafetyPolicy:
    """Fail-closed validation for a public, non-authoritative response."""

    _forbidden = re.compile(
        r"(?:检定|掷骰|成功|失败|获得|得到|拾取|发现|找到|物品|钥匙|暗格|线索|秘密|证据|伤势|状态|关系|信任|"
        r"(?:时间|地点)(?:改变|变化|推进|移动|变更|是)|路线|结局|之后|将会|未来|承诺|"
        r"adjudication|revision|event[_ ]?id|entity[_ ]?id|prompt|schema|json|代码块|内部|协议|"
        r"uuid)",
        re.IGNORECASE,
    )

    def validate(self, decision: HostEntryDecision) -> HostEntryDecision:
        # Re-validate through the strict adapter so callers cannot pass a dict with
        # unknown protocol fields by accident.
        decision = TypeAdapter(HostEntryDecision).validate_python(decision.model_dump())
        if decision.route == "delegate_to_legacy":
            return decision
        text = decision.text or ""
        if not text.strip() or len(text) > HOST_ENTRY_MAX_TEXT:
            raise ValueError("direct response text is empty or too long")
        if any(token in text for token in ("```", "{", "}", "<schema", "<json")):
            raise ValueError("structured or code-like output is not public narration")
        if self._forbidden.search(text):
            raise ValueError("direct response contains an authoritative claim")
        # Never accept a mixed safe/unsafe answer.  This check intentionally rejects
        # the entire output instead of trying to redact a suspicious sentence.
        if any(
            mark in text for mark in ("#", "protocol_version", "message_type", "correlation_id")
        ):
            raise ValueError("internal protocol content")
        return decision


class HostEntryRouter:
    def __init__(
        self,
        model: HostEntryModel,
        *,
        safety_policy: HostDirectResponseSafetyPolicy | None = None,
        force_legacy: bool | None = None,
    ) -> None:
        self.model = model
        self.safety_policy = safety_policy or HostDirectResponseSafetyPolicy()
        self.force_legacy = (
            force_legacy
            if force_legacy is not None
            else os.getenv("HOST_ENTRY_FORCE_LEGACY", "false").lower() in {"1", "true", "yes", "on"}
        )
        self.attempts = 0
        self.safety_failures = 0
        self.fallbacks = 0

    async def decide(self, context: HostPublicContext) -> tuple[HostEntryDecision, str]:
        """Try one structured call plus one complete retry, then clarify safely."""

        payload = context.to_model_payload()
        del payload  # the model receives the immutable context object, not a broad view
        last_error: Exception | None = None
        if self.force_legacy:
            self.attempts += 1
            return HostEntryDecision(route="delegate_to_legacy"), "forced_legacy"
        for _ in range(2):
            self.attempts += 1
            try:
                raw = await self.model.generate(context)
                decision = HostEntryDecision.model_validate(raw)
                return self.safety_policy.validate(
                    decision
                ), "model_direct" if decision.route == "direct_response" else "legacy_delegate"
            except Exception as exc:
                last_error = exc
                self.safety_failures += 1
        self.fallbacks += 1
        # A model failure is still a direct, non-authoritative clarification.  It
        # must never enter ActionPlan merely because structured output was bad.
        _ = last_error
        return HostEntryDecision(
            route="direct_response", text=HOST_ENTRY_FALLBACK
        ), "fallback_clarification"


def host_entry_decision_schema() -> dict[str, object]:
    return TypeAdapter(HostEntryDecision).json_schema(mode="serialization")


def _looks_like_ordinary_interaction(text: str) -> bool:
    lowered = text.casefold()
    if any(
        token in lowered
        for token in (
            "搜索",
            "调查",
            "检查",
            "打开",
            "拿",
            "取",
            "前往",
            "说服",
            "威胁",
            "欺骗",
            "案件",
            "秘密",
            "背景",
            "为什么",
            "怎么",
            "是否",
        )
    ):
        return False
    return any(
        token in lowered
        for token in ("你好", "嗨", "招呼", "问候", "谢谢", "再见", "点头", "微笑", "挥手", "寒暄")
    )


_INTERNAL_TOKEN_RE = re.compile(
    r"(?:\b(?:entity|event|action|client)[_-]?(?:id|request)?\s*[:=]\s*[A-Za-z0-9_.:-]+\b|"
    r"\brevision\s*[:=]\s*[A-Za-z0-9_.:-]+\b|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b)",
    re.IGNORECASE,
)


def _strip_internal_tokens(value: str) -> str:
    return _INTERNAL_TOKEN_RE.sub("", value).strip()


__all__ = [
    "HOST_ENTRY_FALLBACK",
    "HostDirectResponseSafetyPolicy",
    "HostEntryDecision",
    "HostEntryRouter",
    "HostPublicContext",
    "HostPublicContextProjector",
    "HostPublicHistoryEntry",
    "DeterministicHostEntryModel",
    "host_entry_decision_schema",
]
