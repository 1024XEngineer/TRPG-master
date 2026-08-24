"""模组内容进程内缓存的隔离契约与失效行为 (#347 P4)。"""

import json
from copy import deepcopy

import pytest
from collaboration_framework.contracts import ModuleContentV3

from app.service import module_content_cache
from app.service.builtin_module_loader import PAPER_CHASE_SPEC


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    module_content_cache.clear()


@pytest.fixture
def content_json() -> dict:
    return json.loads(PAPER_CHASE_SPEC.source_path.read_text(encoding="utf-8"))


def _load(content_json: dict, *, version: str = PAPER_CHASE_SPEC.version) -> ModuleContentV3:
    content = module_content_cache.load_module_content(
        module_id="paper-chase-zh-coc7",
        version=version,
        content_json=content_json,
    )
    assert isinstance(content, ModuleContentV3)
    return content


def test_repeated_loads_parse_the_content_only_once(content_json: dict) -> None:
    first = _load(content_json)
    second = _load(content_json)

    assert module_content_cache.cache_info().misses == 1
    assert module_content_cache.cache_info().hits == 1
    assert first == second


def test_a_cache_hit_is_isolated_from_the_previous_caller(content_json: dict) -> None:
    """命中缓存不能把上一位调用方的就地修改带给下一位。"""

    first = _load(content_json)
    first.entities[0].state["invented"] = True

    second = _load(content_json)

    assert module_content_cache.cache_info().hits == 1
    assert "invented" not in second.entities[0].state


def test_the_returned_tree_never_aliases_content_json(content_json: dict) -> None:
    """就地修改返回值不能写回 SQLAlchemy 行上的 content_json。

    契约模型本身是 frozen 的，属性赋值会当场报错；真正的走样途径是模型内部
    那些仍然可变的容器（例如实体的 `state` 字典），所以这里改的是它们。
    """

    original = deepcopy(content_json)

    first = _load(content_json)
    first.entities[0].state["invented"] = True
    second = _load(content_json)
    second.entities[1].state["invented"] = True

    assert content_json == original


def test_changed_content_under_the_same_version_is_never_served_stale(
    content_json: dict,
) -> None:
    """作者改了内容却没改版本号时，必须重新解析而不是返回旧内容。

    `version` 是作者手填的自由字符串，没有唯一性保证；键里带内容指纹就是
    为了让这种情况变成一次未命中，而不是一次静默的过期命中。
    """

    first = _load(content_json)
    assert first.presentation.title == "追书人"

    edited = deepcopy(content_json)
    edited["presentation"]["title"] = "改过标题但没改版本号"

    second = _load(edited)

    assert second.presentation.title == "改过标题但没改版本号"
    assert module_content_cache.cache_info().misses == 2
    assert module_content_cache.cache_info().hits == 0


def test_key_order_changes_miss_rather_than_serve_the_wrong_content(
    content_json: dict,
) -> None:
    """指纹不排序：键序不同只会白白重新解析一次，不会命中到错误内容。"""

    first = _load(content_json)
    reordered = dict(reversed(list(content_json.items())))

    second = _load(reordered)

    assert first == second


def test_entry_count_stays_bounded(content_json: dict) -> None:
    for index in range(module_content_cache.MAX_ENTRIES + 3):
        _load(content_json, version=f"3.0.{index}")

    assert module_content_cache.cache_info().size == module_content_cache.MAX_ENTRIES


def test_the_oldest_entry_is_the_one_evicted(content_json: dict) -> None:
    _load(content_json, version="oldest")
    for index in range(module_content_cache.MAX_ENTRIES):
        _load(content_json, version=f"filler-{index}")

    hits_before = module_content_cache.cache_info().hits
    _load(content_json, version="oldest")

    assert module_content_cache.cache_info().hits == hits_before
