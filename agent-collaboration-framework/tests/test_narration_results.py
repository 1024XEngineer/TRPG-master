"""Committed-result projection, audience boundaries and complete information feedback."""

import pytest

from collaboration_framework.contracts import (
    CheckpointOption,
    CommittedResult,
    KnownInformationView,
    NarrationEvidence,
    ObservableStateView,
    VisibleEntity,
)
from collaboration_framework.engine import AdjudicationEngineService
from collaboration_framework.engine.models import DomainEvent, EngineRuntimeSnapshot
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
)
from tests.test_action_plan_orchestrator import orchestrator, plan, player_input
from tests.test_happy_frog_village_v3_fixture import (
    ACTOR,
    PLAYER,
    ROOM,
    initial_state,
    load_module,
)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("new", True),
        ("old", False),
        ("actor", False),
        ("promoted", True),
        ("initial", False),
        ("initial_actor_promoted", True),
        ("hidden", False),
        ("journal", False),
        ("restricted_recipient", False),
        ("hidden_after", False),
    ],
)
def test_public_information_is_a_delta_for_the_broadcast_audience(case, expected):
    module = load_module()
    fact = next(item for item in module.information if item.id == "james_refuses_home")
    if case in {"initial", "initial_actor_promoted"}:
        fact = fact.model_copy(
            update={
                "discovery": fact.discovery.model_copy(
                    update={
                        "initial": "known",
                        "scope": "actor"
                        if case == "initial_actor_promoted"
                        else "party",
                    }
                )
            }
        )
    if case == "hidden":
        fact = fact.model_copy(
            update={
                "audience": fact.audience.model_copy(
                    update={"player_when_discovered": False}
                )
            }
        )
    if case == "journal":
        fact = fact.model_copy(
            update={
                "presentation": fact.presentation.model_copy(
                    update={"channels": ("journal",)}
                )
            }
        )
    module = module.model_copy(
        update={
            "information": tuple(
                fact if item.id == fact.id else item for item in module.information
            )
        }
    )
    before = initial_state()
    if case == "old":
        before = before.model_copy(
            update={"discovered_facts": (*before.discovered_facts, fact.id)}
        )
    if case == "promoted":
        before = before.model_copy(
            update={"actor_discovered_facts": {ACTOR: (fact.id,)}}
        )
    after = before.model_copy(
        update={"discovered_facts": (*before.discovered_facts, fact.id)}
    )
    if case == "actor":
        after = before.model_copy(
            update={"actor_discovered_facts": {ACTOR: (fact.id,)}}
        )
    if case == "hidden_after":
        after = before
    if case == "restricted_recipient":
        # Acting player sees it, but another bound player must not receive it.
        after = after.model_copy(
            update={
                "actors": {
                    **after.actors,
                    "other": after.actors[ACTOR].model_copy(
                        update={"player_id": "other-player"}
                    ),
                },
                "visibility_overrides": {f"actor:other:information:{fact.id}": False},
            }
        )
    runtime = EngineRuntimeSnapshot(
        module_id=module.module_id,
        module_version=module.version,
        module_content=module,
        game_state=before,
        revision="0",
    )
    events = tuple(
        DomainEvent(
            event_id=f"evt-{i}",
            sequence=i,
            type="information.revealed",
            room_id=ROOM,
            actor_id=ACTOR,
            client_action_id="reveal",
            cause="test",
            payload={
                "information_id": fact.id,
                "scope": "actor" if case == "actor" else "party",
            },
        )
        for i in (1, 2)
    )
    evidence = AdjudicationEngineService._narration_evidence(
        runtime, new_state=after, events=events, player_id=PLAYER, actor_id=ACTOR
    )
    assert bool(evidence) is expected
    if expected:
        assert (
            len(evidence) == 1
        )  # repeated events from one execution do not duplicate prose
        assert evidence[0].ref == "evt-1"
        assert evidence[0].description == fact.player_content
        assert fact.keeper_content not in evidence[0].description


