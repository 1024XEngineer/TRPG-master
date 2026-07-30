"""Deterministic validation boundary for untrusted Host Agent output."""

from __future__ import annotations

import unicodedata

from collaboration_framework.contracts import (
    ContractError,
    DefaultCheck,
    Intent,
    JsonObject,
    MatchedTarget,
    ModuleCheck,
    NoCheck,
    UnmatchedTarget,
)
from collaboration_framework.contracts.player_view import (
    AvailableExitView,
    CheckpointOption,
    PlayerView,
    VisibleEntity,
)
from collaboration_framework.host.schemas import IntentContext

from .intent_aligner import align_intent_for_engine


class IntentParser:
    """Parse one raw JSON object without invoking a model or mutating state."""

    @staticmethod
    def parse(raw: JsonObject, context: IntentContext) -> Intent:
        raw = coerce_intent_payload(raw, context)
        intent = Intent.model_validate(raw)
        intent = normalize_intent_against_view(intent, context)
        intent = validate_intent_against_view(intent, context)
        return align_intent_for_engine(intent, context)


def coerce_intent_payload(raw: JsonObject, context: IntentContext) -> JsonObject:
    """Safely normalize recoverable model output before strict validation.

    The model sometimes emits ``route=default`` without a skill.  That is not
    an executable contract: safe observations should be ``no check``; actions
    that clearly need a check must name an available actor skill.  Ambiguous
    cases become a clarification instead of a WebSocket contract failure. A
    search for a narration-only detail may become a state-free current-Scene
    perception check, but never a new authoritative Entity.
    """

    if not isinstance(raw, dict):
        return raw
    narrated_detail_search = _recover_same_scene_narrated_detail_search(raw, context)
    if narrated_detail_search is not None:
        return narrated_detail_search
    check = raw.get("check")
    if not isinstance(check, dict) or check.get("route") != "default":
        return raw
    proposed_skills = check.get("proposed_skills")
    if isinstance(proposed_skills, (list, tuple)) and proposed_skills:
        return raw

    if _looks_like_no_check_action(raw, context):
        return {**raw, "check": {"route": "none"}}

    fallback_skill = _infer_default_skill_id(raw, context)
    if fallback_skill is not None:
        return {
            **raw,
            "check": {**check, "proposed_skills": [fallback_skill]},
        }
    return _clarification_payload(context)


def _recover_same_scene_narrated_detail_search(
    raw: JsonObject,
    context: IntentContext,
) -> JsonObject | None:
    """Turn a same-scene narration-only reference into a safe scene search.

    Published narration is presentation text, not authority for a new Entity. If
    the player searches a concrete detail they recently saw there, the
    safe recovery target is the current Scene: it supports a descriptive default
    check without promoting the detail or firing an Entity checkpoint.
    """

    target = raw.get("target")
    if not isinstance(target, dict):
        return None
    raw_target = (
        target.get("raw") if target.get("matched") is False else target.get("id")
    )
    if not isinstance(raw_target, str) or not raw_target.strip():
        return None
    if _match_target_id(raw_target, context.player_view) is not None:
        return None

    utterance = context.player_input.utterance
    narrated_turn = None
    for turn in reversed(context.recent_history.turns):
        if turn.scene_id != context.player_view.scene_id:
            break
        if turn.published_narration is not None and _shares_specific_narrated_anchor(
            raw_target=raw_target,
            utterance=utterance,
            narration=turn.published_narration.text,
        ):
            narrated_turn = turn
            break
    if narrated_turn is None:
        return None
    skill_id = _specific_perception_skill_id(utterance, context)
    if skill_id is None:
        return None

    summary = raw.get("summary")
    return {
        "kind": "action",
        "verb": "search" if skill_id == "spot-hidden" else "listen",
        "target": {"matched": True, "id": context.player_view.scene.id},
        "check": {"route": "default", "proposed_skills": [skill_id]},
        "approach": raw.get("approach")
        if isinstance(raw.get("approach"), str)
        else None,
        "declarations": [],
        "initiated_by_target": False,
        "summary": (
            summary
            if isinstance(summary, str) and summary.strip()
            else utterance.strip() or "在当前场景寻找先前提到的细节"
        ),
    }


