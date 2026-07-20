"""COC7 建卡计算 / 校验（issue #84 S2）：路线乙的核心——规则计算只在后端
权威实现一份，前端只渲染。给定一份建卡草稿（8 属性 + 职业 + 技能分配），
算出全部派生量并产出结构化校验报告。

公式来源与 `app/service/character.py::roll_attributes`、
`trpg-frontend/src/data/character-model.ts`（S3 之前前端本地那份实现，
S2 阶段只读它核对公式，不依赖它是否存在）保持一致，不自创新公式。

对外两个入口：
- `compute_preview(...)`：给 `POST /systems/{systemId}/character/preview`
  用，返回衍生值 + 两个技能点预算 + 全部技能的 base/cap/当前值 + 校验报告。
- `validate_character(...)`：给 `complete_character` 用，只要校验报告
  （建卡完成前的权威闸门）。

两者内部共用同一套 `_compute`，校验规则只实现一份，不会出现"预览"和
"complete 时校验"两条腿走路、结果不一致的情况。
"""

import re
from dataclasses import dataclass, field

from app.core.coc7_content import COC7_OCCUPATIONS, COC7_SKILLS
from app.dto.game import OccupationSpec

SKILL_CAP = 99

COC7_ATTRIBUTE_KEYS = {"STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"}
ATTRIBUTE_MIN = 1
ATTRIBUTE_MAX = 99


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """一条校验失败信息。`code` 是可枚举的短码，供前端做条件分支；
    `field` 指向出错的字段路径（比如 `skills.spot-hidden`）；`message` 是给
    人看的说明。"""

    code: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class SkillPointsBudget:
    budget: int
    spent: int
    remaining: int


@dataclass(frozen=True, slots=True)
class SkillView:
    id: str
    base: int
    allocated: int
    current: int
    cap: int


@dataclass(frozen=True, slots=True)
class ComputeResult:
    derived_stats: dict[str, int | str]
    occupation_skill_points: SkillPointsBudget
    interest_skill_points: SkillPointsBudget
    skill_view: list[SkillView] = field(default_factory=list)
    validation: list[ValidationIssue] = field(default_factory=list)


def _damage_bonus_and_build(str_: int, siz: int) -> str:
    """伤害加值 DB 和体格 Build 是同一张表查出来的同一个值（COC7 规则）。"""
    total = str_ + siz
    if total <= 64:
        return "-2"
    if total <= 84:
        return "-1"
    if total <= 124:
        return "0"
    if total <= 164:
        return "+1D4"
    if total <= 204:
        return "+1D6"
    return "+1D8"


def compute_derived_stats(attributes: dict[str, int]) -> dict[str, int | str]:
    """HP = floor((SIZ+CON)/10)；MP = floor(POW/5)；SAN = POW；
    DB/Build 查表；MOV 按 STR/DEX 相对 SIZ 的大小判定。"""
    str_ = attributes.get("STR", 0)
    con = attributes.get("CON", 0)
    pow_ = attributes.get("POW", 0)
    dex = attributes.get("DEX", 0)
    siz = attributes.get("SIZ", 0)

    db_build = _damage_bonus_and_build(str_, siz)

    if str_ < siz and dex < siz:
        move = 7
    elif str_ > siz and dex > siz:
        move = 9
    else:
        move = 8

    return {
        "HP": (siz + con) // 10,
        "MP": pow_ // 5,
        "SAN": pow_,
        "DB": db_build,
        "Build": db_build,
        "MOV": move,
    }


def evaluate_skill_base(base: int | str, attributes: dict[str, int]) -> int:
    """技能基础值：`int` 原样返回；公式串按 `ATTR` 或 `ATTR/N` 求值
    （跟前端 `calculateBaseValue` 一致，比如 `DEX/2`、`EDU`）。"""
    if isinstance(base, int):
        return base
    if "/" in base:
        attr, divisor = base.split("/")
        return attributes.get(attr, 0) // int(divisor)
    return attributes.get(base, 0)


_SKILL_POINTS_TERM_RE = re.compile(r"^([A-Z]+)\*(\d+)$")
_SKILL_POINTS_MAX_TERM_RE = re.compile(r"^MAX\(([A-Z]+(?:,[A-Z]+)+)\)\*(\d+)$")