@pytest.mark.asyncio
async def test_literal_information_recovers_refs_and_only_source_spans_get_style_exemption():
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    ref = context.allowed_evidence_refs[0]
    body = "你听见答复：“今晚不能离开；必须等到明天。”"
    fact = NarrationEvidence(
        ref=ref,
        kind="information_revealed",
        subject_id="reply",
        subject_name="离开的条件",
        description=body,
        required_in_narration=True,
    )
    context = context.model_copy(
        update={"narration_evidence": (fact,), "addressing_mode": "named_actor"}
    )
    narrator = ActionPlanNarrator(None)
    for text in [fact.subject_name, body.replace("不能", "可以"), body.split("；")[0]]:
        with pytest.raises(ActionPlanNarrationValidationError, match="安全校验") as exc:
            narrator.validate(context, {"text": text})
        assert exc.value.reason == "required_evidence_missing"
    candidate = {
        "text": body.replace("；", "；\n"),
        "npc_replies": [{"speaker_id": "npc", "text": "..."}],
    }
    output = narrator.validate(context, candidate)
    assert output.claimed_evidence_refs == (ref,)
    with pytest.raises(ActionPlanNarrationValidationError) as exc:
        narrator.validate(context, {**candidate, "text": body + "你继续前进。"})
    assert exc.value.reason == "subject_ownership"
    with pytest.raises(ActionPlanNarrationValidationError) as exc:
        narrator.validate(context, {**candidate, "text": body + "有人喊：“走吧！”"})
    assert exc.value.reason == "npc_dialogue_embedded_in_text"


@pytest.mark.parametrize(
    "event_type,payload,expected",
    [
        (
            "travel.resolved",
            {"destination_id": "room", "path": ["hall", "room"]},
            "room",
        ),
        ("travel.resolved", {"destination_id": "hall", "path": ["hall"]}, None),
        (
            "travel.interrupted",
            {"destination_id": "room", "current_location_id": "hall", "path": ["hall"]},
            None,
        ),
        (
            "travel.interrupted",
            {
                "destination_id": "room",
                "current_location_id": "gate",
                "path": ["hall", "gate"],
            },
            "gate",
        ),
        ("location.entered", {"location_id": "room"}, "room"),
        ("entity.moved", {"entity_id": "companion", "location_id": "room"}, None),
        ("entity.moved", {"entity_id": "key", "holder_actor_id": ACTOR}, "key"),
    ],
)
def test_committed_travel_and_inventory_results_use_actual_effects(
    event_type, payload, expected
):
    from collaboration_framework.engine.persistent_results import (
        committed_results_from_events,
    )

    event = DomainEvent(
        event_id="effect",
        sequence=1,
        type=event_type,
        payload=payload,
        room_id=ROOM,
        actor_id=ACTOR,
        client_action_id="action",
        cause="test",
    )
    results = committed_results_from_events((event,), item_ids=frozenset({"key"}))
    assert [item.target_id for item in results] == (
        [] if expected is None else [expected]
    )
    if results:
        assert results[0].kind == ("inventory" if expected == "key" else "location")


