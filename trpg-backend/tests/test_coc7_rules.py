"""COC7 建卡计算/校验模块（issue #84 S2；issue #112 改为参数注入）的单元测试：
公式求值 + 一张合法卡返回空校验报告 + 六类非法各一条能被独立拦下。

用「会计师」职业（id=1，`skill_points_formula="EDU*4"`，信用评级 [30,70]，
职业技能含 accounting/law/library-use/listen/persuade/psychology/
science-mathematics/spot-hidden）当固定夹具，8 项属性全部取 50 让预算数字
好算：职业技能点预算 = EDU*4 = 200，兴趣技能点预算 = INT*2 = 100。

issue #112：这个模块的公开入口现在都要求调用方传入 `RulesetRead`，多数用例
借用内置 COC7 的完整规则数据（`RULESET`）当夹具——这只是「借用一份趁手的规则
数据」，不代表 `coc7_rules` 本身认识或依赖 COC7；下方
`test_compute_preview_works_with_a_minimal_non_coc7_ruleset` 额外用一份跟
COC7 毫无关系的最小 ruleset 证明这一点。
"""

from app.core.coc7_content import build_coc7_ruleset
from app.core.coc7_rules import (
    SkillPointsBudget,
    compute_derived_stats,
    compute_preview,
    evaluate_skill_base,
    evaluate_skill_points_formula,
    validate_character,
)
from app.dto.game import (
    AttributeSpec,
    OccupationSpec,
    RulesetRead,
    SkillChoiceSlot,
    SkillSpec,
)

RULESET = build_coc7_ruleset()

ATTRS = {
    "STR": 50,
    "CON": 50,
    "POW": 50,
    "DEX": 50,
    "APP": 50,
    "SIZ": 50,
    "INT": 50,
    "EDU": 50,
    "LUCK": 50,
}
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
    result = compute_preview(RULESET, ATTRS, ACCOUNTANT_ID, skills)

    assert result.validation == []
    # 职业技能 200（accounting/law/library-use/listen 各分配 50）+ 信用下限 30 = 230
    assert result.occupation_skill_points == SkillPointsBudget(budget=200, spent=230, remaining=-30)
    # 兴趣技能 50（dodge/occult 各分配 25）+ 信用超出下限部分 20 = 70
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=70, remaining=30)
    assert len(result.skill_view) == 76 + 3 + 1  # +3 悬空引用补齐 +1 信用评级

    # complete_character 用的是按名字查职业的版本，结果应该一致
    assert validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills) == []


def test_skill_points_exceeded_alone() -> None:
    skills = {
        "accounting": 99,
        "law": 99,
        "library-use": 99,
        "persuade": 99,
        "credit-rating": 50,  # 避免信用未填触发 CREDIT_OUT_OF_RANGE 掩盖了本测试要验的错误
    }
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_POINTS_EXCEEDED"]


def test_occupation_skills_may_overflow_into_interest_points() -> None:
    """🔴 职业技能上的点数超过职业预算是**合法**的，超出部分由兴趣点承担。

    COC7 里兴趣点可以花在任何技能上（包括职业技能），所以「职业点单独超了」
    不是拒绝理由——闸门是总预算。这条和上一条互为对照：上一条超的是总预算
    必须拒，这一条只超职业池、总预算没超，必须放行。

    少了这条的话，把闸门改成「按职业池单独卡」照样能让上一条通过，却会把
    这种合法的卡判成非法（前端职业技能加点用完职业池后自动溢出到兴趣池，
    走的正是这条路径）。
    """
    # 会计师：职业点 EDU*4 = 280，兴趣点 INT*2 = 100，总预算 380
    skills = {
        "accounting": 99,  # base 5  → 94
        "law": 99,  # base 5  → 94
        "library-use": 99,  # base 20 → 79
        "credit-rating": 30,  # 下限，全额记职业点
    }
    result = compute_preview(RULESET, attributes=ATTRS, occupation_id=ACCOUNTANT_ID, skills=skills)

    # 职业池记账已经超了（267 + 信用下限 30 = 297 > 280），但总花费没超总预算
    assert result.occupation_skill_points.spent > result.occupation_skill_points.budget
    assert (
        result.occupation_skill_points.spent + result.interest_skill_points.spent
        <= result.occupation_skill_points.budget + result.interest_skill_points.budget
    )
    assert result.validation == []


