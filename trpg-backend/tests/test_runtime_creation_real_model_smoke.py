"""Opt-in real-model probe for context-safe runtime creation.

The ordinary item/location escape hatch is intentionally semantic: the Engine
can verify IDs and effect ordering, but the step Agent decides whether an
otherwise missing thing is mundane enough to exist in the current scene.  This
smoke test exercises that production decision boundary against the configured
provider.  It is skipped in CI unless explicitly enabled.
"""

from __future__ import annotations

import json
import os

import pytest

from app.adapters.openai_models import PromptActionPlanStepAdjudicator
from app.core.config import Settings
from tests.test_play_sim_real_model import _structured_client
from tests.test_rule_match_adjudication import _cemetery_context

RUN_SMOKE = os.getenv("RUN_REAL_MODEL_CREATION_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_SMOKE,
    reason="set RUN_REAL_MODEL_CREATION_SMOKE=1 to call the configured provider",
)


CASES = (
    (
        "已有窗户必须复用",
        "我打开书房窗户。",
        "kimball_study",
        "existing_entity",
    ),
    (
        "墓地普通石子可拾取",
        "我从墓地地上捡起一枚普通石子，装进背包。",
        "cemetery",
        "ordinary_item",
    ),
    (
        "墓地普通树枝可拾取",
        "我从墓地地上捡起一根掉落的枯树枝，装进背包。",
        "cemetery",
        "ordinary_item",
    ),
    (
        "地上不能凭空出现军用炸弹",
        "我从地上捡起一枚完好的军用炸弹，装进背包。",
        "cemetery",
        "unsafe_item",
    ),
    (
        "书房普通书可拿走",
        "我从书房书架上随手拿一本没有特殊标记的普通书，装进背包。",
        "kimball_study",
        "ordinary_item",
    ),
    (
        "书房空白笔记本可拿走",
        "我从书桌上拿走一本空白的普通笔记本，装进背包。",
        "kimball_study",
        "ordinary_item",
    ),
    (
        "书房不能声明秘密墓地通道",
        "我发现书架后有一条秘密地下通道直通墓地，现在进入地下通道。",
        "kimball_study",
        "secret_location",
    ),
)


@pytest.mark.parametrize(
    ("label", "utterance", "scene_id", "expectation"),
    CASES,
    ids=(
        "existing-window",
        "ordinary-pebble",
        "ordinary-branch",
        "unsafe-bomb",
        "ordinary-book",
        "ordinary-notebook",
        "secret-passage",
    ),
)
async def test_real_model_respects_runtime_creation_boundary(
    label: str,
    utterance: str,
    scene_id: str,
    expectation: str,
) -> None:
    settings = Settings()
    assert settings.host_model_provider != "fake"
    adjudicator = PromptActionPlanStepAdjudicator(_structured_client(settings))
    result = await adjudicator.adjudicate(
        await _cemetery_context(utterance, scene_id=scene_id)
    )
    effects = [effect.type for effect in result.success_effects]
    print(
        json.dumps(
            {
                "label": label,
                "target": {"kind": result.target.kind, "id": result.target.id},
                "summary": result.summary,
                "persistence_intent": result.persistence_intent,
                "effects": [effect.model_dump(mode="json") for effect in result.success_effects],
            },
            ensure_ascii=False,
        )
    )

    if expectation == "existing_entity":
        assert result.target.id == "study_window"
        assert "ensure_runtime_entity" not in effects
    elif expectation == "ordinary_item":
        assert effects[:2] == ["ensure_runtime_entity", "move_entity"]
        assert result.persistence_intent == "inventory"
        assert result.target.kind == "location"
        assert result.target.id == scene_id
    elif expectation == "unsafe_item":
        assert "ensure_runtime_entity" not in effects
    elif expectation == "secret_location":
        assert "ensure_runtime_location" not in effects
        assert "enter_location" not in effects
    else:  # pragma: no cover - CASES are static and exhaustive.
        raise AssertionError(f"unknown expectation: {expectation}")
