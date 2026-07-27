"""把已拍板的建模口径应用成确定性规则（issue #114）。

两遍独立推导出的 64 条冲突里，约 52 条不是判断错误，而是**同一个未定口径的两种
合理答案**——集中在「技艺」「外语」这两个专精族上：目录把它们建成三个匿名编号槽
（`art-craft-1/2/3`、`language-foreign-1/2/3`），于是「技艺（表演）」既可以说
"目录里没有表演，进 unmapped"，也可以说"映射到 art-craft-1"，两遍各选了一种。

口径已定（规则依据见下），所以这里把它写成代码而不是再跑一遍模型：口径是确定性
的，让模型重猜一次只会引入新的随机性。

## 口径与规则依据

COC7 规则表 `附表` sheet：

> 「你可以花费技能在**任意专业化技能**上。**不可以加点在作为类属的"艺术与手艺"上**。」
> 「玩家也可以添加更多手艺，比如：游戏，木工，油漆工，铁匠等」

即：每个专精是独立技能、类属本身不可加点、专精是**开放式**的（玩家可自行添加）。
所以角色卡上那三行编号槽就是"玩家自填专精的行"，而**无论专精是否指定**，职业要求
的都是"你这三行里有一行是它"——对技能点记账而言完全等价。

因此统一成：`技艺（X）` / `外语（X）` 一律建成候选为三个编号 id 的自选槽，
`count` = 需要几项，专精名写进 `label`。

⚠️ **残留缺口（本期不修）**：规则里「技艺（表演）」指的就是表演那一项，本模型
无法校验玩家实际写的是不是表演。这个缺口不是本口径造成的，而是目录模型固有的——
专精按规则是开放式的，不给 `SkillSpec` 加专精文本字段就无从校验。需单独开 issue。

## 用法

    python3 scripts/coc7_occupations/normalize_conventions.py <pass目录> [<pass目录>...]

原地改写各目录下的 `*.json`（会先备份成 `*.json.bak`）。
"""

import json
import re
import shutil
import sys
from pathlib import Path

# 专精族：类属关键词 → 该族的编号槽 id。
SPECIALIZATION_FAMILIES = {
    "技艺": ["art-craft-1", "art-craft-2", "art-craft-3"],
    "艺术": ["art-craft-1", "art-craft-2", "art-craft-3"],
    "手艺": ["art-craft-1", "art-craft-2", "art-craft-3"],
    "外语": ["language-foreign-1", "language-foreign-2", "language-foreign-3"],
    "其他语言": ["language-foreign-1", "language-foreign-2", "language-foreign-3"],
    "学识": ["lore-1", "lore-2", "lore-3"],
}

# 这些具名 id 是目录里单独列出的技艺专精。按口径它们**不进**技艺槽的候选——
# 候选只放三个编号槽，否则"选一个专精"和"选一个具名技能"混在一个列表里，
# 语义不统一。
NAMED_CRAFT_IDS = {"carpentry", "illusion", "photography"}

_COUNT_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}

# unmapped 里能确定性映射到既有 id 的技能名。
#
# 「射击（霰弹枪）」不是缺项：COC7 里 Firearms (Rifle/Shotgun) 本来就是**一项**
# 技能（`firearm-rifle` 的 name_en 一直是这个）。之所以被报成找不到，是因为它的
# 中文名当时写作「射击：步枪」把霰弹枪吞了——名字已修，这里把按旧名推导出的
# 结果一并纠回来，不必为此重跑模型。
UNMAPPED_ALIASES = {
    "射击（霰弹枪）": "firearm-rifle",
    "射击：霰弹枪": "firearm-rifle",
    "格斗（链锯）": "fighting-chainsaw",
    "驾驶（热气球）": "pilot-balloon",
}


def _family_of(text: str) -> list[str] | None:
    """这段文字属于哪个专精族（按最长关键词优先，避免"其他语言"被"外语"抢走）。"""
    for keyword in sorted(SPECIALIZATION_FAMILIES, key=len, reverse=True):
        if keyword in text:
            return SPECIALIZATION_FAMILIES[keyword]
    return None


