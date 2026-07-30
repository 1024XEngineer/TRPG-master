from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from collaboration_framework.contracts import (
    ActionDeclarationOption,
    ActorResourceView,
    ActorValueView,
    AvailableExitView,
    CheckpointOption,
    ContractError,
    ExitDestinationView,
    MatchedTarget,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleEntity,
)
from collaboration_framework.host.application import (
    REFERENCE_MODULE_ACTIONS,
    IntentParser,
)
from collaboration_framework.host.schemas import IntentContext, RecentTurnContext

ROOT = Path(__file__).resolve().parents[1]
MODULE_EXAMPLES = ROOT / "docs" / "module-parser" / "examples"


def context(
    *,
    utterance: str,
    checkpoint_options: tuple[CheckpointOption, ...] = (),
) -> IntentContext:
    player_input = PlayerInput(
        room_id="room",
        player_id="player",
        actor_id="actor",
        client_action_id="action",
        utterance=utterance,
    )
    player_view = PlayerView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        background="玩家可见的测试背景。",
        scene_id="study",
        phase="playing",
        revision="1",
        self_actor=SelfActorView(
            id=player_input.actor_id,
            name="调查员",
            attributes=(
                ActorValueView(id="STR", name="力量", value=55),
                ActorValueView(id="FLOAT", name="浮点属性", value=42.5),
            ),
            skills=(
                ActorValueView(id="track", name="追踪", value=60),
                ActorValueView(
                    id="fighting-brawl",
                    name="格斗（斗殴）",
                    value=50,
                ),
            ),
            resources=(
                ActorResourceView(id="luck", name="幸运", value=45),
                ActorResourceView(id="san", name="理智", value=60),
            ),
        ),
        scene=SceneView(
            id="study",
            name="书房",
            description="书房里有一道墓穴入口。",
            visible_entities=(
                VisibleEntity(
                    id="crypt_entrance",
                    kind="location",
                    name="墓穴入口",
                    description="入口深处漆黑一片。",
                ),
                VisibleEntity(
                    id="figure",
                    kind="npc",
                    name="黑影",
                    description="一个模糊的人影。",
                ),
            ),
            available_exits=(
                AvailableExitView(
                    id="library",
                    name="书房外的图书馆",
                    aliases=("书房外",),
                    destination=ExitDestinationView(
                        scene_id="library",
                        name="图书馆",
                    ),
                ),
            ),
        ),
        checkpoint_options=checkpoint_options,
    )
    return IntentContext(
        player_input=player_input,
        player_view=player_view,
        recent_history=RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
        ),
    )


def raw_intent(
    *,
    verb: str,
    target_id: str,
    check: dict[str, object] | None = None,
    declarations: list[str] | None = None,
    initiated_by_target: bool = False,
) -> dict[str, object]:
    return {
        "kind": "action",
        "verb": verb,
        "target": {"matched": True, "id": target_id},
        "check": check or {"route": "none"},
        "declarations": declarations or [],
        "initiated_by_target": initiated_by_target,
        "summary": f"{verb} {target_id}",
    }


def test_exit_travel_is_aligned_to_one_engine_verb() -> None:
    intent = IntentParser.parse(
        raw_intent(
            verb="前往",
            target_id="library",
            initiated_by_target=True,
        ),
        context(utterance="我要前往图书馆"),
    )

    assert intent.kind == "action"
    assert isinstance(intent.target, MatchedTarget)
    assert intent.verb == "go"
    assert intent.initiated_by_target is False


def test_unique_named_exit_recovers_an_unknown_model_target() -> None:
    intent = IntentParser.parse(
        {
            "kind": "unknown",
            "verb": "unknown",
            "target": {"matched": False, "raw": "图书馆"},
            "check": {"route": "none"},
            "summary": "前往图书馆",
            "clarification_question": "你想去哪里？",
        },
        context(utterance="前往图书馆"),
    )

    assert intent.kind == "action"
    assert isinstance(intent.target, MatchedTarget)
    assert intent.target.id == "library"
    assert intent.verb == "go"
    assert intent.clarification_question is None


def test_module_check_uses_trusted_action_hint_instead_of_model_verb() -> None:
    checkpoint = CheckpointOption(
        id="inspect_grave_area",
        target_id="crypt_entrance",
        action_hint="track",
        skills=("track",),
    )
    intent = IntentParser.parse(
        raw_intent(
            verb="查看",
            target_id="crypt_entrance",
            check={
                "route": "module",
                "checkpoint_id": checkpoint.id,
                "proposed_skills": ["track"],
            },
        ),
        context(
            utterance="查看墓穴入口附近有没有足迹",
            checkpoint_options=(checkpoint,),
        ),
    )

    assert intent.verb == "track"
    assert intent.check.route == "module"


