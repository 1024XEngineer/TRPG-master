"""Versioned semantic-planning corpus for Issue #357."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerCorpusCase:
    name: str
    cohort: str
    utterance: str
    expected_kinds: tuple[str, ...]


CASES = (
    PlannerCorpusCase("observe_room", "one_complex", "观察当前房间", ("action",)),
    PlannerCorpusCase("inspect_desk", "one_complex", "仔细检查书桌", ("action",)),
    PlannerCorpusCase("open_door", "one_complex", "打开眼前的门", ("action",)),
    PlannerCorpusCase("take_book", "one_complex", "拿起桌上的书", ("action",)),
    PlannerCorpusCase("use_key", "one_complex", "用钥匙开锁", ("action",)),
    PlannerCorpusCase("travel_cemetery", "deterministic", "去墓地", ("travel",)),
    PlannerCorpusCase("enter_library", "deterministic", "进入图书馆", ("travel",)),
    PlannerCorpusCase("wait", "deterministic", "等待一会儿", ("wait",)),
    PlannerCorpusCase("rest", "deterministic", "休息到晚上", ("rest",)),
    PlannerCorpusCase("rule_observe", "deterministic", "用侦查观察守墓人", ("action",)),
    PlannerCorpusCase("talk", "dialogue_runtime", "询问托马斯关于藏书的事", ("dialogue",)),
    PlannerCorpusCase("greet", "dialogue_runtime", "和眼前的人打招呼", ("dialogue",)),
    PlannerCorpusCase("runtime_inn", "dialogue_runtime", "去镇上的旅馆", ("travel",)),
    PlannerCorpusCase("runtime_clinic", "dialogue_runtime", "进入诊所", ("travel",)),
    PlannerCorpusCase("runtime_item", "dialogue_runtime", "拿一盏普通油灯", ("action",)),
    PlannerCorpusCase(
        "observe_then_ask", "multi", "先观察房间，然后询问托马斯", ("action", "dialogue")
    ),
    PlannerCorpusCase("travel_then_search", "multi", "去图书馆搜索旧报纸", ("travel", "action")),
    PlannerCorpusCase("enter_then_talk", "multi", "进入办公室和托马斯交谈", ("travel", "dialogue")),
    PlannerCorpusCase("take_then_use", "multi", "拿起钥匙，再用它打开门", ("action", "action")),
    PlannerCorpusCase(
        "three_steps", "multi", "先观察，再询问，然后等待", ("action", "dialogue", "wait")
    ),
    PlannerCorpusCase(
        "four_steps",
        "multi",
        "观察；询问；去墓地；在那里搜索",
        ("action", "dialogue", "travel", "action"),
    ),
    PlannerCorpusCase(
        "punctuation",
        "multi",
        "查看书桌，拿起笔记本，询问托马斯",
        ("action", "action", "dialogue"),
    ),
    PlannerCorpusCase("implicit_destination", "multi", "前往墓地调查石板", ("travel", "action")),
    PlannerCorpusCase("travel_rest", "multi", "去旅馆休息", ("travel", "rest")),
    PlannerCorpusCase("companion_present", "prerequisite", "带托马斯去墓地", ("travel",)),
    PlannerCorpusCase("companion_pronoun", "prerequisite", "带他一起去图书馆", ("travel",)),
    PlannerCorpusCase(
        "companion_then_act",
        "prerequisite",
        "带托马斯去墓地调查石板",
        ("travel", "action"),
    ),
    PlannerCorpusCase(
        "meet_then_travel",
        "prerequisite",
        "先去会客室找托马斯，再带他去墓地",
        ("travel", "travel"),
    ),
    PlannerCorpusCase("pending_skill", "pending", "尝试撬开锁", ("action",)),
    PlannerCorpusCase("pending_push", "pending", "强行推开沉重石板", ("action",)),
    PlannerCorpusCase("pending_luck", "pending", "仔细寻找隐藏的入口", ("action",)),
    PlannerCorpusCase("narrator_retry", "narrator", "查看已经发现的线索", ("action",)),
    PlannerCorpusCase("english_one", "multilingual", "Inspect the old desk.", ("action",)),
    PlannerCorpusCase(
        "english_multi",
        "multilingual",
        "Go to the library, then search the archives.",
        ("travel", "action"),
    ),
    PlannerCorpusCase(
        "mixed", "multilingual", "去 library，然后 inspect the desk", ("travel", "action")
    ),
    PlannerCorpusCase(
        "fullwidth", "multilingual", "观察房间；然后 ask Thomas", ("action", "dialogue")
    ),
    PlannerCorpusCase("intent_modifier", "ambiguous", "我想小心地观察房间", ("action",)),
    PlannerCorpusCase("quoted_then", "ambiguous", "对他说‘然后呢？’", ("dialogue",)),
    PlannerCorpusCase("narrative_pose", "ambiguous", "我屏住呼吸，谨慎地查看门锁", ("action",)),
    PlannerCorpusCase("unclear_target", "ambiguous", "继续调查它", ("action",)),
)
