"""Host 侧的玩家可见持久声明校验，不读取 Engine 内部状态或事件载荷。

该模块只消费 Engine 已生成的 ``CommittedResult``，把 Narrator 文本中的确定性
持久声明限制在已有证据范围内；权威效果匹配仍由 engine/persistent_results.py 负责。

这里的判据分两层。主力是 ``ActionPlanNarrationOutput`` 的结构化申报字段——写下
正文的模型自报它声称了什么，服务端只做对引擎真值的集合包含判断（见
``action_plan_narrator``）。本模块承担的是申报不足时的守门补丁：模型漏填字段却在
正文里写了断言时，用**权威数据界定的窄窗口**兜住，命中后由调用方做句级降级而不是
丢弃整段正文。窄窗口的意思是——判定必须绑定到闭集（最终 inventory、场景散落物、
可见实体）上的具体对象，不能只凭一张中文动词表。
"""

from __future__ import annotations

import re
from typing import NamedTuple

from pydantic import JsonValue

from collaboration_framework.contracts import CommittedResult, PlayerView


class ClaimRejection(NamedTuple):
    """一条被拒的持久声明：类别，以及它在原文中的句子区间。

    ``start`` / ``end`` 是**原始 text** 的下标，调用方据此剔除违规小句后保留其余
    正文。为此屏蔽引语时按等长空白替换而不是删除，下标才不会错位。
    """

    reason: str
    start: int
    end: int


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
# 句子区间要连着句末标点一起给出，剔除违规小句时才不会留下孤零零的句号。
_SENTENCE_SPAN = re.compile(r"[^。！？!?\n]+[。！？!?\n]*")
# 小句边界：动词的论元只可能落在同一个小句里。
_CLAUSE_DELIMITERS = "，,、；;：:"
_NON_ASSERTIVE_PREFIX = re.compile(
    r"(?:未|没有|并未|尚未|不会|不能|无法|如果|假如|倘若|是否|能否|想要|试图|准备|打算)$"
)
_ACTIVE_PRESENCE = re.compile(r"(?:正|仍|还)?(?:站在|站着|坐在|走来|走向|朝你走来)")
_PLAYER_PRESENCE = re.compile(r"你(?:们)?(?:正|仍|还)?(?:站在|站着|坐在|走来|走向)")
_ABSENT_PRESENCE = re.compile(
    r"人(?:却|已经|却已经)?不见|不在(?:这里|现场)|找不到(?:他|她)"
)
# 明确的入包声明：目的地本身就是“玩家背包”这个权威概念，不依赖任何语义猜测。
# 中间的填充不得跨小句，否则“把照片放进相框，然后打开背包”会被并成一次入包声明。
_INVENTORY_DEPOSIT = re.compile(
    rf"(?:放|装|塞|收)(?:入|进|到)[^{_CLAUSE_DELIMITERS}。！？!?]{{0,10}}"
    r"(?:背包|行囊|口袋|物品栏)|"
    r"(?:背包|行囊|口袋|物品栏)(?:里|中)?(?:多了|有了|装着|放着|收着)"
)
# 取得类动词但没有显式容器。“收好”既可以是收进背包，也可以是把书放回架上；
# 这一层只有绑定到权威物品名时才判定，不能单凭动词。
# 注意这里没有“拿起/拾起/捡起”：它们在中文里表示瞬时持握（拿起电话拨号、拿起
# 茶杯抿一口），本就不承载“取得”语义，是 #512 全部误杀的来源。
_INVENTORY_TAKEAWAY = re.compile(r"拿走|取走|收好|收下|带走|收入囊中")
_NON_ASSERTIVE_ACQUISITION = re.compile(
    r"未|没有|没能|并未|不能|无法|不曾|试图|尝试|打算|准备|想要|却没"
)
_ITEM_PRONOUN = re.compile(r"它们?|该物品|此物")


def _mask_quoted(text: str) -> str:
    """按等长空白屏蔽引语，保持后续下标与原文一致。"""

    return _QUOTED_TEXT.sub(lambda match: " " * len(match.group(0)), text)


