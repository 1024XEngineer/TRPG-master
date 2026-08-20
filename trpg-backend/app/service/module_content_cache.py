"""已发布模组内容的进程内缓存 (#347 P4)。

每次玩家行动会触发 5~10 次 `load_runtime`，而每一次都要把整份
`content_json` 深拷贝一遍再完整重新校验成 pydantic 树。模组一旦发布就
不可变（`builtin_module_loader` 拒绝用不同内容覆盖同一
`(module_id, version)`），所以这份解析结果本可以复用。

**为什么缓存的是 pickle 字节而不是解析好的对象。** 调用方拿到的模组内容
必须是彼此隔离的：任何一方就地改动都不能影响下一次读取，也不能污染
SQLAlchemy 行上的 `content_json`。所以命中时不能直接把同一个对象发出去，
必须现做一棵新树。实测（追书人，96KB）三种做法产出一棵隔离的树的成本：

| 做法 | 单次耗时 |
|---|---|
| `deepcopy(content_json)` + `model_validate`（改动前） | 3.02 ms |
| 缓存已解析对象 + `model_copy(deep=True)` | 3.08 ms |
| 缓存 pickle 字节 + `pickle.loads` | 1.03 ms |

缓存解析结果再深拷贝**比不缓存还慢**，只有 pickle 这条路是真的省。
`pickle.loads` 每次重建一整套全新对象，隔离性与深拷贝等价。这里
`pickle` 的输入永远是本进程自己刚 `dumps` 出来的字节，不接受任何外部
数据，不存在反序列化不可信输入的问题。

**为什么键里带内容指纹。** `version` 是模组作者手填的自由字符串，仓库层面
没有任何自动递增或唯一性机制。只按 `(module_id, version)` 缓存的话，作者
改了内容却忘记改版本号时，缓存会一直返回过期内容且没有任何报错信号——这
类静默失效比多花几毫秒糟糕得多。把内容指纹并进键之后，内容一变就是一次
未命中、重新解析，不可能读到过期结果。指纹本身约 0.5 ms，命中总成本
1.53 ms，相比改动前仍省约一半。

指纹不对键排序：同样的内容若序列化顺序不同，只会白白未命中、重新解析一
次，不会命中到错误的内容，用 0.2 ms 换一个不必要的保证不划算。
"""

from __future__ import annotations

import json
import pickle
from collections import OrderedDict
from copy import deepcopy
from hashlib import blake2b
from typing import NamedTuple

from collaboration_framework.contracts import ModuleContent, ModuleContentV3

# 一个进程同时在玩的模组版本数远小于这个上限；留出余量后按 LRU 淘汰，
# 避免作者反复改内容不改版本号时条目无限增长。单条约 60KB。
MAX_ENTRIES = 16

_CacheKey = tuple[str, str, int, bytes]

_entries: OrderedDict[_CacheKey, bytes] = OrderedDict()
_hits = 0
_misses = 0


class CacheInfo(NamedTuple):
    hits: int
    misses: int
    size: int


def cache_info() -> CacheInfo:
    """当前命中计数与条目数，仅供测试与排查使用。"""

    return CacheInfo(hits=_hits, misses=_misses, size=len(_entries))


def clear() -> None:
    """清空缓存与计数。"""

    global _hits, _misses
    _entries.clear()
    _hits = 0
    _misses = 0


def _fingerprint(content_json: dict) -> bytes:
    serialized = json.dumps(content_json, separators=(",", ":")).encode("utf-8")
    return blake2b(serialized, digest_size=16).digest()


def load_module_content(
    *,
    module_id: str,
    version: str,
    content_schema_version: int,
    content_json: dict,
) -> ModuleContent | ModuleContentV3:
    """返回一棵与缓存、与 `content_json` 都完全隔离的模组内容树。

    调用方可以随意就地修改返回值，既不会影响下一次调用，也不会写回
    SQLAlchemy 行上的 `content_json`。
    """

    global _hits, _misses

    key: _CacheKey = (
        module_id,
        version,
        content_schema_version,
        _fingerprint(content_json),
    )
    blob = _entries.get(key)
    if blob is not None:
        _entries.move_to_end(key)
        _hits += 1
        return pickle.loads(blob)  # noqa: S301 — 输入是本进程自己 dumps 的字节

    _misses += 1
    # 未命中时逐字沿用改动前的解析方式：先深拷贝再校验，保证行为完全一致。
    payload = deepcopy(content_json)
    content: ModuleContent | ModuleContentV3 = (
        ModuleContentV3.model_validate(payload)
        if content_schema_version == 3
        else ModuleContent.model_validate(payload)
    )
    _entries[key] = pickle.dumps(content, protocol=pickle.HIGHEST_PROTOCOL)
    _entries.move_to_end(key)
    while len(_entries) > MAX_ENTRIES:
        _entries.popitem(last=False)
    return content