def _shares_specific_narrated_anchor(
    *,
    raw_target: str,
    utterance: str,
    narration: str,
) -> bool:
    narration_key = _label_key(narration)
    target_key = _label_key(raw_target)
    if len(target_key) >= 2 and target_key in narration_key:
        return True

    utterance_key = _label_key(utterance)
    ignored = {
        "那我",
        "我要",
        "我去",
        "一下",
        "看看",
        "看一",
        "找一",
        "有没",
        "没有",
        "什么",
        "线索",
        "这个",
        "那个",
        "那里",
        "这里",
        "观察",
        "调查",
        "搜索",
        "搜查",
    }
    max_width = min(12, len(utterance_key))
    for width in range(max_width, 1, -1):
        for start in range(len(utterance_key) - width + 1):
            candidate = utterance_key[start : start + width]
            if candidate not in ignored and candidate in narration_key:
                return True
    return False


def _specific_perception_skill_id(
    utterance: str,
    context: IntentContext,
) -> str | None:
    text = _label_key(utterance)
    actor_candidates = _actor_check_candidates(context)
    if any(marker in text for marker in ("听", "聆听", "倾听")):
        return "listen" if "listen" in actor_candidates else None
    if any(
        marker in text
        for marker in (
            "看",
            "找",
            "搜索",
            "搜查",
            "观察",
            "检查",
            "调查",
            "线索",
        )
    ):
        return "spot-hidden" if "spot-hidden" in actor_candidates else None
    return None


def normalize_intent_against_view(
    intent: Intent,
    context: IntentContext,
) -> Intent:
    """Map player-facing labels to IDs from the current trusted view only.

    Model output is allowed to use a visible Chinese name or alias, but the
    authoritative contracts continue to carry opaque IDs.  Matching is exact
    after Unicode/punctuation normalization and is discarded when ambiguous.
    Hidden module content is deliberately never consulted here.
    """

    view = context.player_view
    target = intent.target
    if isinstance(target, MatchedTarget):
        target_id = _match_target_id(target.id, view)
        if target_id is not None and target_id != target.id:
            intent = intent.model_copy(update={"target": MatchedTarget(id=target_id)})
    elif intent.kind != "unknown":
        target_id = _match_target_id(target.raw, view)
        if target_id is not None:
            intent = intent.model_copy(update={"target": MatchedTarget(id=target_id)})

    # A player can refer to the visible thing at the end of a route ("靠近它")
    # instead of repeating the route label ("前往入口").  The model may bind
    # that phrase to the entity, but the authoritative action must target the
    # visible exit so the engine performs the scene transition.
    if isinstance(intent.target, MatchedTarget) and _action_family(intent.verb) in {
        "travel",
        "enter",
        "move_object",
    }:
        matching_exits = tuple(
            item
            for item in view.scene.available_exits
            if item.target_id == intent.target.id
        )
        if len(matching_exits) == 1:
            intent = intent.model_copy(
                update={"target": MatchedTarget(id=matching_exits[0].id)}
            )

    # The engine accepts only canonical travel verbs for an exit target.  Keep
    # any explicit check/approach, but make the authoritative transition verb
    # provider- and language-independent.
    if (
        isinstance(intent.target, MatchedTarget)
        and _action_family(intent.verb) in {"travel", "enter", "move_object"}
        and any(item.id == intent.target.id for item in view.scene.available_exits)
    ):
        intent = intent.model_copy(update={"verb": "go"})

    target_checkpoints = _checkpoints_for_target(intent, view)
    checkpoint = _matching_checkpoint_for_intent(intent, target_checkpoints)
    if checkpoint is not None and not isinstance(intent.check, ModuleCheck):
        proposed_skills = ()
        if isinstance(intent.check, DefaultCheck):
            normalized = _normalize_skills(
                intent.check.proposed_skills,
                checkpoint.skills,
                view,
            )
            if set(normalized).issubset(checkpoint.skills):
                proposed_skills = normalized
        intent = intent.model_copy(
            update={
                "verb": checkpoint.action_hint,
                "check": ModuleCheck(
                    checkpoint_id=checkpoint.id,
                    proposed_skills=proposed_skills,
                ),
            }
        )
    elif target_checkpoints and isinstance(intent.check, DefaultCheck):
        # A visible module checkpoint owns uncertain actions against its target.
        # A generic skill check must not bypass that rule boundary when the
        # proposed action is unsupported or still ambiguous.
        return _checkpoint_clarification(intent, view)

    if isinstance(intent.check, ModuleCheck):
        option = _match_checkpoint(intent, view)
        if option is not None:
            proposed_skills = _normalize_skills(
                intent.check.proposed_skills,
                option.skills,
                view,
            )
            intent = intent.model_copy(
                update={
                    "check": intent.check.model_copy(
                        update={
                            "checkpoint_id": option.id,
                            "proposed_skills": proposed_skills,
                        }
                    ),
                    "verb": option.action_hint,
                }
            )
    elif isinstance(intent.check, DefaultCheck):
        intent = intent.model_copy(
            update={
                "check": intent.check.model_copy(
                    update={
                        "proposed_skills": _normalize_skills(
                            intent.check.proposed_skills,
                            _actor_value_ids(view),
                            view,
                        )
                    }
                )
            }
        )
    return intent


