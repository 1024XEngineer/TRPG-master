"""COC7 建卡计算/校验模块（issue #84 S2）的单元测试：公式求值 + 一张合法卡
返回空校验报告 + 六类非法各一条能被独立拦下。

用「会计师」职业（id=1，`skill_points_formula="EDU*4"`，信用评级 [30,70]，
职业技能含 accounting/law/library-use/listen/persuade/psychology/
science-mathematics/spot-hidden）当固定夹具，8 项属性全部取 50 让预算数字
好算：职业技能点预算 = EDU*4 = 200，兴趣技能点预算 = INT*2 = 100。
"""

from app.core.coc7_rules import (
    SkillPointsBudget,
    compute_derived_stats,
    compute_preview,
    evaluate_skill_base,
    evaluate_skill_points_formula,
    validate_character,
)

ATTRS = {"STR": 50, "CON": 50, "POW": 50, "DEX": 50, "APP": 50, "SIZ": 50, "INT": 50, "EDU": 50}
ACCOUNTANT_ID = 1
ACCOUNTANT_NAME = "会计师"


def test_derived_stats_formulas() -> None:
    stats = compute_derived_stats(ATTRS)
    assert stats == {"HP": 10, "MP": 10, "SAN": 50, "DB": "0", "Build": "0", "MOV": 8}


def test_derived_stats_move_small_and_large() -> None:
    # COC7 规则：STR/DEX 都小于 SIZ（体格相对弱小）MOV=7；都大于 SIZ（体格
    # 相对高大灵活）MOV=9（PR #85 review #2：之前这两个分支的返回值是反的）。
    small = compute_derived_stats({**ATTRS, "STR": 30, "DEX": 30, "SIZ": 60})
    assert small["MOV"] == 7
    large = compute_derived_stats({**ATTRS, "STR": 80, "DEX": 80, "SIZ": 40})
    assert large["MOV"] == 9


def test_damage_bonus_build_table() -> None:
    assert compute_derived_stats({**ATTRS, "STR": 10, "SIZ": 10})["DB"] == "-2"
    assert compute_derived_stats({**ATTRS, "STR": 90, "SIZ": 90})["DB"] == "+1D6"
    assert compute_derived_stats({**ATTRS, "STR": 150, "SIZ": 150})["DB"] == "+1D8"


def test_evaluate_skill_base_handles_fixed_formula_and_divisor() -> None:
    assert evaluate_skill_base(25, ATTRS) == 25
    assert evaluate_skill_base("EDU", ATTRS) == 50
    assert evaluate_skill_base("DEX/2", ATTRS) == 25


def test_evaluate_skill_points_formula_single_and_multi_term() -> None:
    assert evaluate_skill_points_formula("EDU*4", ATTRS) == 200
    assert evaluate_skill_points_formula("EDU*2+DEX*2", ATTRS) == 200


def test_evaluate_skill_points_formula_max_term_takes_higher_attribute() -> None:
    attrs = {**ATTRS, "STR": 40, "DEX": 60, "EDU": 50}
    # EDU*2 + max(STR,DEX)*2 = 50*2 + 60*2 = 100 + 120 = 220（验证取较高的 DEX）
    assert evaluate_skill_points_formula("EDU*2+MAX(STR,DEX)*2", attrs) == 220


def test_evaluate_skill_points_formula_max_term_with_three_attributes() -> None:
    attrs = {**ATTRS, "APP": 30, "DEX": 45, "STR": 70}
    # EDU*2 + max(APP,DEX,STR)*2 = 50*2 + 70*2 = 100 + 140 = 240（三选一取 STR）
    assert evaluate_skill_points_formula("EDU*2+MAX(APP,DEX,STR)*2", attrs) == 240


def test_evaluate_skill_points_formula_rejects_unparseable_string() -> None:
    import pytest

    with pytest.raises(ValueError):
        evaluate_skill_points_formula("EDU*4 或 STR*2", ATTRS)


def test_valid_card_has_empty_validation_report() -> None:
    skills = {
        "accounting": 55,
        "law": 55,
        "library-use": 70,
        "listen": 70,
        "dodge": 50,  # 非职业技能，DEX/2=25 基础值，分配 25 点
        "occult": 30,  # 非职业技能，分配 25 点
        # 会计师信用区间 [30,70]：下限 30 点算职业点负担，超出下限的 20 点
        # （50-30）算兴趣点负担（COC7 官方裁定，见下方专项测试）。
        "credit-rating": 50,
    }
    result = compute_preview(ATTRS, ACCOUNTANT_ID, skills)

    assert result.validation == []
    # 职业技能 200（accounting/law/library-use/listen 各分配 50）+ 信用下限 30 = 230
    assert result.occupation_skill_points == SkillPointsBudget(budget=200, spent=230, remaining=-30)
    # 兴趣技能 50（dodge/occult 各分配 25）+ 信用超出下限部分 20 = 70
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=70, remaining=30)
    assert len(result.skill_view) == 76 + 3 + 1  # +3 悬空引用补齐 +1 信用评级

    # complete_character 用的是按名字查职业的版本，结果应该一致
    assert validate_character(ATTRS, ACCOUNTANT_NAME, skills) == []


def test_occupation_points_exceeded_alone() -> None:
    skills = {
        "accounting": 99,
        "law": 99,
        "library-use": 99,
        "persuade": 99,
        "credit-rating": 50,  # 避免信用未填触发 CREDIT_OUT_OF_RANGE 掩盖了本测试要验的错误
    }
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["OCCUPATION_POINTS_EXCEEDED"]


