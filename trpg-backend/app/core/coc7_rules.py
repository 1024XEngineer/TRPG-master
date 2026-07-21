"""COC7 建卡计算 / 校验（issue #84 S2；issue #112 改为参数注入）：路线乙的
核心——规则计算只在后端权威实现一份，前端只渲染。给定一份建卡草稿（属性 +
职业 + 技能分配），算出全部派生量并产出结构化校验报告。

公式来源与 `app/service/character.py::roll_attributes`、
`trpg-frontend/src/data/character-model.ts`（S3 之前前端本地那份实现，
S2 阶段只读它核对公式，不依赖它是否存在）保持一致，不自创新公式。

issue #112：此前本模块直接 import 权威规则数据模块（存放 COC7 属性/技能/
职业目录的那个 `app/core/` 文件）的模块常量，规则核心因此写死只认识 COC7
一种规则系统，也造成规则数据存在"规则引擎读代码常量、
`GET /systems/{systemId}/ruleset` 读数据库"两个源、彼此没有同步机制（改了
那份数据模块不删库不会生效）。改为由调用方传入 `RulesetRead` 后，本模块对
具体是哪个规则系统无知，`app/service/character.py` 负责决定传哪份规则数据
进来。

对外两个入口：
- `compute_preview(ruleset, ...)`：给 `POST /systems/{systemId}/character/preview`
  用，返回衍生值 + 两个技能点预算 + 全部技能的 base/cap/当前值 + 校验报告。
- `validate_character(ruleset, ...)`：给 `complete_character` 用，只要校验
  报告（建卡完成前的权威闸门）。

两者内部共用同一套 `_compute`，校验规则只实现一份，不会出现"预览"和
"complete 时校验"两条腿走路、结果不一致的情况。
"""

import re
from dataclasses import dataclass, field

from app.dto.game import OccupationSpec, RulesetRead

SKILL_CAP = 99

# 掷骰法的属性只做宽松的合理性兜底：骰子结果本来就不受点数购买法的
# [10, 90] 约束（(2d6+6)*5 最低就是 40，3d6*5 最低 15），而且服务端掷的骰子
# 没什么可不信的，这里只拦明显越界的脏数据。
ROLLED_ATTRIBUTE_MIN = 1
ROLLED_ATTRIBUTE_MAX = 99

GENERATION_POINT_BUY = "pointbuy"
GENERATION_ROLL = "roll"


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


def find_occupation_by_id(
    occupations: list[OccupationSpec], occupation_id: int | None
) -> tuple[OccupationSpec | None, bool]:
    """按 id 查职业。返回 `(职业或 None, 传了 id 但没查到)`。"""
    if occupation_id is None:
        return None, False
    match = next((o for o in occupations if o.id == occupation_id), None)
    return match, match is None


def find_occupation_by_name(
    occupations: list[OccupationSpec], name: str | None
) -> tuple[OccupationSpec | None, bool]:
    """按名字查职业——`complete_character` 时角色卡存的是职业名字符串
    （不是 id），只能这样映射回职业定义。"""
    if name is None:
        return None, False
    match = next((o for o in occupations if o.name == name), None)
    return match, match is None


def _validate_attributes(
    ruleset: RulesetRead, attributes: dict[str, int], generation_method: str
) -> list[ValidationIssue]:
    """属性必须正好是 ruleset 声明的那些键、每项都是整数且落在合法区间；点数
    购买法还要额外校验总点数不超预算。

    **区间和总预算都取决于生成方法**（issue #96 决策 1）：
    - `pointbuy`：参与点数购买的属性走 `ruleset.attribute_point_buy` 声明的
      `[min_value, max_value]`，且它们的总和不能超过 `budget`；
    - `roll`：只做宽松兜底 `[1, 99]`，不校验总和——骰子结果本来就不受点数
      购买法约束（8 项总和均值约 457、范围 195–720），拿预算去卡它会把合法
      掷出来的角色卡判成非法。

    `ruleset.attribute_point_buy` 为 `None`（自定义系统还没配置点数购买约束）
    时，点数购买法也退回宽松兜底区间、且不校验总预算——issue #112：没有约束
    数据就没法裁决，不能拿 COC7 的数字硬套上去。

    不参与点数购买的属性（比如幸运）无论哪种方法都走宽松兜底：它们只能掷。

    结构性问题（缺键/多键）报一条汇总就返回；结构没问题时再逐项查范围。
    """
    issues: list[ValidationIssue] = []
    attribute_keys = {a.key for a in ruleset.attributes}
    actual_keys = set(attributes.keys())
    missing = attribute_keys - actual_keys
    extra = actual_keys - attribute_keys
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

    point_buy_keys = frozenset(a.key for a in ruleset.attributes if a.point_buy)
    is_point_buy = generation_method == GENERATION_POINT_BUY
    for key in sorted(attribute_keys):
        value = attributes[key]
        if not isinstance(value, int) or isinstance(value, bool):
            issues.append(
                ValidationIssue(
                    code="INVALID_ATTRIBUTES",
                    field=f"attributes.{key}",
                    message=f"{key} 必须是整数",
                )
            )
            continue

        if is_point_buy and key in point_buy_keys and ruleset.attribute_point_buy is not None:
            low, high = ruleset.attribute_point_buy.min_value, ruleset.attribute_point_buy.max_value
        else:
            low, high = ROLLED_ATTRIBUTE_MIN, ROLLED_ATTRIBUTE_MAX
        if not (low <= value <= high):
            issues.append(
                ValidationIssue(
                    code="INVALID_ATTRIBUTES",
                    field=f"attributes.{key}",
                    message=f"{key} 的值 {value} 不在合法范围 [{low}, {high}] 内",
                )
            )

    if is_point_buy and not issues and ruleset.attribute_point_buy is not None:
        spent = sum(attributes[key] for key in point_buy_keys)
        if spent > ruleset.attribute_point_buy.budget:
            issues.append(
                ValidationIssue(
                    code="ATTRIBUTE_POINTS_EXCEEDED",
                    field="attributes",
                    message=(f"属性点总数 {spent} 超出预算 {ruleset.attribute_point_buy.budget}"),
                )
            )
    return issues