def evaluate_skill_points_formula(formula: str, attributes: dict[str, int]) -> int:
    """职业技能点预算公式求值，形如 `EDU*4`、`EDU*2+DEX*2`（属性*系数，
    可以有多项相加），以及 `MAX(ATTR1,ATTR2[,ATTR3])*N`（取列出属性里的
    最高值再乘系数，用于 COC7 规则书里"二选一/三选一"的职业公式，比如
    `EDU*2+MAX(STR,DEX)*2`）。格式不认识就报错，不悄悄兜底成 0——公式本身
    是权威数据的一部分，解析不了应该在开发期就暴露，而不是让预算悄悄变成
    0。"""
    total = 0
    for term in formula.split("+"):
        term = term.strip()
        max_match = _SKILL_POINTS_MAX_TERM_RE.match(term)
        if max_match is not None:
            attrs, coefficient = max_match.group(1), max_match.group(2)
            values = [attributes.get(attr, 0) for attr in attrs.split(",")]
            total += max(values) * int(coefficient)
            continue
        match = _SKILL_POINTS_TERM_RE.match(term)
        if match is None:
            raise ValueError(f"无法解析的技能点公式: {formula!r}")
        attr, coefficient = match.group(1), match.group(2)
        total += attributes.get(attr, 0) * int(coefficient)
    return total


def find_occupation_by_id(occupation_id: int | None) -> tuple[OccupationSpec | None, bool]:
    """按 id 查职业。返回 `(职业或 None, 传了 id 但没查到)`。"""
    if occupation_id is None:
        return None, False
    match = next((o for o in COC7_OCCUPATIONS if o.id == occupation_id), None)
    return match, match is None


def find_occupation_by_name(name: str | None) -> tuple[OccupationSpec | None, bool]:
    """按名字查职业——`complete_character` 时角色卡存的是职业名字符串
    （不是 id），只能这样映射回职业定义。"""
    if name is None:
        return None, False
    match = next((o for o in COC7_OCCUPATIONS if o.name == name), None)
    return match, match is None


def _validate_attributes(attributes: dict[str, int]) -> list[ValidationIssue]:
    """属性必须正好是 8 个 COC7 键、每项都是 [1, 99] 内的 int，不然客户端能
    传 `INT=999` 之类的脏数据把后面的技能点预算/衍生值撑爆（PR #85 review #1）。
    结构性问题（缺键/多键）报一条汇总；结构没问题时再逐项查范围。"""
    issues: list[ValidationIssue] = []
    actual_keys = set(attributes.keys())
    missing = COC7_ATTRIBUTE_KEYS - actual_keys
    extra = actual_keys - COC7_ATTRIBUTE_KEYS
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"缺少 {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"多余 {', '.join(sorted(extra))}")
        issues.append(
            ValidationIssue(
                code="INVALID_ATTRIBUTES",
                field="attributes",
                message=f"属性字段不正确：{'；'.join(parts)}",
            )
        )
        return issues

    for key in sorted(COC7_ATTRIBUTE_KEYS):
        value = attributes[key]
        if not isinstance(value, int) or isinstance(value, bool):
            issues.append(
                ValidationIssue(
                    code="INVALID_ATTRIBUTES",
                    field=f"attributes.{key}",
                    message=f"{key} 必须是整数",
                )
            )
        elif not (ATTRIBUTE_MIN <= value <= ATTRIBUTE_MAX):
            issues.append(
                ValidationIssue(
                    code="INVALID_ATTRIBUTES",
                    field=f"attributes.{key}",
                    message=(
                        f"{key} 的值 {value} 不在合法范围 [{ATTRIBUTE_MIN}, {ATTRIBUTE_MAX}] 内"
                    ),
                )
            )
    return issues


