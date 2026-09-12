"""Valid authored modules and public Engine commands for sanity scenarios."""

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
    SubmitAdjudicationRequest,
    RuleSpecV3,
)
from collaboration_framework.engine import (
    ActorResources,
    DiceRoller,
    InMemoryEngineStore,
    AdjudicationEngineService,
    SequenceDiceSource,
)
from tests.test_projection_v3 import ACTOR, PLAYER, ROOM, game_state, module


def sandbox_content(*, parameters=None, effects=None):
    content = module()
    if parameters and ("habit_cap" in parameters or "sanity_source" in parameters):
        from collaboration_framework.contracts.sanity import SanitySource
        parameters = {**parameters, "sanity_source": "test.creature"}
        content = content.model_copy(update={"sanity_sources": (SanitySource(id="test.creature", habit_cap=parameters.get("habit_cap")),)})
    rule = next(
        r for r in content.rules if r.id == "first_sight_of_douglas"
    ).to_json_dict()
    rule["id"] = "test_sanity"
    rule["trigger"]["when"] = {
        "op": "predicate",
        "predicate": "entity_state_is",
        "args": {
            "entity_id": "cemetery_figure",
            "key": "true_form_seen",
            "value": True,
        },
    }
    rule["execution"]["branches"][0]["entry_step_id"] = (
        "san_check" if effects is None else "effect_0"
    )
    if effects is None:
        rule["execution"]["steps"] = rule["execution"]["steps"][1:]
        rule["execution"]["steps"][0]["check"]["parameters"] = parameters or {
            "success_loss": "0",
            "failure_loss": "1d6",
        }
    else:
        rule["execution"]["steps"] = [
            {
                "id": f"effect_{i}",
                "kind": "effect",
                "effect": effect.to_json_dict(),
                "next_step_id": f"effect_{i + 1}" if i + 1 < len(effects) else "finish",
            }
            for i, effect in enumerate(effects)
        ] + [{"id": "finish", "kind": "finish"}]
    return content.model_copy(update={"rules": (RuleSpecV3.model_validate(rule),)})


def make_store(content=None, *, san=60, before_commit=None):
    content = content or sandbox_content()
    state = game_state(content)
    actor = state.actors[ACTOR]
    state.actors[ACTOR] = actor.model_copy(
        update={
            "resources": ActorResources(hp=10, san=san, mp=10, luck=50, mythos=0),
            "state": {**actor.state, "attributes": {"INT": 70, "STR": 45}},
        }
    )
    store = InMemoryEngineStore(before_commit=before_commit)
    store.register_room(module_content=content, initial_state=state)
    return store


def trigger(revision, request_id="trigger"):
    return SubmitAdjudicationRequest(
        room_id=ROOM,
        player_id=PLAYER,
        adjudication=ActionAdjudication(
            request_id=request_id,
            source_revision=revision,
            actor_id=ACTOR,
            summary="观察真容",
            target=ActionTarget(kind="entity", id="cemetery_figure"),
            method=ActionMethod(family="observe", description="观察"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="cemetery_figure", key="true_form_seen", value=True
                ),
            ),
        ),
    )


async def roll_sanity(store, *, roll=81, request_id="trigger"):
    async with store.transaction(ROOM) as tx:
        runtime = await tx.load_runtime()
    result = await AdjudicationEngineService(store).submit(
        trigger(runtime.revision, request_id)
    )
    decision = result.pending_decision
    assert decision is not None
    result = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([roll]))
    ).decide(
        CheckDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id=request_id + "-roll",
            source_revision=result.view_revision,
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            choice=SelectCheckChoice(candidate_id=decision.options[0].candidate_id),
        )
    )
    check = result.check_run
    assert check is not None
    return PostRollDecisionRequest(
        room_id=ROOM,
        player_id=PLAYER,
        request_id=request_id + "-accept",
        source_revision=result.view_revision,
        check_id=check.check_id,
        check_version=check.version,
        option_id="accept-current",
    )


async def settle(store, *, dice=(4,), roll=81, request_id="trigger"):
    request = await roll_sanity(store, roll=roll, request_id=request_id)
    result = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource(dice))
    ).decide_post_roll(request)
    return result