def test_interest_points_exceeded_alone() -> None:
    skills = {"dodge": 95, "occult": 95, "credit-rating": 50}
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED"]


def test_skill_above_cap_alone() -> None:
    skills = {"spot-hidden": 105, "credit-rating": 50}
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_ABOVE_CAP"]


def test_skill_below_base_alone() -> None:
    skills = {"accounting": 0, "credit-rating": 50}
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["SKILL_BELOW_BASE"]


def test_credit_in_range_passes() -> None:
    # 会计师信用区间 [30,70]，50 在区间内，单独看不应该产出任何校验项。
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, {"credit-rating": 50})
    assert issues == []


def test_credit_missing_defaults_to_zero_and_is_rejected() -> None:
    # 不传信用评级时 current = base(0)，等价于交了 0 分，落在会计师区间
    # [30,70] 之外——这就是"必填"的实现方式。
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["CREDIT_OUT_OF_RANGE"]


def test_credit_out_of_range_alone() -> None:
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, {"credit-rating": 99})
    codes = [issue.code for issue in issues]
    assert codes == ["CREDIT_OUT_OF_RANGE"]


def test_credit_not_capped_at_99_and_skips_below_base_check() -> None:
    # 信用评级不走常规的「不能低于基础值/不能超过 99」检查，改用职业信用区间——
    # 这里用一个超过 99 的值验证它不会被误判成 SKILL_ABOVE_CAP。超出下限的
    # 120 点（150-30）全部算进兴趣点，超过兴趣预算 100，所以还会连带触发
    # INTEREST_POINTS_EXCEEDED；同时仍因超出会计师区间 [30,70] 被
    # CREDIT_OUT_OF_RANGE 拦下。
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, {"credit-rating": 150})
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED", "CREDIT_OUT_OF_RANGE"]


def test_credit_at_min_counts_only_against_occupation_points() -> None:
    # COC7 官方裁定：信用评级的下限（credit_min）那部分点数由职业点负担。
    # 会计师信用下限是 30，信用刚好等于下限时，兴趣点完全不受影响。
    result = compute_preview(RULESET, ATTRS, ACCOUNTANT_ID, {"credit-rating": 30})
    assert result.occupation_skill_points.spent == 30
    assert result.interest_skill_points.spent == 0
    assert result.validation == []


def test_credit_above_min_excess_counts_against_interest_points() -> None:
    # 超出下限的部分（credit_value - credit_min）由兴趣点负担：会计师信用
    # 下限 30，信用调到 50 时，多出的 20 点应该落进 interest_spent，而不是
    # 继续算进 occupation_spent。
    result = compute_preview(RULESET, ATTRS, ACCOUNTANT_ID, {"credit-rating": 50})
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
    issues = validate_character(RULESET, ATTRS, ACCOUNTANT_NAME, skills)
    codes = [issue.code for issue in issues]
    assert codes == ["INTEREST_POINTS_EXCEEDED"]


def test_unknown_skill_alone() -> None:
    issues = validate_character(
        RULESET, ATTRS, ACCOUNTANT_NAME, {"totally-fake-skill": 50, "credit-rating": 50}
    )
    codes = [issue.code for issue in issues]
    assert codes == ["UNKNOWN_SKILL"]