def validate_age(ruleset: RulesetRead, age: int | None) -> list[ValidationIssue]:
    """年龄要落在 `ruleset.age_range` 声明的合法区间内（COC7 是 [15, 89]，
    年龄档从 15-19 起、到 80-89 止）。

    没填年龄不拦——年龄是本期才开始入库的字段，迁移之前建的卡都没有，拿它
    去拒绝那些卡等于用新规则追溯判旧数据非法。`ruleset.age_range` 为 `None`
    （自定义系统还没配置年龄区间）时同样跳过校验——issue #112：没有约束数据
    就没法裁决。
    """
    if age is None or ruleset.age_range is None:
        return []
    if not (ruleset.age_range.min_value <= age <= ruleset.age_range.max_value):
        return [
            ValidationIssue(
                code="INVALID_AGE",
                field="age",
                message=(
                    f"年龄 {age} 不在合法范围 "
                    f"[{ruleset.age_range.min_value}, {ruleset.age_range.max_value}] 内"
                ),
            )
        ]
    return []


def _compute(
    ruleset: RulesetRead,
    attributes: dict[str, int],
    occupation: OccupationSpec | None,
    skills: dict[str, int],
    *,
    occupation_not_found: bool,
    generation_method: str = GENERATION_POINT_BUY,
) -> ComputeResult:
    issues: list[ValidationIssue] = []
    if occupation_not_found:
        issues.append(
            ValidationIssue(
                code="OCCUPATION_NOT_FOUND", field="occupation", message="未找到匹配的职业"
            )
        )

    attribute_issues = _validate_attributes(ruleset, attributes, generation_method)
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

    skills_by_id = {skill.id: skill for skill in ruleset.skills}

    occupation_spent = 0
    interest_spent = 0
    skill_view: list[SkillView] = []

    # 遍历技能表里的全部技能（不只是草稿里提到的那些），这样 `compute_preview`
    # 能一次性把完整的 base/cap 都带给前端渲染，草稿没提到的技能视为
    # 「未分配点数」（current 就是 base）。
    for spec in ruleset.skills:
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

    # 这里查的是**总预算**，不是"职业点单独有没有超"——后者会误杀合法的卡。
    # COC7 里兴趣点可以花在任何技能上（包括职业技能），职业点则只能花在职业
    # 技能上。所以从最终值反推时，唯一能确定的约束是：
    #   ①非职业技能只能由兴趣点买 → 上面那条 INTEREST_POINTS_EXCEEDED；
    #   ②两个池加起来够不够 → 这一条。
    # 职业技能上的点数超过职业预算是允许的（超出部分由兴趣点承担），所以
    # `occupation_spent` 只是给前端渲染的记账，不作为闸门。
    total_spent = occupation_spent + interest_spent
    total_budget = occupation_budget + interest_budget
    if total_spent > total_budget:
        issues.append(
            ValidationIssue(
                code="SKILL_POINTS_EXCEEDED",
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
    ruleset: RulesetRead,
    attributes: dict[str, int],
    occupation_id: int | None,
    skills: dict[str, int],
    generation_method: str = GENERATION_POINT_BUY,
) -> ComputeResult:
    """`POST /systems/{systemId}/character/preview` 的计算核心：职业按 id 查。

    `ruleset` 由调用方注入（issue #112）——这里对它具体是哪个规则系统无知，
    只消费 `attributes`/`skills`/`occupations`/`attribute_point_buy`/`age_range`
    这几个字段。

    跟 `validate_character` 一样接受 `generation_method`——预览和最终校验必须
    用同一套判据，否则会出现「预览说没问题、提交被拒」这种最难排查的不一致。
    """
    occupation, not_found = find_occupation_by_id(ruleset.occupations, occupation_id)
    return _compute(
        ruleset,
        attributes,
        occupation,
        skills,
        occupation_not_found=not_found,
        generation_method=generation_method,
    )


def validate_character(
    ruleset: RulesetRead,
    attributes: dict[str, int],
    occupation_name: str | None,
    skills: dict[str, int],
    generation_method: str = GENERATION_POINT_BUY,
) -> list[ValidationIssue]:
    """`complete_character` 的校验核心：角色卡存的是职业名字符串，按名字查。

    `ruleset` 由调用方注入（issue #112），语义同 `compute_preview`。

    `generation_method` 决定属性区间与是否校验总预算，见 `_validate_attributes`。
    默认按点数购买法校验——这是更严的那条路径，调用方忘记传时宁可误拦也不漏放。
    """
    occupation, not_found = find_occupation_by_name(ruleset.occupations, occupation_name)
    return _compute(
        ruleset,
        attributes,
        occupation,
        skills,
        occupation_not_found=not_found,
        generation_method=generation_method,
    ).validation
