"""Deterministic alignment from model semantics to Rule Engine action ids."""

from __future__ import annotations

from collaboration_framework.contracts import (
    CheckpointOption,
    ContractError,
    Intent,
    JsonObject,
    MatchedTarget,
    ModuleCheck,
    NoCheck,
)
from collaboration_framework.host.schemas import IntentContext

# These ids are consumed by the current Rule Engine: checkpoint actions,
# Entity direct/refused operations, or ``action.type`` expressions.  The set is
# intentionally a vocabulary, not an authorization list; current PlayerView
# targets and checkpoint options remain the authority boundary.
REFERENCE_MODULE_ACTIONS = frozenset(
    {
        "analyze",
        "approach",
        "ask_about_anomalies",
        "ask_about_disappearances",
        "ask_about_ezra",
        "ask_about_water",
        "ask_to_go_home",
        "ask_to_leave",
        "ask_why_stay",
        "assess",
        "break",
        "bribe",
        "call_name",
        "cement_crypt",
        "chase",
        "communicate",
        "cross",
        "cut",
        "dig",
        "dive",
        "draw",
        "enter",
        "escape",
        "evade",
        "feed",
        "flee",
        "follow",
        "hack",
        "illuminate",
        "infiltrate",
        "inspect",
        "insult_messenger",
        "interview",
        "intimidate",
        "investigate",
        "let_leave",
        "listen",
        "look",
        "move",
        "observe",
        "open",
        "persuade",
        "polite_question",
        "pull_down",
        "question",
        "read",
        "reassure",
        "recover",
        "recruit",
        "request",
        "request_access",
        "rescue",
        "research",
        "resist",
        "retrieve_without_diving",
        "reveal_evidence",
        "search",
        "social",
        "spot",
        "study",
        "surveil",
        "talk",
        "tear",
        "touch",
        "track",
        "traverse",
        "treat",
        "understand",
        "unlock",
        "verify",
        "wake",
    }
)

# The demo fixture is executable module content too, although it is not one of
# the validation examples under docs/.
REFERENCE_FIXTURE_ACTIONS = frozenset({"smash"})

CORE_ENGINE_ACTIONS = frozenset({"go", "attack", "wait", "wait_until_night"})
RULE_ENGINE_ACTION_VOCABULARY = (
    REFERENCE_MODULE_ACTIONS | REFERENCE_FIXTURE_ACTIONS | CORE_ENGINE_ACTIONS
)

_ATTACK_ALIASES = frozenset(
    {
        "attack",
        "fight",
        "shoot",
        "strike",
        "攻击",
        "开枪",
        "射击",
        "战斗",
        "打",
        "殴打",
        "袭击",
        "揍",
    }
)
_WAIT_ALIASES = frozenset(
    {
        "rest",
        "time_elapsed",
        "wait",
        "休息",
        "停留",
        "等待",
        "等候",
        "消磨时间",
    }
)
_WAIT_UNTIL_NIGHT_ALIASES = frozenset(
    {
        "wait_until_night",
        "守到天黑",
        "等到夜晚",
        "等到晚上",
        "等天黑",
    }
)
_TRAVEL_VERB_ALIASES = frozenset(
    {
        "go",
        "go_to",
        "head_to",
        "leave",
        "move",
        "travel",
        "出发",
        "到",
        "前去",
        "前往",
        "去",
        "去往",
        "回到",
        "抵达",
        "离开",
        "移动",
        "移动到",
        "走",
        "走到",
        "走向",
        "返回",
        "进入",
    }
)
_TRAVEL_TEXT_MARKERS = (
    "go to",
    "head to",
    "leave",
    "move to",
    "travel",
    "出发",
    "前去",
    "前往",
    "带我去",
    "我去",
    "我要去",
    "我想去",
    "去往",
    "回到",
    "想去",
    "抵达",
    "离开",
    "移动到",
    "走到",
    "走向",
    "继续去",
    "直接去",
    "返回",
    "进入",
)

# Localized model output is normalized only when one canonical id is
# unambiguous.  Distinct module action ids such as inspect/observe/investigate
# are deliberately kept distinct because modules attach different checkpoints
# and direct responses to them.
_UNAMBIGUOUS_ACTION_ALIASES = {
    "分析": "analyze",
    "接近": "approach",
    "评估": "assess",
    "打破": "break",
    "破坏": "break",
    "贿赂": "bribe",
    "叫名字": "call_name",
    "呼喊名字": "call_name",
    "追赶": "chase",
    "追逐": "chase",
    "沟通": "communicate",
    "穿越": "cross",
    "切割": "cut",
    "割开": "cut",
    "挖": "dig",
    "挖掘": "dig",
    "潜水": "dive",
    "拔出": "draw",
    "进入": "enter",
    "逃脱": "escape",
    "躲避": "evade",
    "喂食": "feed",
    "逃跑": "flee",
    "跟随": "follow",
    "黑入": "hack",
    "照亮": "illuminate",
    "渗透": "infiltrate",
    "检查": "inspect",
    "查看": "inspect",
    "采访": "interview",
    "访谈": "interview",
    "威吓": "intimidate",
    "恐吓": "intimidate",
    "调查": "investigate",
    "放走": "let_leave",
    "倾听": "listen",
    "聆听": "listen",
    "看": "look",
    "看看": "look",
    "移动": "move",
    "观察": "observe",
    "打开": "open",
    "说服": "persuade",
    "礼貌询问": "polite_question",
    "拉下": "pull_down",
    "提问": "question",
    "询问": "question",
    "阅读": "read",
    "安抚": "reassure",
    "恢复": "recover",
    "招募": "recruit",
    "请求": "request",
    "申请访问": "request_access",
    "请求进入": "request_access",
    "营救": "rescue",
    "研究": "research",
    "抵抗": "resist",
    "揭示证据": "reveal_evidence",
    "搜索": "search",
    "搜查": "search",
    "社交": "social",
    "察觉": "spot",
    "研读": "study",
    "监视": "surveil",
    "交谈": "talk",
    "对话": "talk",
    "撕开": "tear",
    "触摸": "touch",
    "追踪": "track",
    "治疗": "treat",
    "理解": "understand",
    "解锁": "unlock",
    "核实": "verify",
    "叫醒": "wake",
    "唤醒": "wake",
    "砸": "smash",
    "砸开": "smash",
}