def test_invalid_attributes_missing_key_rejected() -> None:
    attrs = {k: v for k, v in ATTRS.items() if k != "EDU"}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_missing_luck_rejected() -> None:
    """幸运是必填属性——建卡时必须掷出来，不能整项缺失。"""
    attrs = {k: v for k, v in ATTRS.items() if k != "LUCK"}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_luck_does_not_affect_skill_point_budgets() -> None:
    """幸运不参与任何职业技能点/兴趣技能点公式——改幸运值，两条预算都不动。
    （COC7 里幸运是独立掷出的属性，只在游戏中被消耗，不换算成技能点。）"""
    baseline = compute_preview(RULESET, ATTRS, ACCOUNTANT_ID, {})
    lucky = compute_preview(RULESET, {**ATTRS, "LUCK": 99}, ACCOUNTANT_ID, {})

    assert lucky.occupation_skill_points.budget == baseline.occupation_skill_points.budget
    assert lucky.interest_skill_points.budget == baseline.interest_skill_points.budget


def test_invalid_attributes_extra_key_rejected() -> None:
    attrs = {**ATTRS, "LUK": 50}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_out_of_range_rejected() -> None:
    attrs = {**ATTRS, "INT": 999}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_invalid_attributes_short_circuits_and_skips_other_checks() -> None:
    # 属性不合法时应该直接返回，不会借着这份脏数据继续算出一堆其他校验项
    # （比如信用评级缺失本来也会报错，但不应该跟 INVALID_ATTRIBUTES 一起出现）。
    attrs = {**ATTRS, "STR": 0}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {})
    codes = [issue.code for issue in issues]
    assert codes == ["INVALID_ATTRIBUTES"]


def test_occupation_not_found_by_id_and_by_name() -> None:
    preview = compute_preview(RULESET, ATTRS, 9999, {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in preview.validation)

    issues = validate_character(RULESET, ATTRS, "不存在的职业", {})
    assert any(issue.code == "OCCUPATION_NOT_FOUND" for issue in issues)


def test_occupation_skill_points_budget_uses_max_of_str_dex() -> None:
    # 事务所侦探（id=30）公式是 EDU*2+MAX(STR,DEX)*2，STR40/DEX60 应按较高的
    # DEX 算：EDU*2 + DEX*2 = 50*2 + 60*2 = 220，而不是误用 STR 算出的 180。
    attrs = {**ATTRS, "STR": 40, "DEX": 60}
    result = compute_preview(RULESET, attrs, 30, {})
    assert result.occupation_skill_points.budget == 220


def test_no_occupation_selected_all_budget_is_interest_only() -> None:
    result = compute_preview(RULESET, ATTRS, None, {})
    assert result.occupation_skill_points == SkillPointsBudget(budget=0, spent=0, remaining=0)
    assert result.interest_skill_points == SkillPointsBudget(budget=100, spent=0, remaining=100)
    assert result.validation == []


# ── 属性点预算：必须区分生成方法（issue #96 决策 1）────────────────────


def test_point_buy_over_budget_is_rejected() -> None:
    """点数购买法：8 项可购买属性的总和超过预算就拒。"""
    attrs = {**ATTRS, "STR": 90, "CON": 90, "POW": 90, "DEX": 90, "APP": 90}
    # 90*5 + 50*3 = 600 > 480
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {}, generation_method="pointbuy")
    assert "ATTRIBUTE_POINTS_EXCEEDED" in [issue.code for issue in issues]


def test_rolled_attributes_over_point_buy_budget_are_allowed() -> None:
    """🔴 掷骰法不受点数购买预算约束。

    这条和上一条是一对：掷骰法 8 项总和均值约 457、理论范围 195–720，本来就
    经常超过 480。如果不区分生成方法、无条件拿预算去卡，合法掷出来的角色卡
    会被判成非法，等于废掉 roll-attributes 端点。
    """
    attrs = {**ATTRS, "STR": 90, "CON": 90, "POW": 90, "DEX": 90, "APP": 90}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {}, generation_method="roll")
    assert "ATTRIBUTE_POINTS_EXCEEDED" not in [issue.code for issue in issues]