def sentence_span_at(text: str, index: int) -> tuple[int, int]:
    """返回包含 ``index`` 的句子区间；没有命中时退回整段。"""

    for match in _SENTENCE_SPAN.finditer(text):
        if match.start() <= index < match.end():
            return match.start(), match.end()
    return 0, len(text)


def _clause_at(sentence: str, start: int, end: int) -> str:
    """返回 ``[start, end)`` 所在的小句，用于把物品名绑定到动词的论元位。"""

    left = start
    while left > 0 and sentence[left - 1] not in _CLAUSE_DELIMITERS:
        left -= 1
    right = end
    while right < len(sentence) and sentence[right] not in _CLAUSE_DELIMITERS:
        right += 1
    return sentence[left:right]


def _labels_of(entity: object) -> tuple[str, ...]:
    return tuple(
        label
        for label in (getattr(entity, "name", ""), *getattr(entity, "aliases", ()))
        if label
    )


def unsupported_persistent_claim(
    text: str,
    committed_results: tuple[CommittedResult, ...],
    player_view: PlayerView | None = None,
) -> ClaimRejection | None:
    """返回首个缺少证据或与当前状态冲突的持久声明及其所在句子。

    ``committed_results`` 只覆盖本回合事件；``player_view`` 则覆盖之前回合
    已经写入并重新投影的公开状态，避免 NPC 状态跨回合丢失。

    这里仍然保留状态动词表。状态断言的闭集锚点是可见实体名，而
    ``visible_entities`` 并不是“可被合法提及的角色”的全集（随行者、运行时对话
    人物都可能不在其中，见下方注释），把词表收窄到“必须点名可见实体”会放行
    “守墓人昏迷了”这类点名场外实体的无证据断言。词表因此留作兜底，其误判代价
    由调用方的句级降级阶梯承担——被拒的是一小句，不再是整段正文。
    """

    asserted_text = _mask_quoted(text)
    entities = () if player_view is None else player_view.scene.visible_entities
    for span in _SENTENCE_SPAN.finditer(asserted_text):
        sentence = span.group(0)
        active_claim = _ACTIVE_PRESENCE.search(sentence)
        absent_claim = _ABSENT_PRESENCE.search(sentence)
        if (not active_claim and not absent_claim) or _PLAYER_PRESENCE.search(sentence):
            continue
        mentioned = tuple(
            entity
            for entity in entities
            if any(label in sentence for label in _labels_of(entity))
        )
        # 当前 PlayerView 只投影标准场景实体，随行者或运行时对话人物可能暂未
        # 出现在 visible_entities。不能仅凭“未投影”判定叙事越权，否则会把正常
        # 的同行、交谈全部拒绝；这里只否决已有明确权威状态冲突的可见实体。
        if absent_claim and mentioned:
            return ClaimRejection("entity_presence", span.start(), span.end())
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
                return ClaimRejection("entity_presence", span.start(), span.end())
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
            mentioned_entities = tuple(
                entity
                for entity in entities
                if any(name in sentence for name in _labels_of(entity))
            )
            mentioned_ids = {entity.id for entity in mentioned_entities}
            if key == "posture":
                character_ids = {
                    entity.id
                    for entity in mentioned_entities
                    if getattr(entity, "kind", "npc") == "npc"
                }
                if mentioned_entities and not character_ids:
                    # “钥匙躺在桌上”描述的是物件位置，不是角色姿态。
                    continue
                if character_ids:
                    mentioned_ids = character_ids
                elif (
                    player_view is not None
                    and entities
                    and not any(
                        getattr(entity, "kind", "npc") == "npc" for entity in entities
                    )
                ):
                    # 没有点名实体且场景只有物件时，属于环境描写而非角色姿态。
                    continue
            if key == "posture" and player_view is not None and entities and not mentioned_ids:
                # 无名称指代仍需绑定唯一可见 NPC，不能用任意一条姿态证据背书。
                candidate_ids = {
                    entity.id
                    for entity in entities
                    if getattr(entity, "kind", "npc") == "npc"
                }
                evidence_target_ids = {
                    result.target_id
                    for result in committed_results
                    if result.state_key == key and result.state_value == value
                }
                evidence_target_ids.update(
                    entity.id
                    for entity in entities
                    if any(
                        state.key == key and state.value == value
                        for state in entity.observable_state
                    )
                )
                has_evidence = (
                    len(candidate_ids) == 1
                    and candidate_ids.issubset(evidence_target_ids)
                )
            else:
                has_evidence = any(
                    result.state_key == key
                    and result.state_value == value
                    and (not mentioned_ids or result.target_id in mentioned_ids)
                    for result in committed_results
                )
            if not has_evidence and player_view is not None and not (
                key == "posture" and entities and not mentioned_ids
            ):
                has_evidence = any(
                    state.key == key
                    and state.value == value
                    and (not mentioned_ids or entity.id in mentioned_ids)
                    for entity in player_view.scene.visible_entities
                    for state in entity.observable_state
                )
            if not has_evidence:
                start, end = sentence_span_at(asserted_text, match.start())
                return ClaimRejection(key, start, end)
    return None


