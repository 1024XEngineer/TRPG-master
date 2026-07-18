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
    small = compute_derived_stats({**ATTRS, "STR": 30, "DEX": 30, "SIZ": 60})
    assert small["MOV"] == 9
    large = compute_derived_stats({**ATTRS, "STR": 80, "DEX": 80, "SIZ": 40})
    assert large["MOV"] == 7


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
        "dodge": 75,  # 非职业技能，DEX/2=25 基础值
        "occult": 55,  # 非职业技能
    }
    result = compute_preview(ATTRS, ACCOUNTANT_ID, skills, credit_rating=50)

    assert result.validation == []
    assert result.occupation_skill_points == SkillPointsBudget(budget=200, spent=200, remaining=0)
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=100, remaining=0)
    assert len(result.skill_view) == 76 + 3  # 见 coc7_content 补齐的 3 条

    # complete_character 用的是按名字查职业的版本，结果应该一致
    assert validate_character(ATTRS, ACCOUNTANT_NAME, skills, credit_rating=50) == []


def test_occupation_points_exceeded_alone() -> None:
    skills = {"accounting": 99, "law": 99, "library-use": 99, "persuade": 99}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["OCCUPATION_POINTS_EXCEEDED"]


def test_interest_points_exceeded_alone() -> None:
    skills = {"dodge": 95, "occult": 95}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED"]


def test_skill_above_cap_alone() -> None:
    skills = {"spot-hidden": 105}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_ABOVE_CAP"]


def test_skill_below_base_alone() -> None:
    skills = {"accounting": 0}
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_BELOW_BASE"]


def test_credit_out_of_range_alone() -> None:
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {}, credit_rating=999)
    codes = [issue.code for issue in issues]
    assert codes == ["CREDIT_OUT_OF_RANGE"]


def test_unknown_skill_alone() -> None:
    issues = validate_character(ATTRS, ACCOUNTANT_NAME, {"totally-fake-skill": 50})
    codes = [issue.code for issue in issues]
    assert codes == ["UNKNOWN_SKILL"]


def test_occupation_not_found_by_id_and_by_name() -> None:
    preview = compute_preview(ATTRS, 9999, {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in preview.validation)

    issues = validate_character(ATTRS, "不存在的职业", {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in issues)


def test_no_occupation_selected_all_budget_is_interest_only() -> None:
    result = compute_preview(ATTRS, None, {})
    assert result.occupation_skill_points == SkillPointsBudget(budget=0, spent=0, remaining=0)
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=0, remaining=100)
    assert result.validation == []
