"""COC7 权威数据本身的完整性铁律（issue #84 S2 任务 0 + issue #114 扩到 229）：
职业引用的技能 id 必须都能在技能表里查到，不允许悬空引用；公式必须可求值；
信用区间必须合法。S1 移植时踩过一次悬空引用的坑（navigate/carpentry/illusion
三个技能当时没补全），#114 把职业从 30 扩到 229、又新增了自选槽（候选技能也
可能悬空），出错面更大——这些是「防止导入损坏」的守卫，一条坏数据混进 229 条
里靠抽查是抽不出来的（PR #85 记者/间谍公式被误设 EDU*4 就是靠人肉对照才发现）。
"""

from app.core.coc7_content import COC7_OCCUPATIONS, COC7_SKILLS
from app.core.coc7_rules import evaluate_skill_points_formula

_VALID_SKILL_IDS = {skill.id for skill in COC7_SKILLS}
# 求值只需要一份属性字典，取值无所谓——这里只验「公式能不能算出来」，不验数值。
_DUMMY_ATTRS = dict.fromkeys(("STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"), 50)


def test_all_occupation_fixed_skill_ids_exist_in_skill_table() -> None:
    dangling: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        for skill_id in occupation.skill_ids:
            if skill_id not in _VALID_SKILL_IDS:
                dangling.append(f"{occupation.name}({occupation.id}) -> {skill_id}")

    assert dangling == [], f"固定技能存在悬空引用: {dangling}"


def test_all_choice_slot_candidate_skill_ids_exist_in_skill_table() -> None:
    """自选槽里限定候选集的技能 id 同样不能悬空（issue #114 新增的出错面）。

    `candidate_skill_ids is None` 表示「任意技能」的开放槽，不做引用检查；
    给出列表时列表里的每个 id 都必须在技能表里。
    """
    dangling: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        for slot in occupation.choice_slots:
            for skill_id in slot.candidate_skill_ids or []:
                if skill_id not in _VALID_SKILL_IDS:
                    dangling.append(
                        f"{occupation.name}({occupation.id}) 槽[{slot.label}] -> {skill_id}"
                    )

    assert dangling == [], f"自选槽候选技能存在悬空引用: {dangling}"


def test_all_occupation_formulas_are_evaluable() -> None:
    """229 项职业的技能点公式全部可求值（验收标准 #4）。

    公式解析器格式不认识时会 raise，不悄悄兜底成 0——所以一条公式写坏了，
    这里就会红，而不是让某个职业静默变成 0 点预算。
    """
    unparseable: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        try:
            evaluate_skill_points_formula(occupation.skill_points_formula, _DUMMY_ATTRS)
        except ValueError as exc:
            unparseable.append(
                f"{occupation.name}({occupation.id}) {occupation.skill_points_formula!r}: {exc}"
            )

    assert unparseable == [], f"存在不可求值的技能点公式: {unparseable}"


def test_all_occupation_credit_ranges_are_valid() -> None:
    """信用评级区间必须 0 ≤ min ≤ max ≤ 99（验收标准 #4）。"""
    invalid: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        if not (0 <= occupation.credit_min <= occupation.credit_max <= 99):
            invalid.append(
                f"{occupation.name}({occupation.id}) "
                f"[{occupation.credit_min}, {occupation.credit_max}]"
            )

    assert invalid == [], f"存在非法的信用评级区间: {invalid}"


def test_all_choice_slots_are_structurally_sound() -> None:
    """自选槽结构本身合法：至少选 1 项；限定候选集时候选数不能少于要选的数量
    （否则这个槽永远填不满，是导入错误）。"""
    broken: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        for slot in occupation.choice_slots:
            if slot.count < 1:
                broken.append(
                    f"{occupation.name}({occupation.id}) 槽[{slot.label}] count={slot.count}"
                )
            candidates = slot.candidate_skill_ids
            if candidates is not None and len(candidates) < slot.count:
                broken.append(
                    f"{occupation.name}({occupation.id}) 槽[{slot.label}] "
                    f"候选 {len(candidates)} < 需选 {slot.count}"
                )

    assert broken == [], f"存在结构不合法的自选槽: {broken}"


def test_occupation_ids_are_unique_and_contiguous() -> None:
    """229 项职业的 id 唯一，且是 1..229 连续编号（导入时按序号对齐，缺号/重号
    都说明提取或合并出了错）。"""
    ids = sorted(o.id for o in COC7_OCCUPATIONS)
    assert len(ids) == len(set(ids)), "职业 id 有重复"
    assert ids == list(range(1, len(COC7_OCCUPATIONS) + 1)), "职业 id 不是 1..N 连续编号"