@pytest.mark.asyncio
async def test_confirmed_arrival_requires_place_and_allows_new_scene_atmosphere():
    from collaboration_framework.contracts import CommittedResult
    from collaboration_framework.host.application.narration_policy import (
        narration_atmosphere_rejection_reason,
    )

    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    scene = context.player_view.scene
    prior = "下午的阳光透过庄园会客厅的窗户。人们在桌边等候。"
    text = f"你走进{scene.name}。下午的阳光落在这里的窗台上。"
    assert narration_atmosphere_rejection_reason(text, prior) == "atmosphere_repeat"
    ref = context.allowed_evidence_refs[0]
    step = context.completed_steps[0].model_copy(
        update={
            "committed_results": (
                CommittedResult(kind="location", target_id=scene.id, event_ref=ref),
            )
        }
    )
    context = context.model_copy(
        update={"completed_steps": (step,), "previous_published_narration": prior}
    )
    narrator = ActionPlanNarrator(None)
    assert narrator.validate(context, {"text": text}).text == text
    natural_arrival = "你沿楼梯下楼，回到楼下的大厅。"
    assert (
        narrator.validate(
            context, {"text": natural_arrival, "claimed_evidence_refs": [ref]}
        ).text
        == natural_arrival
    )
    unrelated_ref = context.allowed_evidence_refs[-1]
    assert unrelated_ref != ref
    with pytest.raises(ActionPlanNarrationValidationError) as unrelated:
        narrator.validate(
            context, {"text": natural_arrival, "claimed_evidence_refs": [unrelated_ref]}
        )
    assert unrelated.value.reason == "required_arrival_missing"
    with pytest.raises(ActionPlanNarrationValidationError) as exc:
        narrator.validate(context, {"text": "你停下脚步。"})
    assert exc.value.reason == "required_arrival_missing"
    assert (
        narration_atmosphere_rejection_reason(prior, prior, scene_changed=True)
        == "atmosphere_repeat"
    )


@pytest.mark.parametrize(
    "case,reason",
    [
        ("rewrite", None),
        ("missing_ref", "required_evidence_missing"),
        ("foreign_ref", "evidence_scope"),
        ("wrong_subject", "subject_ownership"),
        ("embedded_dialogue", "npc_dialogue_embedded_in_text"),
    ],
)
@pytest.mark.asyncio
async def test_arrival_accepts_rewritten_information_with_scoped_source_claim(
    case, reason
):
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    ref = context.allowed_evidence_refs[0]
    fact = NarrationEvidence(
        ref=ref,
        kind="information_revealed",
        subject_id="departure",
        subject_name="离开的条件",
        description="你听见答复：“今晚不能离开；必须等到明天。”",
        required_in_narration=True,
    )
    scene = context.player_view.scene
    step = context.completed_steps[0].model_copy(
        update={
            "narration_evidence": (fact,),
            "committed_results": (
                CommittedResult(kind="location", target_id=scene.id, event_ref=ref),
            ),
        }
    )
    context = context.model_copy(
        update={
            "narration_evidence": (fact,),
            "completed_steps": (step, *context.completed_steps[1:]),
            "addressing_mode": "named_actor",
        }
    )
    text = f"调查员走进{scene.name}。答复很明确：明天才可以离开，今晚必须留在这里。"
    refs = [ref]
    replies = []
    if case == "missing_ref":
        refs = []
    elif case == "foreign_ref":
        refs = ["unpublished-event"]
    elif case == "wrong_subject":
        text += "你继续前进。"
    elif case == "embedded_dialogue":
        text += "有人喊：“走吧！”"
        replies = [{"speaker_id": "npc", "text": "..."}]
    candidate = {"text": text, "claimed_evidence_refs": refs, "npc_replies": replies}
    narrator = ActionPlanNarrator(None)
    if reason is not None:
        with pytest.raises(ActionPlanNarrationValidationError) as exc:
            narrator.validate(context, candidate)
        assert exc.value.reason == reason
    else:
        output = narrator.validate(context, candidate)
        assert output.text == text
        assert fact.description not in output.text
        assert output.claimed_evidence_refs == (ref,)


