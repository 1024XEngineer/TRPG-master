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
    (r"昏迷|昏倒|失去意识|失去知觉|不省人事|昏睡|没有醒来|仍未醒|尚未苏醒|闭着眼|双眼紧闭", "consciousness", "unconscious"),
    (r"死亡|死去|毙命|断气", "consciousness", "dead"),
    (r"醒来|醒着|恢复意识|重新获得意识|清醒", "consciousness", "conscious"),
    (r"倒地|倒下|趴在地上|躺在地上|躺着|躺在", "posture", "prone"),
    (r"站起|站起来|站立着|直立", "posture", "standing"),
    (r"被束缚|被捆住|被绑住|动弹不得", "restraint", "restrained"),
    (r"挣脱束缚|解除束缚|恢复自由|不再受束缚", "restraint", "free"),
    (r"重伤|严重受伤", "injury", "major"),
    (r"危重伤|伤势危重|伤势危急", "injury", "critical"),
    (r"(?<!重)受伤|负伤", "injury", "minor"),
    (r"伤势痊愈|恢复健康|完好无损", "injury", "none"),
    (r"已经打开|被打开|敞开", "open", True),
    (r"关上|关闭|闭合|已经关好", "open", False),
    (r"已经锁住|被锁住|上了锁", "locked", True),
    (r"解锁|锁已解开|锁已经解开|解除锁定|没有上锁", "locked", False),
    (r"已经损坏|被破坏|已经破碎|碎裂", "broken", True),
    (r"修好|修复完成|恢复原状|完整无损", "broken", False),
)
_QUOTED_TEXT = re.compile(r"[“\"『「][^”\"』」]*[”\"』」]")
_NON_ASSERTIVE_PREFIX = re.compile(
    r"(?:未|没有|并未|尚未|不会|不能|无法|如果|假如|倘若|是否|能否|想要|试图|准备|打算)$"
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
    for pattern, key, value in _PERSISTENT_CLAIMS:
        for match in re.finditer(pattern, asserted_text):
            prefix = asserted_text[max(0, match.start() - 8) : match.start()]
            if _NON_ASSERTIVE_PREFIX.search(prefix):
                continue
            # 以句子中的可见名称绑定目标，避免把另一个 NPC 的状态套到当前目标上。
            sentence_start = max(
                asserted_text.rfind("。", 0, match.start()),
                asserted_text.rfind("！", 0, match.start()),
                asserted_text.rfind("？", 0, match.start()),
            ) + 1
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
            evidence_target_ids = {
                result.target_id
                for result in committed_results
                if result.state_key == key and result.state_value == value
            }
            if player_view is not None:
                evidence_target_ids.update(
                    entity.id
                    for entity in player_view.scene.visible_entities
                    if any(
                        state.key == key and state.value == value
                        for state in entity.observable_state
                    )
                )
            if mentioned_ids:
                # 多实体同句必须逐一有证据，不能只凭其中一个实体背书整句。
                has_evidence = mentioned_ids.issubset(evidence_target_ids)
            else:
                # “他/目标”等指代必须同时满足“场景中只有一个可能目标”和
                # “该目标有精确证据”；只有一个有证据的 NPC 并不代表它是
                # 唯一目标，否则会把 NPC A 的状态错误套到 NPC B 身上。
                character_keys = {"consciousness", "posture", "restraint", "injury"}
                expected_kind = "npc" if key in character_keys else "object"
                candidate_ids = {
                    entity.id
                    for entity in entities
                    if getattr(entity, "kind", "npc") == expected_kind
                }
                if entities:
                    # 有场景投影时，候选必须来自当前可见实体，避免跨实体串状态。
                    has_evidence = (
                        len(candidate_ids) == 1
                        and candidate_ids.issubset(evidence_target_ids)
                    )
                else:
                    # 旧调用方可能只提供本回合证据而没有场景投影，保持兼容。
                    has_evidence = len(evidence_target_ids) == 1
            if not has_evidence:
                return key
    return None