def _matching_checkpoint_for_intent(
    intent: Intent,
    candidates: tuple[CheckpointOption, ...],
) -> CheckpointOption | None:
    semantic_matches = tuple(
        option
        for option in candidates
        if _action_matches(intent.verb, option.action_hint)
    )
    return semantic_matches[0] if len(semantic_matches) == 1 else None


def _checkpoints_for_target(
    intent: Intent,
    view: PlayerView,
) -> tuple[CheckpointOption, ...]:
    if not isinstance(intent.target, MatchedTarget):
        return ()
    return tuple(
        option
        for option in view.checkpoint_options
        if option.target_id == intent.target.id
    )


def _checkpoint_clarification(intent: Intent, view: PlayerView) -> Intent:
    assert isinstance(intent.target, MatchedTarget)
    target_name = next(
        (
            item.name
            for item in (
                *view.scene.visible_entities,
                *view.scene.available_exits,
            )
            if item.id == intent.target.id
        ),
        intent.target.id,
    )
    return Intent(
        kind="unknown",
        verb=intent.verb,
        target=UnmatchedTarget(raw=target_name),
        check=NoCheck(),
        approach=intent.approach,
        declarations=intent.declarations,
        initiated_by_target=intent.initiated_by_target,
        summary=intent.summary,
        clarification_question=f"你想如何处理{target_name}？",
    )


def _looks_like_no_check_action(raw: JsonObject, context: IntentContext) -> bool:
    verb = str(raw.get("verb", ""))
    family = _action_family(verb)
    target = raw.get("target")
    if family in {"travel", "enter"} and isinstance(target, dict):
        target_id = target.get("id")
        if target.get("matched") is True and isinstance(target_id, str):
            exit_candidates = [
                (item.id, _labels(item))
                for item in context.player_view.scene.available_exits
            ]
            if _unique_match(target_id, exit_candidates) is not None:
                return True

    text = _label_key(
        " ".join(
            str(value)
            for value in (
                raw.get("verb", ""),
                raw.get("summary", ""),
                context.player_input.utterance,
            )
        )
    )
    if family != "perception":
        return False
    if any(
        _label_key(marker) in text
        for marker in ("搜索", "寻找", "隐藏", "暗格", "仔细", "调查")
    ):
        return False
    return any(
        _label_key(marker) in text
        for marker in ("查看", "看看", "阅读", "观察", "描述周围")
    )