def intent_action_contract() -> JsonObject:
    """Return the provider-neutral action vocabulary included in model input."""

    return {
        "core_actions": {
            "travel": "go",
            "attack": "attack",
            "ordinary_wait": "wait",
            "wait_until_night": "wait_until_night",
        },
        "module_action_vocabulary": sorted(REFERENCE_MODULE_ACTIONS),
    }


def align_intent_for_engine(intent: Intent, context: IntentContext) -> Intent:
    """Align equivalent model wording to the exact ids consumed by the Engine."""

    if not isinstance(intent.target, MatchedTarget):
        available_exit = _match_available_exit(context)
        if available_exit is None:
            return intent.model_copy(
                update={
                    "declarations": (),
                    "initiated_by_target": False,
                }
            )
        return Intent(
            kind="action",
            verb="go",
            target=MatchedTarget(id=available_exit.id),
            check=NoCheck(),
            approach=intent.approach,
            declarations=(),
            initiated_by_target=False,
            summary=intent.summary,
        )

    verb = intent.verb.strip()
    declarations: tuple[str, ...] = ()
    if not isinstance(intent.check, ModuleCheck) and intent.declarations:
        raise ContractError("只有 Module Check 可以携带 declaration")
    if isinstance(intent.check, ModuleCheck):
        option = next(
            (
                candidate
                for candidate in context.player_view.checkpoint_options
                if candidate.id == intent.check.checkpoint_id
            ),
            None,
        )
        if option is None:
            raise ContractError("Intent checkpoint 不在可信候选中")
        verb = option.action_hint
        declarations = _validate_checkpoint_declarations(
            intent.declarations,
            option,
        )
    elif any(
        candidate.id == intent.target.id
        for candidate in context.player_view.scene.available_exits
    ):
        if not _has_travel_semantics(intent.verb, context.player_input.utterance):
            raise ContractError("available exit 只能作为移动动作目标")
        verb = "go"
    else:
        verb = _canonicalize_action_verb(verb)

    update: dict[str, object] = {
        "verb": verb,
        "declarations": declarations,
        # A PlayerInput can never authorize an NPC/target-initiated rule hook.
        "initiated_by_target": False,
    }
    if verb in CORE_ENGINE_ACTIONS:
        update["kind"] = "action"
    return intent.model_copy(update=update)


def _canonicalize_action_verb(verb: str) -> str:
    normalized = _normalize_token(verb)
    if normalized in _ATTACK_ALIASES:
        return "attack"
    if normalized in _WAIT_UNTIL_NIGHT_ALIASES:
        return "wait_until_night"
    if normalized in _WAIT_ALIASES:
        return "wait"
    localized = _UNAMBIGUOUS_ACTION_ALIASES.get(normalized)
    if localized is not None:
        return localized
    if normalized in RULE_ENGINE_ACTION_VOCABULARY:
        return normalized
    return verb


def _validate_checkpoint_declarations(
    proposed: tuple[str, ...],
    option: CheckpointOption,
) -> tuple[str, ...]:
    allowed = {item.id for item in option.declaration_options}
    if not set(proposed).issubset(allowed):
        raise ContractError("Intent declaration 不属于当前 Checkpoint 候选")
    aligned: list[str] = []
    for declaration in proposed:
        if declaration not in aligned:
            aligned.append(declaration)
    return tuple(aligned)


def _match_available_exit(context: IntentContext):
    utterance = context.player_input.utterance.strip().casefold()
    if not _has_travel_semantics("", utterance):
        return None
    destination_text = utterance
    for marker in sorted(_TRAVEL_TEXT_MARKERS, key=len, reverse=True):
        destination_text = destination_text.replace(marker, "")
    destination_text = destination_text.strip(" ，。！？,.!?")
    matches = []
    for available_exit in context.player_view.scene.available_exits:
        candidates = [
            available_exit.id,
            available_exit.name,
            *available_exit.aliases,
        ]
        if available_exit.destination is not None:
            candidates.extend(
                [
                    available_exit.destination.scene_id,
                    available_exit.destination.name,
                ]
            )
        if any(
            candidate
            and (
                candidate.casefold() in utterance
                or (
                    destination_text
                    and destination_text in candidate.casefold()
                )
            )
            for candidate in candidates
        ):
            matches.append(available_exit)
    return matches[0] if len(matches) == 1 else None


def _has_travel_semantics(verb: str, utterance: str) -> bool:
    normalized_verb = _normalize_token(verb)
    normalized_utterance = utterance.strip().casefold()
    return normalized_verb in _TRAVEL_VERB_ALIASES or any(
        marker in normalized_utterance for marker in _TRAVEL_TEXT_MARKERS
    )


def _normalize_token(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")
