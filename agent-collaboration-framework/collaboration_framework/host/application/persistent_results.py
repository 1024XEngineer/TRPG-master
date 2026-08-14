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
    (r"死亡|死去|毙命|断气", "consciousness", "dead"),
    (r"倒地|倒下|趴在地上|躺在地上|躺着|躺在", "posture", "prone"),
    (r"被束缚|被捆住|被绑住|动弹不得", "restraint", "restrained"),
    (r"重伤", "injury", "major"),
    (r"受伤|负伤", "injury", "minor"),
    (r"已经打开|被打开|敞开", "open", True),
    (r"已经锁住|被锁住|上了锁", "locked", True),
    (r"已经损坏|被破坏|已经破碎|碎裂", "broken", True),
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
_INVENTORY_ACQUISITION = re.compile(
    r"捡起|拾起|拿起|拿走|取走|收好|收下|带走|收入囊中|"
    r"(?:放|装|塞|收)(?:入|进|到).{0,10}(?:背包|行囊|口袋|物品栏)|"
    r"(?:背包|行囊|口袋|物品栏)(?:里|中)?(?:多了|有了|装着|放着|收着)"
)
_NON_ASSERTIVE_ACQUISITION = re.compile(
    r"未|没有|没能|并未|不能|无法|不曾|试图|尝试|打算|准备|想要|却没"
)
_ITEM_PRONOUN = re.compile(r"它们?|该物品|此物")


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
            has_evidence = any(
                result.state_key == key
                and result.state_value == value
                and (not mentioned_ids or result.target_id in mentioned_ids)
                for result in committed_results
            )
            if not has_evidence and player_view is not None:
                has_evidence = any(
                    state.key == key
                    and state.value == value
                    and (not mentioned_ids or entity.id in mentioned_ids)
                    for entity in player_view.scene.visible_entities
                    for state in entity.observable_state
                )
            if not has_evidence:
                return key
    return None


def unsupported_inventory_acquisition_claim(
    text: str,
    committed_results: tuple[CommittedResult, ...],
    player_view: PlayerView,
) -> str | None:
    """Reject prose that claims an acquisition absent from final inventory.

    An ``entity.moved`` event by itself is insufficient: older behavior could
    attach ``holder_actor_id`` to a generic entity while inventory projection
    ignored it.  A truthful acquisition therefore needs both a current-turn
    inventory result and the same id in the final PlayerView inventory.
    """

    result_ids = {
        result.target_id for result in committed_results if result.kind == "inventory"
    }
    confirmed_items = tuple(
        item for item in player_view.inventory if item.id in result_ids
    )
    asserted_text = _QUOTED_TEXT.sub("", text)
    for sentence in re.split(r"[。！？!?]", asserted_text):
        match = _INVENTORY_ACQUISITION.search(sentence)
        if match is None:
            continue
        prefix = sentence[max(0, match.start() - 12) : match.start()]
        if _NON_ASSERTIVE_ACQUISITION.search(prefix):
            continue
        if not confirmed_items:
            return "inventory_acquisition"
        if any(_mentions_inventory_item(sentence, item.name) for item in confirmed_items):
            continue
        if len(confirmed_items) == 1 and _ITEM_PRONOUN.search(sentence):
            continue
        return "inventory_acquisition"
    return None


def _mentions_inventory_item(sentence: str, name: str) -> bool:
    """Match a displayed item name without maintaining an item allowlist."""

    compact_name = re.sub(r"\s+", "", name).casefold()
    compact_sentence = re.sub(r"\s+", "", sentence).casefold()
    if compact_name and compact_name in compact_sentence:
        return True
    cjk_name = "".join(character for character in compact_name if "一" <= character <= "鿿")
    # Display names commonly carry a quantity or adjective before the actual
    # noun.  A trailing CJK name segment lets prose use that ordinary noun
    # while still requiring correspondence with the confirmed item.
    for width in range(len(cjk_name), 1, -1):
        if cjk_name[-width:] in compact_sentence:
            return True
    words = tuple(re.findall(r"[a-z0-9]+", compact_name))
    return bool(words) and words[-1] in compact_sentence
