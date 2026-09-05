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

import structlog
from collaboration_framework.contracts import PlayerView
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

logger = structlog.get_logger(__name__)

HostEntryRoute = Literal[
    "direct_response",
    "rule_once",
    "composite_rule",
    "delegate_to_legacy",
    "needs_clarification",
]
HOST_ENTRY_FALLBACK = "我暂时没能准确接住这句话，请重新说明你想做什么。"
HOST_ENTRY_MAX_TEXT = 1000
HOST_ENTRY_MAX_HISTORY = 6
HOST_ENTRY_MAX_CHARS = 6000


class HostEntryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: HostEntryRoute
    text: str | None = Field(default=None, max_length=HOST_ENTRY_MAX_TEXT)
    rule_id: str | None = Field(default=None, min_length=1, max_length=100)
    option_id: str | None = Field(default=None, min_length=1, max_length=100)
    target_kind: Literal["information", "entity", "location", "actor", "world"] | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_route_text(self) -> HostEntryDecision:
        if self.route in {"direct_response", "needs_clarification"}:
            if not isinstance(self.text, str) or not self.text.strip():
                raise ValueError(f"{self.route} 必须包含非空 text")
            self.text = self.text.strip()
            if any(
                value is not None
                for value in (
                    self.rule_id,
                    self.option_id,
                    self.target_kind,
                    self.target_id,
                    self.summary,
                )
            ):
                raise ValueError("direct_response 不得包含 rule_once 字段")
        elif self.route == "rule_once":
            if not self.rule_id or not self.option_id:
                raise ValueError("rule_once 必须包含 rule_id 和 option_id")
            if self.text not in (None, ""):
                raise ValueError("rule_once 不得包含 direct_response text")
            if self.summary is not None:
                self.summary = self.summary.strip()
                if not self.summary:
                    self.summary = None
        elif self.route == "composite_rule":
            if self.text not in (None, ""):
                raise ValueError("composite_rule 不得包含 direct_response text")
            if any(
                value is not None
                for value in (
                    self.rule_id,
                    self.option_id,
                    self.target_kind,
                    self.target_id,
                    self.summary,
                )
            ):
                raise ValueError("composite_rule 不得包含预先冻结的规则字段")
        elif self.text not in (None, ""):
            raise ValueError("delegate_to_legacy 不得包含 text")
        if self.route == "delegate_to_legacy" and any(
            value is not None
            for value in (
                self.rule_id,
                self.option_id,
                self.target_kind,
                self.target_id,
                self.summary,
            )
        ):
            raise ValueError("delegate_to_legacy 不得包含 rule_once 字段")
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
    clarification_question: str | None = Field(default=None, max_length=HOST_ENTRY_MAX_TEXT)
    player_answer: str | None = Field(default=None, max_length=2000)
    completed_rule_feedback: tuple[str, ...] = Field(default=(), max_length=8)
    loop_step_index: int = Field(default=0, ge=0, le=8)

    def to_model_payload(self) -> dict[str, object]:
        """Return the exact allow-listed payload sent to a model."""

        return self.model_dump(mode="json")


class HostRuleOptionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    semantic_hints: tuple[str, ...] = ()
    requires_check: bool = True


class HostRuleCandidateContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=100)
    question_kind: Literal["action_declaration", "method", "intent_relation"]
    semantic_hints: tuple[str, ...] = ()
    action_families: tuple[str, ...] = ()
    target_kinds: tuple[Literal["information", "entity", "location", "actor", "world"], ...] = ()
    target_ids: tuple[str, ...] = ()
    options: tuple[HostRuleOptionContext, ...] = ()


class HostTargetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["information", "entity", "location", "actor", "world"]
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class HostRuleMatchContext(BaseModel):
    """Allow-listed rule-match data; never contains Keeper-only content."""

    model_config = ConfigDict(extra="forbid")

    source_revision: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=200)
    skills: tuple[str, ...] = ()
    targets: tuple[HostTargetContext, ...] = ()
    rule_candidates: tuple[HostRuleCandidateContext, ...] = ()


class HostEntryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public: HostPublicContext
    rule_match: HostRuleMatchContext | None = None

    @property
    def current_keeper_text(self) -> str:
        return self.public.current_keeper_text

    @property
    def player_answer(self) -> str | None:
        return self.public.player_answer

    @property
    def clarification_question(self) -> str | None:
        return self.public.clarification_question

    def to_model_payload(self) -> dict[str, object]:
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
        clarification_question: str | None = None,
        player_answer: str | None = None,
        completed_rule_feedback: Sequence[str] = (),
        loop_step_index: int = 0,
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
        cleaned_keeper_text = _strip_internal_tokens(current_keeper_text.strip())
        return HostPublicContext(
            public_scene="\n".join(scene_parts)[:1200],
            public_location=location,
            public_time=scene.time,
            visible_characters=characters[:32],
            visible_environment=environment[:64],
            recent_history=tuple(entries),
            # An input made entirely of internal tokens must not be restored
            # from the original text after sanitization.  Keep the contract's
            # non-empty field with a neutral placeholder instead.
            current_keeper_text=cleaned_keeper_text or "未提供可用的公开文本",
            clarification_question=(
                _strip_internal_tokens(clarification_question).strip() or None
                if clarification_question
                else None
            ),
            player_answer=(
                _strip_internal_tokens(player_answer).strip() or None if player_answer else None
            ),
            completed_rule_feedback=tuple(
                _strip_internal_tokens(value).strip()
                for value in completed_rule_feedback
                if isinstance(value, str) and _strip_internal_tokens(value).strip()
            )[-8:],
            loop_step_index=max(0, min(loop_step_index, 8)),
        )


class HostEntryModel(Protocol):
    async def generate(
        self, context: HostPublicContext | HostEntryContext
    ) -> Mapping[str, object]: ...


class DeterministicHostEntryModel:
    """Offline fake model.  It is injectable and intentionally conservative."""

    async def generate(self, context: HostPublicContext | HostEntryContext) -> Mapping[str, object]:
        text = context.current_keeper_text.strip()
        answer = (context.player_answer or "").strip()
        if answer:
            if _looks_like_legacy_intent(answer) or _looks_like_legacy_intent(text):
                return {"route": "delegate_to_legacy", "text": None}
            return {"route": "direct_response", "text": "明白了，就按这个来。"}
        if _looks_like_important_ambiguity(text):
            return {"route": "needs_clarification", "text": "你具体指的是哪一个？"}
        if _looks_like_composite_intent(text):
            return {"route": "composite_rule", "text": None}
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
        if decision.route == "rule_once":
            summary = decision.summary or ""
            if any(token in summary for token in ("```", "{", "}", "<schema", "<json")):
                raise ValueError("rule_once summary contains structured content")
            if self._forbidden.search(summary):
                raise ValueError("rule_once summary contains an authoritative claim")
            return decision
        if decision.route == "composite_rule":
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

    async def decide(
        self, context: HostPublicContext | HostEntryContext
    ) -> tuple[HostEntryDecision, str]:
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
                validated = self.safety_policy.validate(decision)
                if validated.route == "direct_response":
                    provenance = "model_direct"
                elif validated.route == "needs_clarification":
                    provenance = "model_clarify"
                elif validated.route == "rule_once":
                    provenance = "rule_once"
                elif validated.route == "composite_rule":
                    provenance = "composite_rule"
                else:
                    provenance = "legacy_delegate"
                logger.info("host_entry_decision", route=validated.route, provenance=provenance)
                return validated, provenance
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


_LEGACY_INTENT_TOKENS = (
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


def _looks_like_composite_intent(text: str) -> bool:
    """Conservative offline heuristic for compound authoritative actions."""

    pattern = r"(?:并且|然后|再|同时|之后|拿出|取出).*(?:并|然后|再|拿|取|打开|搜索)"
    return bool(re.search(pattern, text))


def _looks_like_legacy_intent(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in _LEGACY_INTENT_TOKENS)


def _looks_like_important_ambiguity(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in ("那个", "哪一个", "哪本", "哪把"))


def _looks_like_ordinary_interaction(text: str) -> bool:
    lowered = text.casefold()
    if _looks_like_legacy_intent(lowered):
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
    "HostEntryContext",
    "HostRuleMatchContext",
    "HostRuleCandidateContext",
    "HostRuleOptionContext",
    "HostTargetContext",
    "HostPublicHistoryEntry",
    "DeterministicHostEntryModel",
    "host_entry_decision_schema",
]