def test_luck_is_excluded_from_the_attribute_point_budget() -> None:
    """幸运不占属性点预算：把它拉满也不该让总预算超支。"""
    attrs = {**ATTRS, "LUCK": 99}
    issues = validate_character(RULESET, attrs, ACCOUNTANT_NAME, {}, generation_method="pointbuy")
    assert "ATTRIBUTE_POINTS_EXCEEDED" not in [issue.code for issue in issues]


def test_point_buy_attribute_below_min_is_rejected() -> None:
    """点数购买法下单项属性有 [10, 90] 区间，低于下限要拒——这个边界此前
    只有前端在管，后端放行到 1。"""
    issues = validate_character(RULESET, {**ATTRS, "STR": 5}, ACCOUNTANT_NAME, {}, "pointbuy")
    assert "INVALID_ATTRIBUTES" in [issue.code for issue in issues]


def test_rolled_attribute_below_point_buy_min_is_allowed() -> None:
    """掷骰法不套 [10, 90]：3d6*5 最低能掷出 15，但兜底区间放到 [1, 99]，
    不该拿点数购买法的下限去卡骰子结果。"""
    issues = validate_character(RULESET, {**ATTRS, "STR": 5}, ACCOUNTANT_NAME, {}, "roll")
    assert "INVALID_ATTRIBUTES" not in [issue.code for issue in issues]


def test_age_outside_coc7_range_is_rejected() -> None:
    """COC7 的年龄档从 15-19 起、到 80-89 止，区间外要拒。

    前端此前把输入框写死成 [10, 100]，两头都不符合规则；现在区间由后端
    ruleset 声明并裁决。
    """
    from app.core.coc7_rules import validate_age

    assert [i.code for i in validate_age(RULESET, 10)] == ["INVALID_AGE"]
    assert [i.code for i in validate_age(RULESET, 90)] == ["INVALID_AGE"]
    assert validate_age(RULESET, 15) == []
    assert validate_age(RULESET, 89) == []


def test_age_not_filled_is_not_rejected() -> None:
    """年龄是本期才入库的字段，迁移前的卡都没有——不能拿新规则追溯判它们非法。"""
    from app.core.coc7_rules import validate_age

    assert validate_age(RULESET, None) == []


# ── issue #112：coc7_rules 改为参数注入，不再写死认识 COC7 ──────────────────


def test_compute_preview_works_with_a_minimal_non_coc7_ruleset() -> None:
    """规则核心必须只靠传入的 `RulesetRead` 就能算出结果，不依赖 `coc7_content`
    里的任何 COC7 具体数据——用一份跟 COC7 毫无关系的最小规则（2 项属性、
    2 条技能、1 个职业）跑通 `compute_preview`，证明这一点。"""
    minimal_ruleset = RulesetRead(
        attributes=[
            AttributeSpec(key="MIGHT", label="力量", generation="3d6*5"),
            AttributeSpec(key="WITS", label="智力", generation="3d6*5"),
        ],
        attribute_point_buy=None,
        age_range=None,
        skills=[
            SkillSpec(id="brawl", name="搏斗", base=20, category="combat"),
            SkillSpec(id="lore", name="见闻", base="WITS/2", category="knowledge"),
        ],
        occupations=[
            OccupationSpec(
                id=1,
                name="流浪者",
                credit_min=0,
                credit_max=0,
                skill_points_formula="WITS*2",
                skill_ids=["brawl"],
                description="",
            )
        ],
    )

    result = compute_preview(
        minimal_ruleset,
        {"MIGHT": 40, "WITS": 60},
        1,
        {"brawl": 50},
    )

    assert result.validation == []
    # 职业技能点预算 = WITS*2 = 120，brawl 基础值 20、分配到 50 → 花费 30
    assert result.occupation_skill_points == SkillPointsBudget(budget=120, spent=30, remaining=90)
    # `_compute` 的兴趣点预算固定读 attributes 的 "INT" 键（COC7 遗留细节，
    # issue #112 不改变行为），minimal_ruleset 里没有这个属性，兜底为 0；
    # lore 没被分配点数（沿用基础值），兴趣花费也是 0。
    assert result.interest_skill_points == SkillPointsBudget(budget=0, spent=0, remaining=0)