@pytest.mark.asyncio
async def test_narration_prompt_preserves_scene_and_results_without_duplicate_sources():
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    fact = NarrationEvidence(
        ref=context.allowed_evidence_refs[0],
        kind="information_revealed",
        subject_id="departure",
        subject_name="离开的条件",
        description="今晚不能离开，必须等到明天。",
        required_in_narration=True,
    )
    known = KnownInformationView(
        id=fact.subject_id,
        title=fact.subject_name,
        summary="新消息",
        content=fact.description,
        scope="party",
    )
    earlier = known.model_copy(update={"id": "old-fact", "content": "调查员受邀前来。"})
    step = context.completed_steps[0].model_copy(update={"narration_evidence": (fact,)})
    view = context.player_view.model_copy(
        update={
            "known_information": (earlier, known),
            "checkpoint_options": (
                CheckpointOption(
                    id="ask", target_id="npc", action_hint="询问离开的条件"
                ),
            ),
        }
    )
    context = context.model_copy(
        update={
            "player_view": view,
            "completed_steps": (step, *context.completed_steps[1:]),
            "narration_evidence": (fact,),
            "previous_published_narration": "调查员刚离开街道。",
            "forbidden_disclosure_terms": ("未公开秘密",),
        }
    )
    original_json = context.to_json_dict()
    payload = context.to_prompt_dict()
    assert context.to_json_dict() == original_json
    assert payload["player_view"]["scene"] == original_json["player_view"]["scene"]
    assert (
        payload["player_view"]["self_actor"]
        == original_json["player_view"]["self_actor"]
    )
    assert (
        payload["player_view"]["inventory"] == original_json["player_view"]["inventory"]
    )
    assert payload["player_view"]["known_information"] == [earlier.to_json_dict()]
    assert "checkpoint_options" not in payload["player_view"]
    assert "background" not in payload["player_view"]
    assert "forbidden_disclosure_terms" not in payload
    assert payload["narration_evidence"] == [fact.to_json_dict()]
    for compact, full in zip(
        payload["completed_steps"], original_json["completed_steps"], strict=True
    ):
        assert compact == {
            key: value for key, value in full.items() if key != "narration_evidence"
        }
    for key in (
        "background",
        "memories",
        "conversation_summary",
        "previous_published_narration",
        "allowed_evidence_refs",
        "opening_world_time",
        "termination_status",
    ):
        assert payload[key] == original_json[key]


@pytest.mark.asyncio
async def test_narration_prompt_identifies_companions_from_current_public_state():
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    companion = VisibleEntity(
        id="companion",
        kind="npc",
        name="同行者",
        description="公开人物外貌",
        observable_state=(
            ObservableStateView(
                key="accompanying",
                label="随行",
                value=True,
            ),
        ),
    )
    former = companion.model_copy(
        update={
            "id": "former-companion",
            "observable_state": (
                ObservableStateView(
                    key="accompanying",
                    label="随行",
                    value=False,
                ),
            ),
        }
    )
    resident = companion.model_copy(update={"id": "resident", "observable_state": ()})
    malformed = companion.model_copy(
        update={
            "id": "unconfirmed",
            "observable_state": (
                ObservableStateView(
                    key="accompanying",
                    label="随行",
                    value="true",
                ),
            ),
        }
    )
    carried_object = companion.model_copy(update={"id": "object", "kind": "object"})
    view = context.player_view.model_copy(
        update={
            "scene": context.player_view.scene.model_copy(
                update={
                    "visible_entities": (
                        companion,
                        former,
                        resident,
                        malformed,
                        carried_object,
                    ),
                }
            ),
        }
    )
    context = context.model_copy(update={"player_view": view})
    original_json = context.to_json_dict()
    payload = context.to_prompt_dict()
    assert payload["accompanying_npcs"] == [{"id": "companion", "name": "同行者"}]
    assert payload["player_view"]["scene"] == original_json["player_view"]["scene"]
    assert context.to_json_dict() == original_json

    # Losing public visibility or ending the relation removes the hint even if
    # earlier prose still says the character followed the party.
    context = context.model_copy(
        update={
            "previous_published_narration": "同行者和你一起离开了大厅。",
            "player_view": view.model_copy(
                update={
                    "scene": view.scene.model_copy(
                        update={"visible_entities": (former, resident)}
                    ),
                }
            ),
        }
    )
    assert context.to_prompt_dict()["accompanying_npcs"] == []
