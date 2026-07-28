"""合并两遍推导 + 裁定记录，生成 `coc7_content.py` 的职业段（issue #114 最后一步）。

流程：

    extract_raw.py      规则表 → raw_occupations.json（只搬运，不解释）
    ↓ workflow 两遍独立推导（分批边界错开）
    normalize_conventions.py  应用已定口径（确定性，不用模型）
    compare_passes.py   对拍 → 分歧清单
    ↓ 人工裁定 → resolutions.json
    build_occupations.py（本文件）→ coc7_content.py 的职业段

信用评级区间和技能点公式**不经过模型**：它们在规则表里是结构化的（`30-70`、
`教育×2＋力量或敏捷×2`），确定性解析即可，让模型碰只会引入不必要的风险。
模型只负责本职技能与自选槽——那部分才需要判断。

两遍不一致、又没有裁定记录的条目会让脚本**报错退出**，不允许静默取其一；
两遍里任何一遍缺失或多出条目（相对 raw_occupations.json）同样报错退出，
不允许被取交集悄悄丢掉。

用法：

    python3 scripts/coc7_occupations/build_occupations.py <pass1目录> <pass2目录>
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from compare_passes import load_pass, normalize  # noqa: E402

HERE = Path(__file__).parent
RAW = HERE / "raw_occupations.json"
RESOLUTIONS = HERE / "resolutions.json"
OUTPUT = HERE / "generated_occupations.py"

# 规则表用中文属性名和全角符号写公式，这里翻译成 `evaluate_skill_points_formula`
# 认识的形式。「或」表示二选一取较高，对应求值器的 `MAX(...)`。
ATTR_NAMES = {
    "力量": "STR",
    "体质": "CON",
    "意志": "POW",
    "敏捷": "DEX",
    "外貌": "APP",
    "体型": "SIZ",
    "智力": "INT",
    "教育": "EDU",
}


def parse_credit(raw: str) -> tuple[int, int]:
    """`"30-70"` → `(30, 70)`。"""
    match = re.fullmatch(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", str(raw))
    if match is None:
        raise ValueError(f"无法解析的信用评级区间: {raw!r}")
    low, high = int(match.group(1)), int(match.group(2))
    if low > high:
        raise ValueError(f"信用评级区间下限大于上限: {raw!r}")
    return low, high


def parse_formula(raw: str) -> str:
    """`"教育×2＋力量或敏捷×2"` → `"EDU*2+MAX(STR,DEX)*2"`。"""
    text = str(raw).replace("＋", "+").replace("×", "*").replace("　", "").strip()
    terms = []
    for term in text.split("+"):
        match = re.fullmatch(r"([^*]+)\*(\d+)", term.strip())
        if match is None:
            raise ValueError(f"无法解析的技能点公式项: {term!r}（完整公式 {raw!r}）")
        attrs_text, coefficient = match.group(1), match.group(2)
        attrs = [ATTR_NAMES[a] for a in attrs_text.split("或") if a in ATTR_NAMES]
        if len(attrs) != len(attrs_text.split("或")):
            raise ValueError(f"公式里有不认识的属性名: {attrs_text!r}（完整公式 {raw!r}）")
        head = attrs[0] if len(attrs) == 1 else f"MAX({','.join(attrs)})"
        terms.append(f"{head}*{coefficient}")
    return "+".join(terms)


def reconcile(
    pass1: dict, pass2: dict, resolutions: dict[int, str], raw_indices: set[int]
) -> dict[int, dict]:
    """两遍一致就直接采用；不一致则按裁定记录取其一，没有裁定就报错。

    覆盖率先于内容对拍检查：之前只取 `set(pass1) & set(pass2)` 的交集，某一遍
    如果漏了一批（比如某次批处理中途失败），缺失的职业会被静默丢出结果、还
    跟着重新编号——生成不会报错，只是职业数量比 229 少，且看不出是哪条丢了。
    """
    if set(pass1) != raw_indices or set(pass2) != raw_indices:
        problems = []
        if missing := raw_indices - set(pass1):
            problems.append(f"pass1 缺失（相对 raw_occupations.json）: {sorted(missing)}")
        if missing := raw_indices - set(pass2):
            problems.append(f"pass2 缺失（相对 raw_occupations.json）: {sorted(missing)}")
        if extra := set(pass1) - raw_indices:
            problems.append(f"pass1 多出（raw_occupations.json 里没有）: {sorted(extra)}")
        if extra := set(pass2) - raw_indices:
            problems.append(f"pass2 多出（raw_occupations.json 里没有）: {sorted(extra)}")
        raise SystemExit(
            "两遍推导覆盖的职业集合和 raw_occupations.json 不一致，拒绝生成：\n"
            + "\n".join(problems)
        )

    merged, unresolved = {}, []
    for index in sorted(raw_indices):
        if normalize(pass1[index]) == normalize(pass2[index]):
            merged[index] = pass1[index]
            continue
        take = resolutions.get(index)
        if take is None:
            unresolved.append((index, pass1[index]["name"]))
            continue
        merged[index] = (pass1 if take == "pass1" else pass2)[index]
    if unresolved:
        lines = "\n".join(f"  [{i}] {n}" for i, n in unresolved)
        raise SystemExit(f"以下条目两遍不一致且没有裁定记录，拒绝生成：\n{lines}")
    return merged


def _render_description(text: str, indent: str = "            ") -> str:
    """把职业介绍渲染成不超行宽的相邻字符串字面量（Python 会自动拼接）。

    规则表里的职业介绍最长有 800 多字，写成一行必然超 ruff 的 100 字符行宽，
    而中文没有空格、格式化工具没法自动折行。按字数切段是唯一不损失内容的办法
    ——截断会丢掉真实的规则书内容，给整个文件开 E501 例外则等于让这个文件
    以后可以随便超宽。
    """
    if not text:
        return "''"
    width = 40  # 中文按两倍宽算，40 字 ≈ 80 列，留出缩进余量
    pieces = [text[i : i + width] for i in range(0, len(text), width)]
    if len(pieces) == 1:
        return repr(pieces[0])
    body = "\n".join(f"{indent}{piece!r}" for piece in pieces)
    return f"(\n{body}\n{indent[:-4]})"


def render(occupations: list[dict]) -> str:
    """生成 Python 源码片段。"""
    chunks = []
    for occupation in occupations:
        slots = "".join(
            "\n            SkillChoiceSlot(\n"
            f"                count={slot['count']},\n"
            f"                candidate_skill_ids={slot['candidate_skill_ids']!r},\n"
            f"                label={slot['label']!r},\n"
            "            ),"
            for slot in occupation["choice_slots"]
        )
        slots_field = f"\n        choice_slots=[{slots}\n        ]," if slots else ""
        chunks.append(
            "    OccupationSpec(\n"
            f"        id={occupation['id']},\n"
            f"        name={occupation['name']!r},\n"
            f"        credit_min={occupation['credit_min']},\n"
            f"        credit_max={occupation['credit_max']},\n"
            f"        skill_points_formula={occupation['skill_points_formula']!r},\n"
            f"        description={_render_description(occupation['description'])},\n"
            f"        skill_ids={occupation['skill_ids']!r},"
            f"{slots_field}\n"
            "    ),"
        )
    body = "\n".join(chunks)
    return f"COC7_OCCUPATIONS: list[OccupationSpec] = [\n{body}\n]\n"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)

    raw = {o["index"]: o for o in json.loads(RAW.read_text(encoding="utf-8"))}
    resolutions = {
        r["index"]: r["take"]
        for r in json.loads(RESOLUTIONS.read_text(encoding="utf-8"))["resolutions"]
    }
    merged = reconcile(
        load_pass(Path(sys.argv[1])), load_pass(Path(sys.argv[2])), resolutions, set(raw)
    )

    occupations = []
    for new_id, index in enumerate(sorted(merged), start=1):
        entry, source = merged[index], raw[index]
        credit_min, credit_max = parse_credit(source["credit_raw"])
        occupations.append(
            {
                # id 按序号顺序重新编号 1..229。规则表的序号从 2 起、且中间可能
                # 有空缺，直接拿来当 id 会让「有多少个职业」和「id 最大值」对不上。
                "id": new_id,
                "name": source["name"],
                "credit_min": credit_min,
                "credit_max": credit_max,
                "skill_points_formula": parse_formula(source["formula_raw"]),
                "description": (source.get("description") or "").strip().replace("\n", " "),
                "skill_ids": sorted(entry["fixed_skill_ids"]),
                "choice_slots": entry["choice_slots"],
            }
        )

    OUTPUT.write_text(render(occupations), encoding="utf-8")
    print(f"生成 {len(occupations)} 个职业 -> {OUTPUT}")

    still_unmapped = {raw[i]["name"]: e["unmapped"] for i, e in merged.items() if e.get("unmapped")}
    if still_unmapped:
        print(f"\n仍有 unmapped 技能名的职业: {len(still_unmapped)} 条")
        for name, names in still_unmapped.items():
            print(f"  {name}: {names}")


if __name__ == "__main__":
    main()
