"""服务端权威的 COC7 一键角色卡生成器。

这个模块只生成建卡草稿，不标记角色完成。规则校验仍由
``app.core.coc7_rules`` 负责，避免一键生成和手动建卡出现两套裁决逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from app.core.coc7_rules import (
    GENERATION_ROLL,
    ComputeResult,
    compute_derived_stats,
    compute_preview,
    evaluate_skill_base,
    evaluate_skill_points_formula,
)
from app.dto.game import OccupationSpec, RulesetRead

NON_ALLOCATABLE_SKILLS = frozenset({"cthulhu-mythos"})


class CharacterGenerationError(RuntimeError):
    """规则目录无法生成一张合法角色卡。"""


@dataclass(frozen=True, slots=True)
class GeneratedCharacterDraft:
    name: str
    age: int
    gender: str
    residence: str
    birthplace: str
    attributes: dict[str, int]
    derived_stats: dict[str, int | str]
    skills: dict[str, int]
    occupation_id: int
    occupation: str
    occupation_choice_skill_ids: list[str]
    equipment: list[str]
    background: str
    notes: str
    compute_result: ComputeResult


@dataclass(frozen=True, slots=True)
class _ProfilePreset:
    name: str
    gender: str
    residence: str
    birthplace: str
    background: str


_PROFILE_PRESETS = (
    _ProfilePreset(
        name="林岚",
        gender="女",
        residence="阿卡姆",
        birthplace="波士顿",
        background=(
            "形象描述：短发利落，穿着耐磨的深色外套，习惯把笔记本贴身收好。\n"
            "思想与信念：相信任何异常都值得留下记录。\n"
            "特质：冷静、好奇，面对未知时会先观察再行动。"
        ),
    ),
    _ProfilePreset(
        name="周砚",
        gender="男",
        residence="阿卡姆",
        birthplace="纽约",
        background=(
            "形象描述：身材修长，戴着旧式圆框眼镜，衣着整洁但袖口略有磨损。\n"
            "思想与信念：认为事实比传闻更值得信任。\n"
            "特质：耐心、谨慎，不轻易放过矛盾之处。"
        ),
    ),
    _ProfilePreset(
        name="沈安",
        gender="男",
        residence="阿卡姆",
        birthplace="芝加哥",
        background=(
            "形象描述：体格结实，留着修剪整齐的短发，常穿便于行动的风衣。\n"
            "思想与信念：答应过的事一定要做到。\n"
            "特质：坚韧、直接，在压力下仍能保持专注。"
        ),
    ),
    _ProfilePreset(
        name="顾宁",
        gender="女",
        residence="阿卡姆",
        birthplace="费城",
        background=(
            "形象描述：面容清秀，衣着朴素，随身带着一只装满纸张和工具的小包。\n"
            "思想与信念：知识应当帮助人理解恐惧，而不是制造恐惧。\n"
            "特质：敏锐、克制，擅长从细节中寻找线索。"
        ),
    ),
)


def _roll(rng: Random, count: int, sides: int) -> int:
    return sum(rng.randint(1, sides) for _ in range(count))


def _roll_attributes(rng: Random, ruleset: RulesetRead) -> dict[str, int]:
    """按 COC7 标准公式生成 ruleset 中声明的属性。"""
    formulas = {
        "STR": (3, 6, 0),
        "CON": (3, 6, 0),
        "DEX": (3, 6, 0),
        "APP": (3, 6, 0),
        "POW": (3, 6, 0),
        "SIZ": (2, 6, 6),
        "INT": (2, 6, 6),
        "EDU": (2, 6, 6),
        "LUCK": (3, 6, 0),
    }
    attributes: dict[str, int] = {}
    for spec in ruleset.attributes:
        count, sides, bonus = formulas.get(spec.key, (3, 6, 0))
        attributes[spec.key] = (_roll(rng, count, sides) + bonus) * 5
    return attributes


def _choice_candidates(
    occupation: OccupationSpec,
    skill_ids: set[str],
    fixed_ids: set[str],
    already_selected: set[str],
    candidate_ids: list[str] | None,
) -> list[str]:
    allowed = (set(candidate_ids) if candidate_ids is not None else skill_ids) & skill_ids
    return sorted(
        allowed - fixed_ids - already_selected - NON_ALLOCATABLE_SKILLS - {"credit-rating"}
    )


def _choose_occupation_choices(
    occupation: OccupationSpec,
    skill_ids: set[str],
    rng: Random,
) -> list[str]:
    """为职业自选槽找一组不重复的技能，保留职业槽原顺序。"""
    fixed_ids = set(occupation.skill_ids)
    units: list[tuple[int, list[str]]] = []
    for slot_index, slot in enumerate(occupation.choice_slots):
        for _ in range(max(0, slot.count)):
            candidates = _choice_candidates(
                occupation, skill_ids, fixed_ids, set(), slot.candidate_skill_ids
            )
            units.append((slot_index, candidates))

    units.sort(key=lambda item: len(item[1]))
    assignments: list[str | None] = [None] * len(units)
    selected: set[str] = set()

    def search(index: int) -> bool:
        if index == len(units):
            return True
        slot_index, candidates = units[index]
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        for skill_id in shuffled:
            if skill_id in selected:
                continue
            selected.add(skill_id)
            assignments[index] = skill_id
            if search(index + 1):
                return True
            selected.remove(skill_id)
            assignments[index] = None
        return False

    if not search(0):
        raise CharacterGenerationError(f"职业“{occupation.name}”的自选技能槽无法满足")

    by_slot: dict[int, list[str]] = {}
    for (slot_index, _), skill_id in zip(units, assignments, strict=True):
        assert skill_id is not None
        by_slot.setdefault(slot_index, []).append(skill_id)
    return [
        skill_id
        for index in range(len(occupation.choice_slots))
        for skill_id in by_slot.get(index, [])
    ]


def _allocate_points(
    values: dict[str, int],
    skill_ids: list[str],
    points: int,
    skill_bases: dict[str, int],
    rng: Random,
) -> None:
    """把技能点随机分配到给定技能，永不超过 99。"""
    remaining = max(0, points)
    while remaining:
        available = [skill_id for skill_id in skill_ids if values[skill_id] < 99]
        if not available:
            return
        skill_id = rng.choice(available)
        capacity = 99 - values[skill_id]
        increment = min(capacity, remaining, rng.randint(1, min(20, capacity)))
        values[skill_id] += increment
        remaining -= increment


def _equipment_for(occupation: OccupationSpec) -> list[str]:
    categories = set(occupation.categories)
    if "医疗保健" in categories:
        return ["急救包", "听诊器", "手电筒"]
    if "执法安全" in categories:
        return ["手电筒", "记事本", "皮革公文包"]
    if "户外生存" in categories or "运动娱乐" in categories:
        return ["结实的旅行包", "指南针", "手电筒"]
    if "文化艺术" in categories or "新闻出版" in categories:
        return ["笔记本与铅笔", "便携相机", "旧式公文包"]
    return ["笔记本与铅笔", "手电筒", "旧式公文包"]


def generate_character_draft(
    ruleset: RulesetRead,
    *,
    rng: Random | None = None,
) -> GeneratedCharacterDraft:
    """生成一张可提交的 COC7 草稿；不会写数据库，也不会标记完成。"""
    random_source = rng or Random()
    if not ruleset.occupations or not ruleset.skills or not ruleset.attributes:
        raise CharacterGenerationError("当前规则系统缺少生成角色所需的职业、技能或属性数据")

    profile = random_source.choice(_PROFILE_PRESETS)
    # Character 持久化协议目前保存职业名称而不是职业 ID，完成校验也会按名称
    # 解析。目录里可能存在同名的兼容定义，因此一键生成只从每个名称的首个
    # 规范定义中选择，避免生成阶段与落库后的校验阶段指向不同职业。
    canonical_occupations = []
    seen_occupation_names: set[str] = set()
    for candidate in ruleset.occupations:
        if candidate.name not in seen_occupation_names:
            canonical_occupations.append(candidate)
            seen_occupation_names.add(candidate.name)
    occupation = random_source.choice(canonical_occupations)
    skill_ids = {skill.id for skill in ruleset.skills}
    choices = _choose_occupation_choices(occupation, skill_ids, random_source)
    attributes = _roll_attributes(random_source, ruleset)
    skill_bases = {
        skill.id: evaluate_skill_base(skill.base, attributes) for skill in ruleset.skills
    }
    skills = dict(skill_bases)

    credit_min = occupation.credit_min
    if credit_min > 99:
        raise CharacterGenerationError(f"职业“{occupation.name}”的信用评级下限无效")
    skills["credit-rating"] = credit_min

    occupation_ids = [
        skill_id
        for skill_id in [*occupation.skill_ids, *choices]
        if skill_id in skills and skill_id != "credit-rating"
    ]
    occupation_budget = evaluate_skill_points_formula(occupation.skill_points_formula, attributes)
    _allocate_points(
        skills,
        occupation_ids,
        occupation_budget - credit_min,
        skill_bases,
        random_source,
    )

    interest_ids = [
        skill.id
        for skill in ruleset.skills
        if skill.id not in set(occupation_ids)
        and skill.id not in NON_ALLOCATABLE_SKILLS
        and skill.id != "credit-rating"
    ]
    _allocate_points(
        skills,
        interest_ids,
        attributes.get("INT", 0) * 2,
        skill_bases,
        random_source,
    )

    compute_result = compute_preview(
        ruleset,
        attributes=attributes,
        occupation_id=occupation.id,
        skills=skills,
        generation_method=GENERATION_ROLL,
        occupation_choice_skill_ids=choices,
    )
    if compute_result.validation:
        messages = "；".join(issue.message for issue in compute_result.validation)
        raise CharacterGenerationError(f"生成结果未通过规则校验：{messages}")

    return GeneratedCharacterDraft(
        name=profile.name,
        age=28,
        gender=profile.gender,
        residence=profile.residence,
        birthplace=profile.birthplace,
        attributes=attributes,
        derived_stats=compute_derived_stats(attributes),
        skills=skills,
        occupation_id=occupation.id,
        occupation=occupation.name,
        occupation_choice_skill_ids=choices,
        equipment=_equipment_for(occupation),
        background=profile.background,
        notes="由一键生成创建，可继续编辑。",
        compute_result=compute_result,
    )
