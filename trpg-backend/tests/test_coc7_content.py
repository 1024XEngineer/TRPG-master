"""COC7 权威数据本身的完整性铁律（issue #84 S2 任务 0）：职业引用的技能 id
必须都能在技能表里查到，不允许悬空引用。S1 移植时就踩过一次这个坑（navigate/
carpentry/illusion 三个技能当时没补全），这条测试防止以后再犯同样的错误。
"""

from app.core.coc7_content import COC7_OCCUPATIONS, COC7_SKILLS


def test_all_occupation_skill_ids_exist_in_skill_table() -> None:
    valid_skill_ids = {skill.id for skill in COC7_SKILLS}

    dangling: list[str] = []
    for occupation in COC7_OCCUPATIONS:
        for skill_id in occupation.skill_ids:
            if skill_id not in valid_skill_ids:
                dangling.append(f"{occupation.name}({occupation.id}) -> {skill_id}")

    assert dangling == [], f"存在悬空技能引用: {dangling}"