def _compute(
    attributes: dict[str, int],
    occupation: OccupationSpec | None,
    skills: dict[str, int],
    *,
    occupation_not_found: bool,
) -> ComputeResult:
    issues: list[ValidationIssue] = []
    if occupation_not_found:
        issues.append(
            ValidationIssue(
                code="OCCUPATION_NOT_FOUND", field="occupation", message="未找到匹配的职业"
            )
        )

    attribute_issues = _validate_attributes(attributes)
    if attribute_issues:
        issues.extend(attribute_issues)
        # 属性本身不合法，后面的衍生值/技能点预算算出来也是垃圾数据，直接
        # 返回空结果 + 校验报告，不再往下算。
        return ComputeResult(
            derived_stats={},
            occupation_skill_points=SkillPointsBudget(budget=0, spent=0, remaining=0),
            interest_skill_points=SkillPointsBudget(budget=0, spent=0, remaining=0),
            skill_view=[],
            validation=issues,
        )

    derived_stats = compute_derived_stats(attributes)

    occupation_budget = (
        evaluate_skill_points_formula(occupation.skill_points_formula, attributes)
        if occupation is not None
        else 0
    )
    interest_budget = attributes.get("INT", 0) * 2
    occupation_skill_ids = set(occupation.skill_ids) if occupation is not None else set()

    skills_by_id = {skill.id: skill for skill in COC7_SKILLS}

    occupation_spent = 0
    interest_spent = 0
    skill_view: list[SkillView] = []

    # 遍历技能表里的全部技能（不只是草稿里提到的那些），这样 `compute_preview`
    # 能一次性把完整的 base/cap 都带给前端渲染，草稿没提到的技能视为
    # 「未分配点数」（current 就是 base）。
    for spec in COC7_SKILLS:
        base = evaluate_skill_base(spec.base, attributes)
        current = skills.get(spec.id, base)
        allocated = current - base
        is_credit = spec.id == "credit-rating"

        # 信用评级是特殊技能：用职业信用区间校验（见下方 CREDIT_OUT_OF_RANGE），
        # 不套常规的「不能低于基础值」「不能超过 99」这两条。
        if not is_credit:
            if current < base:
                issues.append(
                    ValidationIssue(
                        code="SKILL_BELOW_BASE",
                        field=f"skills.{spec.id}",
                        message=f"{spec.name} 的值 {current} 不能低于基础值 {base}",
                    )
                )
            if current > SKILL_CAP:
                issues.append(
                    ValidationIssue(
                        code="SKILL_ABOVE_CAP",
                        field=f"skills.{spec.id}",
                        message=f"{spec.name} 的值 {current} 超过上限 {SKILL_CAP}",
                    )
                )

        effective_allocated = max(allocated, 0)
        if is_credit:
            # 信用评级按 COC7 官方裁定分账：下限（credit_min）那部分点数视为
            # 职业点负担，超出下限的部分才算兴趣点负担；范围校验见下方
            # CREDIT_OUT_OF_RANGE（这里不重复判断，只管记账）。未选职业时没有
            # 区间可言，全部点数按兴趣点算。
            if occupation is not None:
                occupation_spent += occupation.credit_min
                interest_spent += max(0, current - occupation.credit_min)
            else:
                interest_spent += max(0, current)
        elif spec.id in occupation_skill_ids:
            occupation_spent += effective_allocated
        else:
            interest_spent += effective_allocated

        cap = occupation.credit_max if is_credit and occupation is not None else SKILL_CAP
        skill_view.append(
            SkillView(id=spec.id, base=base, allocated=allocated, current=current, cap=cap)
        )

    for skill_id in skills:
        if skill_id not in skills_by_id:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_SKILL",
                    field=f"skills.{skill_id}",
                    message=f"未知技能 id: {skill_id}",
                )
            )

    if interest_spent > interest_budget:
        issues.append(
            ValidationIssue(
                code="INTEREST_POINTS_EXCEEDED",
                field="skills",
                message=f"非职业技能已用 {interest_spent} 点兴趣点，超过预算 {interest_budget}",
            )
        )

    total_spent = occupation_spent + interest_spent
    total_budget = occupation_budget + interest_budget
    if total_spent > total_budget:
        issues.append(
            ValidationIssue(
                code="OCCUPATION_POINTS_EXCEEDED",
                field="skills",
                message=f"技能总点数已用 {total_spent}，超过总预算 {total_budget}"
                f"（职业 {occupation_budget} + 兴趣 {interest_budget}）",
            )
        )

    # 信用评级必填 + 范围校验：职业已选时才能校验（没有区间可比）；信用值为 0
    # 或低于下限也会被这条挡住，等价于「必须填」。
    credit_value = skills.get("credit-rating", 0)
    if occupation is not None and not (
        occupation.credit_min <= credit_value <= occupation.credit_max
    ):
        issues.append(
            ValidationIssue(
                code="CREDIT_OUT_OF_RANGE",
                field="skills.credit-rating",
                message=(
                    f"信用评级 {credit_value} 不在职业 {occupation.name} 的区间 "
                    f"[{occupation.credit_min}, {occupation.credit_max}] 内"
                ),
            )
        )

    return ComputeResult(
        derived_stats=derived_stats,
        occupation_skill_points=SkillPointsBudget(
            budget=occupation_budget,
            spent=occupation_spent,
            remaining=occupation_budget - occupation_spent,
        ),
        interest_skill_points=SkillPointsBudget(
            budget=interest_budget,
            spent=interest_spent,
            remaining=interest_budget - interest_spent,
        ),
        skill_view=skill_view,
        validation=issues,
    )


def compute_preview(
    attributes: dict[str, int],
    occupation_id: int | None,
    skills: dict[str, int],
) -> ComputeResult:
    """`POST /systems/{systemId}/character/preview` 的计算核心：职业按 id 查。"""
    occupation, not_found = find_occupation_by_id(occupation_id)
    return _compute(attributes, occupation, skills, occupation_not_found=not_found)


def validate_character(
    attributes: dict[str, int],
    occupation_name: str | None,
    skills: dict[str, int],
) -> list[ValidationIssue]:
    """`complete_character` 的校验核心：角色卡存的是职业名字符串，按名字查。"""
    occupation, not_found = find_occupation_by_name(occupation_name)
    return _compute(attributes, occupation, skills, occupation_not_found=not_found).validation