def test_interest_points_exceeded_alone() -> None:
    skills = {"dodge": 95, "occult": 95, "credit-rating": 50}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED"]


def test_skill_above_cap_alone() -> None:
    skills = {"spot-hidden": 105, "credit-rating": 50}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_ABOVE_CAP"]


def test_skill_below_base_alone() -> None:
    skills = {"accounting": 0, "credit-rating": 50}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_BELOW_BASE"]


def test_credit_in_range_passes() -> None:
    # 会计师信用区间 [30,70]，50 在区间内，单独看不应该产出任何校验项。
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {"credit-rating": 50})
    assert issues == []


def test_credit_missing_defaults_to_zero_and_is_rejected() -> None:
    # 不传信用评级时 current = base(0)，等价于交了 0 分，落在会计师区间
    # [30,70] 之外——这就是"必填"的实现方式。
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["CREDIT_OUT_OF_RANGE"]


def test_credit_out_of_range_alone() -> None:
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {"credit-rating": 99})
    codes = [issue.code for issue in issues]
    assert codes == ["CREDIT_OUT_OF_RANGE"]


def test_credit_not_capped_at_99_and_skips_below_base_check() -> None:
    # 信用评级不走常规的「不能低于基础值/不能超过 99」检查，改用职业信用区间——
    # 这里用一个超过 99 的值验证它不会被误判成 SKILL_ABOVE_CAP。超出下限的
    # 120 点（150-30）全部算进兴趣点，超过兴趣预算 100，所以还会连带触发
    # INTEREST_POINTS_EXCEEDED；同时仍因超出会计师区间 [30,70] 被
    # CREDIT_OUT_OF_RANGE 拦下。
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {"credit-rating": 150})
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED", "CREDIT_OUT_OF_RANGE"]


def test_credit_at_min_counts_only_against_occupation_points() -> None:
    # COC7 官方裁定：信用评级的下限（credit_min）那部分点数由职业点负担。
    # 会计师信用下限是 30，信用刚好等于下限时，兴趣点完全不受影响。
    result = compute_preview(ATTRS, ACCOUNTANT_ID, {"credit-rating": 30})
    assert result.occupation_skill_points.spent == 30
    assert result.interest_skill_points.spent == 0
    assert result.validation == []


def test_credit_above_min_excess_counts_against_interest_points() -> None:
    # 超出下限的部分（credit_value - credit_min）由兴趣点负担：会计师信用
    # 下限 30，信用调到 50 时，多出的 20 点应该落进 interest_spent，而不是
    # 继续算进 occupation_spent。
    result = compute_preview(ATTRS, ACCOUNTANT_ID, {"credit-rating": 50})
    assert result.occupation_skill_points.spent == 30
    assert result.interest_skill_points.spent == 20
    assert result.validation == []


def test_credit_excess_counts_against_interest_budget() -> None:
    # 兴趣点数（预算 100）先花在两个非职业技能上正好用满，再额外给信用评级
    # 分配 50 点（超出会计师信用下限 30 的部分是 20 点）——这 20 点现在应该
    # 算进 interest_spent，导致超预算 20 点，触发 INTEREST_POINTS_EXCEEDED。
    skills = {
        "dodge": 99,  # 非职业技能，base 25，分配 74 点
        "occult": 31,  # 非职业技能，base 5，分配 26 点
        "credit-rating": 50,  # 会计师信用区间 [30,70]，下限 30 走职业点
    }
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED"]


def test_unknown_skill_alone() -> None:
    issues = validate_character(
        ATTRS, ACCOUNTANT_NAME, {"totally-fake-skill": 50, "credit-rating": 50}
    )
    codes = [issue.code for issue in issues]
    assert codes == ["UNKNOWN_SKILL"]


def test_invalid_attributes_missing_key_rejected() -> None:
    attrs = {k: v for k, v in ATTRS.items() if k != "EDU"}
    issues = validate_character(attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_extra_key_rejected() -> None:
    attrs = {**ATTRS, "LUK": 50}
    issues = validate_character(attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_out_of_range_rejected() -> None:
    attrs = {**ATTRS, "INT": 999}
    issues = validate_character(attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_short_circuits_and_skips_other_checks() -> None:
    # 属性不合法时应该直接返回，不会借着这份脏数据继续算出一堆其他校验项
    # （比如信用评级缺失本来也会报错，但不应该跟 INVALID_ATTRIBUTES 一起出现）。
    attrs = {**ATTRS, "STR": 0}
    issues = validate_character(attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_occupation_not_found_by_id_and_by_name() -> None:
    preview = compute_preview(ATTRS, 9999, {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in preview.validation)

    issues = validate_character(ATTRS, "不存在的职业", {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in issues)


def test_occupation_skill_points_budget_uses_max_of_str_dex() -> None:
    # 事务所侦探（id=30）公式是 EDU*2+MAX(STR,DEX)*2，STR40/DEX60 应按较高的
    # DEX 算：EDU*2 + DEX*2 = 50*2 + 60*2 = 220，而不是误用 STR 算出的 180。
    attrs = {**ATTRS, "STR": 40, "DEX": 60}
    result = compute_preview(attrs, 30, {})
    assert result.occupation_skill_points.budget == 220


def test_no_occupation_selected_all_budget_is_interest_only() -> None:
    result = compute_preview(ATTRS, None, {})
    assert result.occupation_skill_points == SkillPointsBudget(budget=0, spent=0, remaining=0)
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=0, remaining=100)
    assert result.validation == []