def unsupported_inventory_acquisition_claim(
    text: str,
    committed_results: tuple[CommittedResult, ...],
    player_view: PlayerView,
) -> ClaimRejection | None:
    """Reject prose that claims an acquisition absent from the final inventory.

    主力判据是 ``ActionPlanNarrationOutput.claimed_inventory_ids`` 的集合包含校验；
    本函数只兜“正文声称了却没有申报”的那一半，并按声明的强弱分两级：

    * **明确入包声明**（“放进背包 / 收进口袋 / 背包里多了……”）——目的地本身就是
      玩家背包这个权威概念，无需任何语义猜测，因此无条件要求正文点名一件确实在
      最终 ``player_view.inventory`` 里的物品。判据是最终 inventory 而不是“本回合
      inventory 结果 ∩ 最终 inventory”：承重的一直是前者（只有移动事件而最终背包
      没有该 id，正是它挡下的），而后者会把“传单上一回合就已入包”的正常复述也拒掉。
    * **无容器的取得类动词**（“带走 / 取走 / 收好”）——中文里它们既可能是取得，也
      可能只是收拾归位，单凭动词无法判别。只有当动词所在**小句**里出现了权威物品名
      （场景散落物 ∪ 可见实体 ∪ 最终背包），且该物品不在最终背包时才判定。小句这一
      层不能省：“你拿起电话，拨打了传单上的号码”整句里确实有权威物品名“传单”，但
      它不是该动词的论元。
    """

    inventory = tuple(getattr(player_view, "inventory", ()) or ())
    held_ids = {item.id for item in inventory}
    scene = getattr(player_view, "scene", None)
    entities = tuple(getattr(scene, "visible_entities", ()) or ())
    # 权威物品名闭集：场景散落物、可见实体与最终背包，全部来自 PlayerView 投影。
    known_objects = (
        *(getattr(scene, "loose_items", ()) or ()),
        *entities,
        *inventory,
    )
    asserted_text = _mask_quoted(text)
    for span in _SENTENCE_SPAN.finditer(asserted_text):
        sentence = span.group(0)
        deposit = _INVENTORY_DEPOSIT.search(sentence)
        takeaway = _INVENTORY_TAKEAWAY.search(sentence)
        match = deposit or takeaway
        if match is None:
            continue
        prefix = sentence[max(0, match.start() - 12) : match.start()]
        if _NON_ASSERTIVE_ACQUISITION.search(prefix):
            continue
        clause = _clause_at(sentence, match.start(), match.end())
        # 主语是在场 NPC 时，这句描述的是别人的动作，与玩家背包无关。
        # 与 #425 对 posture 的实体类型判别同一形状：闭集、按 kind 判别。
        if any(
            getattr(entity, "kind", "npc") == "npc"
            and any(label in clause for label in _labels_of(entity))
            for entity in entities
        ):
            continue
        if deposit is not None:
            if any(_mentions_inventory_item(sentence, item.name) for item in inventory):
                continue
            if len(inventory) == 1 and _ITEM_PRONOUN.search(sentence):
                continue
            return ClaimRejection("inventory_acquisition", span.start(), span.end())
        named = tuple(
            item
            for item in known_objects
            if any(_mentions_inventory_item(clause, label) for label in _labels_of(item))
        )
        if named and all(getattr(item, "id", None) not in held_ids for item in named):
            return ClaimRejection("inventory_acquisition", span.start(), span.end())
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