def test_none_attribute_point_buy_and_age_range_skip_their_validations() -> None:
    """`ruleset.attribute_point_buy`/`ruleset.age_range` 为 `None`（自定义系统
    还没配置这两项约束）时，对应校验应该被跳过而不是崩溃或者拿 COC7 的默认值
    顶上——没有约束数据就没法裁决。"""
    ruleset_without_budget = RulesetRead(
        attributes=RULESET.attributes,
        attribute_point_buy=None,
        age_range=None,
        skills=RULESET.skills,
        occupations=RULESET.occupations,
    )

    # 点数购买法下，8 项可购买属性顶到 90（总和远超 COC7 的 480 预算），
    # 但没有 attribute_point_buy 数据可比，不应该报 ATTRIBUTE_POINTS_EXCEEDED。
    attrs = {**ATTRS, "STR": 90, "CON": 90, "POW": 90, "DEX": 90, "APP": 90}
    issues = validate_character(
        ruleset_without_budget, attrs, ACCOUNTANT_NAME, {}, generation_method="pointbuy"
    )
    assert "ATTRIBUTE_POINTS_EXCEEDED" not in [issue.code for issue in issues]

    # 年龄给一个 COC7 规则会拒绝的越界值（150），没有 age_range 数据可比，
    # 不应该报 INVALID_AGE。
    from app.core.coc7_rules import validate_age

    assert validate_age(ruleset_without_budget, 150) == []