def _infer_default_skill_id(raw: JsonObject, context: IntentContext) -> str | None:
    family = _action_family(str(raw.get("verb", "")))
    candidates_by_family = {
        "perception": ("spot-hidden", "listen"),
        "social": ("fast-talk", "credit-rating"),
        "intimidate": ("intimidate",),
        "bribe": ("credit-rating", "fast-talk"),
        "open": ("STR", "DEX"),
        "attack": ("STR", "DEX"),
    }
    actor_ids = _actor_value_ids(context.player_view)
    return next(
        (
            candidate
            for candidate in candidates_by_family.get(family, ())
            if candidate in actor_ids
        ),
        None,
    )


def _clarification_payload(context: IntentContext) -> JsonObject:
    utterance = context.player_input.utterance.strip() or "这次行动"
    return {
        "kind": "unknown",
        "verb": "unknown",
        "target": {"matched": False, "raw": utterance},
        "check": {"route": "none"},
        "summary": utterance,
        "clarification_question": "你想对当前场景中的哪个人物、物品或地点做什么？",
    }


def validate_intent_against_view(
    intent: Intent,
    context: IntentContext,
) -> Intent:
    """Fail closed without replacing the Agent's semantic checkpoint choice."""

    if not isinstance(intent.target, MatchedTarget):
        return intent

    visible_entity_ids = {
        item.id for item in context.player_view.scene.visible_entities
    }
    available_exit_ids = {item.id for item in context.player_view.scene.available_exits}
    trusted_target_ids = visible_entity_ids | available_exit_ids
    if isinstance(intent.check, DefaultCheck):
        # Environment-wide perception and movement checks do not always have a
        # concrete Entity target.  The current player-safe Scene is the trusted
        # target for actions such as looking around, listening, or hiding.
        trusted_target_ids.add(context.player_view.scene.id)
    if intent.target.id not in trusted_target_ids:
        raise ContractError("Intent target 不在当前 PlayerView 中")

    if isinstance(intent.check, ModuleCheck):
        option = next(
            (
                item
                for item in context.player_view.checkpoint_options
                if item.id == intent.check.checkpoint_id
            ),
            None,
        )
        if option is None:
            raise ContractError("Intent checkpoint 不在可信候选中")
        if option.target_id != intent.target.id:
            raise ContractError("Intent checkpoint 与目标不一致")
        if not set(intent.check.proposed_skills).issubset(option.skills):
            raise ContractError("Intent proposed_skills 不属于 Checkpoint 候选技能")
    elif isinstance(intent.check, DefaultCheck):
        if not intent.check.proposed_skills:
            raise ContractError("Default Check 至少需要一个候选属性或技能")
        actor_candidates = _actor_check_candidates(context)
        if not set(intent.check.proposed_skills).issubset(actor_candidates):
            raise ContractError(
                "Default Check 只能使用当前 Actor 的整数属性、技能或 luck"
            )
    return intent


def _actor_check_candidates(context: IntentContext) -> set[str]:
    candidates = {
        item.id
        for item in (
            *context.player_view.self_actor.attributes,
            *context.player_view.self_actor.skills,
        )
        if isinstance(item.value, int) and not isinstance(item.value, bool)
    }
    candidates.update(
        item.id
        for item in context.player_view.self_actor.resources
        if item.id == "luck"
        and isinstance(item.value, int)
        and not isinstance(item.value, bool)
    )
    return candidates


def _match_target_id(raw: str, view: PlayerView) -> str | None:
    candidates: list[tuple[str, tuple[str, ...]]] = [
        (entity.id, _labels(entity)) for entity in view.scene.visible_entities
    ]
    candidates.extend(
        (available_exit.id, _labels(available_exit))
        for available_exit in view.scene.available_exits
    )
    if _same_label(raw, view.scene.id) or _same_label(raw, view.scene.name):
        candidates.append((view.scene.id, (view.scene.id, view.scene.name)))
    return _unique_match(raw, candidates)


