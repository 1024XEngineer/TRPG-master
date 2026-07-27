"""对拍两遍独立推导的结果（issue #114 第三步）。

229 条职业数据由模型逐条裁定，而模型出的错**看起来都很合理**——本项目已有
先例：PR #85 期间记者/间谍的技能点公式被误设成 `EDU*4`，是个完全说得通的值，
最后靠人肉对照规则表才发现。229 条里错几条，靠抽查是抽不出来的。

所以做两遍**独立**推导再对拍：

- 两遍看的都是同一份原始数据，但第二遍拿不到第一遍的任何结果和推理；
- 两遍的**分批边界特意错开**（第一遍连续区间、第二遍跨步取样）。同一批里的
  职业互为上下文，若两遍分组相同，很可能诱发同一处系统性误判，对拍就白做了。

一致的条目进数据；不一致的列出来人工裁定。这个脚本只负责找出不一致，不做
任何裁定——它是**度量**，不是权威。

用法：

    python3 scripts/coc7_occupations/compare_passes.py <pass1目录> <pass2目录>
"""

import json
import sys
from pathlib import Path


def load_pass(directory: Path) -> dict[int, dict]:
    """把一遍推导的所有分批结果合并成 {职业序号: 结果}。

    `batch_*.json` 是正常分批产物，**序号重复会直接报错**——分批本该是互不重叠
    的划分，重叠说明某一批处理错了范围，静默去重会把这个信号盖掉（第一次跑
    pass2 就是这么发现 batch_2 做成了 batch_0 那批：提示词里说"数组下标"，
    而 JSON 里那个字段恰好叫 `index` 存的却是序号，agent 取了字段）。

    `override_*.json` 是补跑产物，**允许覆盖**已有条目：原始数据修正后需要
    重推的那些职业走这条路，不必把整批重跑一遍。
    """
    merged: dict[int, dict] = {}
    for path in sorted(directory.glob("batch_*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            index = entry["index"]
            if index in merged:
                raise SystemExit(f"序号 {index} 在 {directory.name} 里出现了两次（分批重叠）")
            merged[index] = entry

    for path in sorted(directory.glob("override_*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            merged[entry["index"]] = entry

    return merged


def normalize(entry: dict) -> dict:
    """比较用的规范形式。

    只规范「表示方式」上的无谓差异（集合顺序、槽的排列），**不碰语义**：
    - 技能 id 用集合比，顺序不同不算分歧；
    - 槽按 (count, 候选集) 排序后比，声明顺序不同不算分歧；
    - `label` 是给人看的说明文字，措辞不同不算分歧，**不参与比较**；
    - `evidence` 同理，是复核材料不是结论。
    """
    slots = []
    for slot in entry.get("choice_slots") or []:
        candidates = slot.get("candidate_skill_ids")
        slots.append((slot["count"], tuple(sorted(candidates)) if candidates else None))
    return {
        "fixed": frozenset(entry.get("fixed_skill_ids") or []),
        "slots": tuple(sorted(slots, key=lambda s: (s[0], s[1] or ()))),
        "unmapped": frozenset(entry.get("unmapped") or []),
    }


def describe(diff_key: str, a, b) -> str:
    if diff_key == "slots":
        return f"    槽 pass1={a}\n       pass2={b}"
    only_1 = sorted(a - b)
    only_2 = sorted(b - a)
    parts = []
    if only_1:
        parts.append(f"仅 pass1 有: {only_1}")
    if only_2:
        parts.append(f"仅 pass2 有: {only_2}")
    return f"    {diff_key}: " + "；".join(parts)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    pass1 = load_pass(Path(sys.argv[1]))
    pass2 = load_pass(Path(sys.argv[2]))

    only_1 = sorted(set(pass1) - set(pass2))
    only_2 = sorted(set(pass2) - set(pass1))
    if only_1 or only_2:
        print(f"⚠️  覆盖不一致：仅 pass1 有 {len(only_1)} 条，仅 pass2 有 {len(only_2)} 条")
        for i in (only_1 + only_2)[:20]:
            print(f"    下标 {i}")

    shared = sorted(set(pass1) & set(pass2))
    agreed, conflicts = [], []
    for index in shared:
        a, b = normalize(pass1[index]), normalize(pass2[index])
        if a == b:
            agreed.append(index)
        else:
            conflicts.append((index, pass1[index], pass2[index], a, b))

    print(f"\n两遍都覆盖到: {len(shared)} 条")
    print(f"一致: {len(agreed)} 条 ({len(agreed) * 100 // max(len(shared), 1)}%)")
    print(f"不一致: {len(conflicts)} 条 —— 这些需要逐条裁定\n")

    for index, e1, _e2, a, b in conflicts:
        print(f"  [{index}] {e1['name']}")
        for key in ("fixed", "slots", "unmapped"):
            if a[key] != b[key]:
                print(describe(key, a[key], b[key]))

    # 两遍里任意一遍报了 unmapped（技能名在目录里找不到对应 id）的条目单独列出。
    # 这类不一定是分歧，但一定是"数据里有目录装不下的东西"，需要人看。
    unmapped = sorted(
        {i for i in shared for e in (pass1[i], pass2[i]) if e.get("unmapped")},
    )
    if unmapped:
        print(f"\n有 unmapped 技能名的职业: {len(unmapped)} 条")
        for index in unmapped:
            names = set(pass1[index].get("unmapped") or []) | set(
                pass2[index].get("unmapped") or []
            )
            print(f"  [{index}] {pass1[index]['name']}: {sorted(names)}")


if __name__ == "__main__":
    main()
