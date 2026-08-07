from random import Random

import pytest

from app.core.coc7_character_generation import generate_character_draft
from app.core.coc7_content import build_coc7_ruleset


@pytest.mark.parametrize("seed", range(40))
def test_generated_draft_is_rule_valid_for_multiple_random_seeds(seed: int) -> None:
    draft = generate_character_draft(build_coc7_ruleset(), rng=Random(seed))

    assert draft.compute_result.validation == []
    assert draft.age == 28
    assert draft.occupation
    assert draft.occupation_choice_skill_ids == list(
        dict.fromkeys(draft.occupation_choice_skill_ids)
    )
    assert "形象描述：" in draft.background
    assert draft.equipment


def test_generated_draft_contains_all_rule_attributes_and_skills() -> None:
    ruleset = build_coc7_ruleset()
    draft = generate_character_draft(ruleset, rng=Random(259))

    assert set(draft.attributes) == {spec.key for spec in ruleset.attributes}
    assert set(draft.skills) == {spec.id for spec in ruleset.skills}
    assert all(1 <= value <= 99 for value in draft.attributes.values())
    assert all(0 <= value <= 99 for value in draft.skills.values())
