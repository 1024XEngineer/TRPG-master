"""Host 侧的玩家可见持久声明校验，不读取 Engine 内部状态或事件载荷。

该模块只消费 Engine 已生成的 ``CommittedResult``，把 Narrator 文本中的确定性
持久声明限制在已有证据范围内；权威效果匹配仍由 engine/persistent_results.py 负责。
"""

from __future__ import annotations

import re

from pydantic import JsonValue

from collaboration_framework.contracts import CommittedResult, PlayerView

_PERSISTENT_CLAIMS: tuple[tuple[str, str, JsonValue], ...] = (
    # 中文叙事经常不用“昏迷”这个词，以下同义表达也必须受同一证据约束。
    (
        r"昏迷|昏倒|失去意识|失去知觉|不省人事|昏睡|没有醒来|仍未醒|尚未苏醒|闭着眼|双眼紧闭",
        "consciousness",
        "unconscious",
    ),
    (r"已经醒来|醒了过来|苏醒|恢复意识|恢复知觉", "consciousness", "conscious"),
    (r"死亡|死去|毙命|断气", "consciousness", "dead"),
    (r"倒地|倒下|趴在地上|躺在地上|躺着|躺在", "posture", "prone"),
    (r"站了起来|重新站起|起身站好", "posture", "standing"),
    (r"被束缚|被捆住|被绑住|动弹不得", "restraint", "restrained"),
    (r"已经获释|恢复自由|解开束缚|挣脱束缚", "restraint", "free"),
    (r"重伤", "injury", "major"),
    (r"受伤|负伤", "injury", "minor"),
    (r"伤势痊愈|已经痊愈|伤口愈合|恢复如初", "injury", "none"),
    (r"已经打开|被打开|敞开", "open", True),
    (r"已经关闭|被关闭|已经关上|已经合上", "open", False),
    (r"已经锁住|被锁住|上了锁", "locked", True),
    (r"已经解锁|被解锁|锁已打开|没有上锁", "locked", False),
    (r"已经损坏|被破坏|已经破碎|碎裂", "broken", True),
    (r"已经修好|被修好|修复完毕|恢复完好", "broken", False),
)
_QUOTED_TEXT = re.compile(r"[“\"『「][^”\"』」]*[”\"』」]")
_NON_ASSERTIVE_PREFIX = re.compile(
    r"(?:未|没有|并未|尚未|不会|不能|无法|如果|假如|倘若|是否|能否|想要|试图|准备|打算)$"
)
_ACTIVE_PRESENCE = re.compile(r"(?:正|仍|还)?(?:站在|站着|坐在|走来|走向|朝你走来)")
_PLAYER_PRESENCE = re.compile(r"你(?:们)?(?:正|仍|还)?(?:站在|站着|坐在|走来|走向)")
_ABSENT_PRESENCE = re.compile(
    r"人(?:却|已经|却已经)?不见|不在(?:这里|现场)|找不到(?:他|她)"
)


def unsupported_persistent_claim(
    text: str,
    committed_results: tuple[CommittedResult, ...],
    player_view: PlayerView | None = None,
) -> str | None:
    """返回首个缺少证据或与当前状态冲突的持久声明类别。

    ``committed_results`` 只覆盖本回合事件；``player_view`` 则覆盖之前回合
    已经写入并重新投影的公开状态，避免 NPC 状态跨回合丢失。
    """

    asserted_text = _QUOTED_TEXT.sub("", text)
    entities = () if player_view is None else player_view.scene.visible_entities
    for sentence in re.split(r"[。！？]", asserted_text):
        active_claim = _ACTIVE_PRESENCE.search(sentence)
        absent_claim = _ABSENT_PRESENCE.search(sentence)
        if (not active_claim and not absent_claim) or _PLAYER_PRESENCE.search(sentence):
            continue
        mentioned = tuple(
            entity
            for entity in entities
            if any(
                label and label in sentence
                for label in (
                    getattr(entity, "name", ""),
                    *getattr(entity, "aliases", ()),
                )
            )
        )
        # 当前 PlayerView 只投影标准场景实体，随行者或运行时对话人物可能暂未
        # 出现在 visible_entities。不能仅凭“未投影”判定叙事越权，否则会把正常
        # 的同行、交谈全部拒绝；这里只否决已有明确权威状态冲突的可见实体。
        if absent_claim and mentioned:
            return "entity_presence"
        for entity in mentioned:
            consciousness = next(
                (
                    state.value
                    for state in entity.observable_state
                    if state.key == "consciousness"
                ),
                None,
            )
            if active_claim and consciousness in {"dead", "unconscious"}:
                return "entity_presence"
    for pattern, key, value in _PERSISTENT_CLAIMS:
        for match in re.finditer(pattern, asserted_text):
            prefix = asserted_text[max(0, match.start() - 8) : match.start()]
            if _NON_ASSERTIVE_PREFIX.search(prefix):
                continue
            # 以句子中的可见名称绑定目标，避免把另一个 NPC 的状态套到当前目标上。
            sentence_start = (
                max(
                    asserted_text.rfind("。", 0, match.start()),
                    asserted_text.rfind("！", 0, match.start()),
                    asserted_text.rfind("？", 0, match.start()),
                )
                + 1
            )
            sentence = asserted_text[sentence_start : match.end()]
            mentioned_ids = {
                entity.id
                for entity in entities
                if any(
                    name and name in sentence
                    for name in (
                        getattr(entity, "name", ""),
                        *getattr(entity, "aliases", ()),
                    )
                )
            }
            # 持久事实必须绑定到句中明确出现的可见实体；无法绑定时宁可让
            # Narrator 重试，也不能把同类结果从另一个目标复用过来。
            if not mentioned_ids:
                return key
            has_evidence = any(
                result.state_key == key
                and _same_json_value(result.state_value, value)
                and result.target_id in mentioned_ids
                for result in committed_results
            )
            if not has_evidence and player_view is not None:
                has_evidence = any(
                    state.key == key
                    and _same_json_value(state.value, value)
                    and entity.id in mentioned_ids
                    for entity in player_view.scene.visible_entities
                    for state in entity.observable_state
                )
            if not has_evidence:
                return key
    return None


def _same_json_value(left: JsonValue, right: JsonValue) -> bool:
    """持久声明证据同时匹配 JSON 值与类型，避免 0/1 冒充布尔状态。"""

    return type(left) is type(right) and left == right
