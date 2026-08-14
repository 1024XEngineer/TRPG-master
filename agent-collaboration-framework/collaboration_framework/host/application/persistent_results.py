"""Host 侧的玩家可见持久声明校验，不读取 Engine 内部状态或事件载荷。

该模块只消费 Engine 已生成的 ``CommittedResult``，把 Narrator 文本中的确定性
持久声明限制在已有证据范围内；权威效果匹配仍由 engine/persistent_results.py 负责。
"""

from __future__ import annotations

import re

from pydantic import JsonValue

from collaboration_framework.contracts import CommittedResult

_PERSISTENT_CLAIMS: tuple[tuple[str, str, JsonValue], ...] = (
    (r"昏迷|昏倒|失去意识|不省人事", "consciousness", "unconscious"),
    (r"死亡|死去|毙命|断气", "consciousness", "dead"),
    (r"倒地|倒下|趴在地上", "posture", "prone"),
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


def unsupported_persistent_claim(
    text: str,
    committed_results: tuple[CommittedResult, ...],
) -> str | None:
    """返回首个缺少已提交证据的持久声明类别。"""

    asserted_text = _QUOTED_TEXT.sub("", text)
    for pattern, key, value in _PERSISTENT_CLAIMS:
        for match in re.finditer(pattern, asserted_text):
            prefix = asserted_text[max(0, match.start() - 8) : match.start()]
            if _NON_ASSERTIVE_PREFIX.search(prefix):
                continue
            if not any(
                result.state_key == key and result.state_value == value
                for result in committed_results
            ):
                return key
    return None