def _match_checkpoint(intent: Intent, view: PlayerView) -> CheckpointOption | None:
    options = view.checkpoint_options
    checkpoint_id = intent.check.checkpoint_id
    by_id = [option for option in options if _same_label(checkpoint_id, option.id)]
    if len(by_id) == 1:
        return by_id[0]

    target_id = intent.target.id if isinstance(intent.target, MatchedTarget) else None
    candidates = [
        option
        for option in options
        if target_id is not None
        and option.target_id == target_id
        and _action_matches(intent.verb, option.action_hint)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _normalize_skills(
    requested: tuple[str, ...],
    allowed: tuple[str, ...] | set[str],
    view: PlayerView,
) -> tuple[str, ...]:
    allowed_ids = set(allowed)
    if not requested:
        return requested
    values = (*view.self_actor.attributes, *view.self_actor.skills)
    candidates = [
        (value.id, (value.id, value.name, *_actor_value_aliases(value.id)))
        for value in values
        if value.id in allowed_ids
    ]
    normalized: list[str] = []
    for skill in requested:
        if skill in allowed_ids:
            normalized.append(skill)
            continue
        matched = _unique_match(skill, candidates)
        normalized.append(matched or skill)
    return tuple(dict.fromkeys(normalized))


def _actor_value_ids(view: PlayerView) -> set[str]:
    return {
        value.id for value in (*view.self_actor.attributes, *view.self_actor.skills)
    }


_ACTOR_VALUE_ALIASES: dict[str, tuple[str, ...]] = {
    "spot-hidden": ("侦察", "侦查"),
    "listen": ("聆听", "倾听"),
    "credit-rating": ("信用评级", "信用", "信誉"),
    "fast-talk": ("话术", "快速交谈"),
    "STR": ("力量", "力气"),
    "CON": ("体质", "体力"),
    "SIZ": ("体型",),
    "DEX": ("敏捷",),
    "APP": ("外貌",),
    "INT": ("智力", "灵感"),
    "POW": ("意志",),
    "EDU": ("教育",),
    "LUCK": ("幸运", "运气"),
}


def _actor_value_aliases(value_id: str) -> tuple[str, ...]:
    return _ACTOR_VALUE_ALIASES.get(value_id, ())


def _action_matches(raw: str, action_hint: str) -> bool:
    return _action_family(raw) == _action_family(action_hint)


_ACTION_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "perception": (
        "observe",
        "look",
        "inspect",
        "investigate",
        "search",
        "examine",
        "观察",
        "侦察",
        "调查",
        "检查",
        "搜索",
        "查看",
    ),
    "social": ("social", "talk", "speak", "persuade", "交涉", "交谈", "说服", "沟通"),
    "intimidate": ("intimidate", "threaten", "恐吓", "威胁"),
    "bribe": ("bribe", "贿赂", "买通"),
    "travel": (
        "go",
        "travel",
        "approach",
        "前往",
        "靠近",
        "接近",
        "走向",
        "走近",
        "去",
        "走到",
    ),
    "enter": (
        "enter",
        "进入",
        "进去",
        "走进",
        "穿过",
        "钻入",
        "挤进",
        "下去",
    ),
    "move_object": (
        "move",
        "移动",
        "移开",
        "推开",
        "挪开",
        "搬开",
    ),
    "open": ("open", "打开", "开启"),
    "attack": ("attack", "fight", "shoot", "strike", "攻击", "殴打", "破坏"),
}


def _action_family(value: str) -> str:
    key = _label_key(value)
    for family, aliases in _ACTION_FAMILY_ALIASES.items():
        normalized_aliases = tuple(_label_key(alias) for alias in aliases)
        if key in normalized_aliases or any(
            len(alias) >= 2 and alias in key for alias in normalized_aliases
        ):
            return family
    return key


def _labels(value: VisibleEntity | AvailableExitView) -> tuple[str, ...]:
    return (value.id, value.name, *value.aliases)


def _unique_match(
    raw: str, candidates: list[tuple[str, tuple[str, ...]]]
) -> str | None:
    matches = {
        candidate_id
        for candidate_id, labels in candidates
        if any(_same_label(raw, label) for label in labels)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _same_label(left: str, right: str) -> bool:
    return _label_key(left) == _label_key(right)


def _label_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "S"))
    )