@pytest.mark.parametrize(
    ("model_verb", "expected"),
    [
        ("shoot", "attack"),
        ("攻击", "attack"),
        ("rest", "wait"),
        ("time_elapsed", "wait"),
        ("等到夜晚", "wait_until_night"),
        ("观察", "observe"),
        ("查看", "inspect"),
        ("调查", "investigate"),
    ],
)
def test_only_equivalent_engine_actions_are_collapsed(
    model_verb: str,
    expected: str,
) -> None:
    intent = IntentParser.parse(
        raw_intent(verb=model_verb, target_id="figure"),
        context(utterance=f"{model_verb}黑影"),
    )

    assert intent.verb == expected


def test_default_check_requires_an_integer_engine_candidate() -> None:
    with pytest.raises(ContractError, match="至少需要"):
        IntentParser.parse(
            raw_intent(
                verb="inspect",
                target_id="figure",
                check={"route": "default", "proposed_skills": []},
            ),
            context(utterance="仔细检查黑影"),
        )

    with pytest.raises(ContractError, match="整数属性"):
        IntentParser.parse(
            raw_intent(
                verb="inspect",
                target_id="figure",
                check={"route": "default", "proposed_skills": ["FLOAT"]},
            ),
            context(utterance="仔细检查黑影"),
        )

    intent = IntentParser.parse(
        raw_intent(
            verb="search",
            target_id="figure",
            check={"route": "default", "proposed_skills": ["luck"]},
        ),
        context(utterance="碰碰运气搜索黑影"),
    )
    assert intent.check.proposed_skills == ("luck",)


def test_rule_declaration_is_selected_from_current_checkpoint_only() -> None:
    checkpoint = CheckpointOption(
        id="enter_crypt",
        target_id="crypt_entrance",
        action_hint="enter",
        declaration_options=(
            ActionDeclarationOption(
                id="hold_breath",
                semantic_hints=("屏住呼吸", "憋气", "hold breath"),
            ),
        ),
    )
    intent = IntentParser.parse(
        raw_intent(
            verb="进入",
            target_id="crypt_entrance",
            check={
                "route": "module",
                "checkpoint_id": "enter_crypt",
                "proposed_skills": [],
            },
            declarations=["hold_breath"],
        ),
        context(
            utterance="我屏住呼吸进入墓穴入口",
            checkpoint_options=(checkpoint,),
        ),
    )

    assert intent.verb == "enter"
    assert intent.declarations == ("hold_breath",)

    omitted = IntentParser.parse(
        raw_intent(
            verb="进入",
            target_id="crypt_entrance",
            check={
                "route": "module",
                "checkpoint_id": "enter_crypt",
                "proposed_skills": [],
            },
        ),
        context(
            utterance="我屏住呼吸进入墓穴入口",
            checkpoint_options=(checkpoint,),
        ),
    )
    assert omitted.declarations == ()

    with pytest.raises(ContractError, match="当前 Checkpoint"):
        IntentParser.parse(
            raw_intent(
                verb="enter",
                target_id="crypt_entrance",
                check={
                    "route": "module",
                    "checkpoint_id": "enter_crypt",
                    "proposed_skills": [],
                },
                declarations=["cover_nose"],
            ),
            context(
                utterance="我捂住鼻子进入墓穴入口",
                checkpoint_options=(checkpoint,),
            ),
        )


def test_reference_vocabulary_covers_engine_consumed_actions_in_docs() -> None:
    actions: set[str] = set()
    referenced_declarations: set[str] = set()
    declared_options: set[str] = set()
    action_pattern = re.compile(r"""action\.type\s*==\s*['"]([^'"]+)['"]""")
    declaration_pattern = re.compile(
        r"""action\.declares\(\s*['"]([^'"]+)['"]\s*\)"""
    )

    for path in MODULE_EXAMPLES.rglob("module-content*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        actions.update(
            checkpoint["action"] for checkpoint in payload.get("checkpoints", ())
        )
        declared_options.update(
            declaration["id"]
            for checkpoint in payload.get("checkpoints", ())
            for declaration in checkpoint.get("declaration_options", ())
        )
        for entity in payload.get("entities", ()):
            actions.update(entity.get("refuse_ops", ()))
            actions.update((entity.get("direct_responses") or {}).keys())
            for rule in entity.get("rules", ()):
                actions.update(
                    operation["action"]
                    for operation in rule.get("then", ())
                    if operation.get("op") == "allow"
                )
        for rule in payload.get("module_rules", ()):
            actions.update(
                operation["action"]
                for operation in rule.get("then", ())
                if operation.get("op") == "allow"
            )
        encoded = json.dumps(payload, ensure_ascii=False)
        actions.update(action_pattern.findall(encoded))
        referenced_declarations.update(declaration_pattern.findall(encoded))

    assert actions <= REFERENCE_MODULE_ACTIONS
    assert referenced_declarations <= declared_options