def _count_in(text: str) -> int:
    """从 label 里读出要选几项，读不出按 1。"""
    match = re.search(r"(任[意一]|)([一二两三四1234])项", text)
    if match:
        return _COUNT_WORDS.get(match.group(2), 1)
    return 1


def normalize_entry(entry: dict) -> tuple[dict, list[str]]:
    """按口径归一化一条职业，返回 (新条目, 改动说明列表)。"""
    changes: list[str] = []
    fixed = list(entry.get("fixed_skill_ids") or [])
    slots = [dict(s) for s in (entry.get("choice_slots") or [])]
    unmapped = list(entry.get("unmapped") or [])

    # ① unmapped 里能确定性映射的 → 直接落成固定技能；专精族条目 → 转成自选槽
    remaining_unmapped = []
    for name in unmapped:
        alias = UNMAPPED_ALIASES.get(name)
        if alias is not None:
            fixed.append(alias)
            changes.append(f"unmapped「{name}」→ {alias}")
            continue
        family = _family_of(name)
        if family is None:
            remaining_unmapped.append(name)
            continue
        slots.append({"count": _count_in(name), "candidate_skill_ids": list(family), "label": name})
        changes.append(f"unmapped「{name}」→ 专精槽")

    # ② 固定项里的编号槽 id → 转成对应族的自选槽（"指定专精"也走槽）
    still_fixed = []
    for skill_id in fixed:
        family = next(
            (f for f in SPECIALIZATION_FAMILIES.values() if skill_id in f),
            None,
        )
        if family is None:
            still_fixed.append(skill_id)
            continue
        slots.append({"count": 1, "candidate_skill_ids": list(family), "label": skill_id})
        changes.append(f"固定项 {skill_id} → 专精槽")

    # ③ 已有的专精槽：候选统一成三个编号 id，剔除混进来的具名专精
    for slot in slots:
        candidates = slot.get("candidate_skill_ids")
        if not candidates:
            continue
        family = next(
            (f for f in SPECIALIZATION_FAMILIES.values() if set(candidates) & set(f)),
            None,
        )
        if family is None:
            continue
        cleaned = sorted(set(family))
        if sorted(set(candidates)) != cleaned:
            # 括号是必要的可读性保险：Python 里 `-` 比 `&` 结合更紧，不加括号
            # 语义虽然一样，但读起来像 `a - (b & c)`。
            dropped = sorted((set(candidates) - set(family)) & NAMED_CRAFT_IDS)
            slot["candidate_skill_ids"] = cleaned
            changes.append(f"槽候选归一化{'（剔除 ' + ','.join(dropped) + '）' if dropped else ''}")

    # ④ 合并完全等价的专精槽（同族、同 count），避免 ①②③ 产生重复
    merged: list[dict] = []
    for slot in slots:
        same = next(
            (
                m
                for m in merged
                if m["count"] == slot["count"]
                and m.get("candidate_skill_ids") == slot.get("candidate_skill_ids")
                and slot.get("candidate_skill_ids")
            ),
            None,
        )
        if same is None:
            merged.append(slot)
        else:
            changes.append("合并等价专精槽")

    out = dict(entry)
    out["fixed_skill_ids"] = still_fixed
    out["choice_slots"] = merged
    out["unmapped"] = remaining_unmapped
    return out, changes


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    total_changed = 0
    for directory in sys.argv[1:]:
        for path in sorted(Path(directory).glob("*.json")):
            entries = json.loads(path.read_text(encoding="utf-8"))
            new_entries, changed = [], 0
            for entry in entries:
                normalized, changes = normalize_entry(entry)
                new_entries.append(normalized)
                if changes:
                    changed += 1
            if changed:
                shutil.copy(path, path.with_suffix(".json.bak"))
                path.write_text(
                    json.dumps(new_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            total_changed += changed
            print(f"  {path.parent.name}/{path.name}: {changed}/{len(entries)} 条被归一化")
    print(f"\n合计归一化 {total_changed} 条")


if __name__ == "__main__":
    main()