def test_coc7_rules_module_does_not_import_coc7_content() -> None:
    """钉死 issue #112 的目标状态：规则核心不再直接依赖具体系统的规则数据
    模块，全部由调用方通过 `RulesetRead` 注入。

    查的是 **import 关系**（走 AST），不是源码里有没有出现这个词——注释和
    文档字符串本来就该能自由地提到 `coc7_content` 解释这段历史，用子串匹配
    会逼着文档绕开它把话说含糊。
    """
    import ast
    import pathlib

    import app.core.coc7_rules as coc7_rules_module

    tree = ast.parse(pathlib.Path(coc7_rules_module.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    assert not [name for name in imported if "coc7_content" in name]


# ── 职业技能自选槽（issue #114）────────────────────────────────────────


def _detective_with_slots() -> tuple[RulesetRead, OccupationSpec]:
    """借内置 COC7 规则数据，给私家侦探临时装上两个自选槽当夹具。

    槽的声明顺序**故意是「自由槽在前、社交槽在后」**——这是能逼出重排的顺序，
    见下面那条对拍用例的说明。

    ⚠️ 必须 `model_copy(deep=True)`：`build_coc7_ruleset()` 每次返回的是**同一批**
    `OccupationSpec` 对象（它直接引用 `coc7_content` 的模块常量，不做拷贝），
    直接改 `choice_slots` 会改到全局，把同一进程里其他用例一起带坏——第一版
    就是这么写的，一口气挂了 11 个不相干的测试。
    """
    ruleset = build_coc7_ruleset().model_copy(deep=True)
    occupation = next(o for o in ruleset.occupations if o.name == "私家侦探")
    occupation.choice_slots = [
        SkillChoiceSlot(count=2, candidate_skill_ids=None, label="任意两项特长"),
        SkillChoiceSlot(
            count=1,
            candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
            label="一项社交技能",
        ),
    ]
    return ruleset, occupation


SLOT_ATTRS = {
    "STR": 50, "CON": 60, "POW": 55, "DEX": 45, "APP": 50,
    "SIZ": 60, "INT": 70, "EDU": 80, "LUCK": 50,
}  # fmt: skip


def test_choice_slot_skills_count_as_occupation_points() -> None:
    """占住自选槽的技能吃职业技能点，不是兴趣点。

    攀爬不在私家侦探的固定本职技能里，但「任意两项特长」这个槽收得下它。
    兴趣预算只有 INT*2=140，而这里非固定技能合计 150 点——如果槽没生效、
    全按兴趣点计费，就会触发 INTEREST_POINTS_EXCEEDED。
    """
    ruleset, _ = _detective_with_slots()

    issues = validate_character(
        ruleset,
        SLOT_ATTRS,
        "私家侦探",
        {"credit-rating": 25, "climb": 95, "swim": 95},
    )

    assert issues == []


def test_choice_slot_assignment_is_optimal_not_first_come_first_served() -> None:
    """🔴 占槽必须取「让职业技能覆盖最大」的分配，不能先来后到。

    合法性的判据是**存在**一种可行占槽方式，不是我们碰巧挑中的那种。这里
    persuade 社交槽和自由槽都收得下，climb/swim/ride 只有自由槽收得下，
    而自由槽只有 2 个：

    - 先来后到（按点数降序塞第一个能塞的槽）：persuade(80) 占掉自由槽①，
      ride(90) 占自由槽②，climb/swim 无处可去 → 未占槽 150 点 > 兴趣预算 140
      → 一张合法卡被 INTEREST_POINTS_EXCEEDED 判死。
    - 最优：persuade 让给社交槽，自由槽留给 ride(90)+climb(75) → 未占槽只剩
      swim 75 点 ≤ 140 → 合法。

    槽的声明顺序是「自由槽在前」，正是为了让先来后到的实现在这里出错——顺序
    反过来的话，persuade 先撞上社交槽，蒙对了，这条用例就失去区分力。
    """
    ruleset, _ = _detective_with_slots()

    issues = validate_character(
        ruleset,
        SLOT_ATTRS,
        "私家侦探",
        {"credit-rating": 25, "persuade": 90, "climb": 95, "swim": 95, "ride": 95},
    )

    assert issues == []


def test_skill_outside_every_slot_still_costs_interest_points() -> None:
    """槽是有限的：塞不进任何槽的技能照样吃兴趣点，超了要拦。

    跟上一条互为对照——上一条证明"该算职业点的别算成兴趣点"，这条证明
    "槽不是无限的免费通行证"。这里 4 项非固定技能合计 320 点，槽最多吸收 3 项，
    剩下的必然超 140。
    """
    ruleset, _ = _detective_with_slots()

    issues = validate_character(
        ruleset,
        SLOT_ATTRS,
        "私家侦探",
        {"credit-rating": 25, "climb": 95, "swim": 95, "ride": 95, "jump": 95},
    )

    assert [i.code for i in issues] == ["INTEREST_POINTS_EXCEEDED"]


def test_cthulhu_mythos_cannot_be_allocated_at_creation() -> None:
    """克苏鲁神话建卡时不可加点（issue #114）。

    规则依据（`COC7空白卡CY23Final.xlsx` 两处）：
    - `附表`：「没有调查员能在初始技能设定时给克苏鲁神话加点（除非被 KP 同意）」
    - `更新说明`：「兴趣技能点可以添加到任意技能(不包含克苏鲁神话)上」——即本
      项目已用作信用评级分账依据的那封 Chaosium 主编邮件

    修复前：给克苏鲁神话加 60 点，校验返回 0 条问题、直接放行。
    """
    ruleset = build_coc7_ruleset()

    issues = validate_character(
        ruleset, SLOT_ATTRS, "私家侦探", {"credit-rating": 25, "cthulhu-mythos": 60}
    )

    assert [i.code for i in issues] == ["SKILL_NOT_ALLOCATABLE"]


def test_cthulhu_mythos_at_base_value_is_fine() -> None:
    """基础值 0 本身合法——禁的是"加点"，不是"这项技能存在"。"""
    ruleset = build_coc7_ruleset()

    issues = validate_character(
        ruleset, SLOT_ATTRS, "私家侦探", {"credit-rating": 25, "cthulhu-mythos": 0}
    )

    assert issues == []
