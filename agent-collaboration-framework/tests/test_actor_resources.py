import pytest
from pydantic import TypeAdapter, ValidationError
from collaboration_framework.contracts import ActionEffect
from collaboration_framework.contracts.resources import (
    ChangeActorResourceEffect,
    FixedQuantity,
    DiceQuantity,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    SequenceDiceSource,
)
from tests.sanity_fixtures import make_store, sandbox_content, trigger, ACTOR, ROOM


@pytest.mark.parametrize(
    "resource,before",
    [("hp", 10), ("san", 60), ("mp", 10), ("luck", 50), ("mythos", 0)],
)
@pytest.mark.parametrize("direction,sign", [("increase", 1), ("decrease", -1)])
@pytest.mark.parametrize("random", [False, True])
async def test_authored_resource_effect_executes(
    resource, before, direction, sign, random
):
    effect = ChangeActorResourceEffect(
        resource_id=resource,
        direction=direction,
        quantity=DiceQuantity(count=2, sides=6, bonus=1)
        if random
        else FixedQuantity(value=4),
        reason_code="test.resource",
    )
    store = make_store(sandbox_content(effects=[effect]))
    result = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([2, 1]))
    ).submit(trigger("0"))
    assert result.status == "resolved"
    expected = before + sign * 4
    if resource != "hp":
        expected = max(0, expected)
    assert (
        getattr(store.inspect_state(ROOM).actors[ACTOR].resources, resource) == expected
    )
    event = next(
        e
        for e in store.inspect_domain_events(ROOM)
        if e.type == "actor.resource_changed"
    )
    assert event.payload["requested_delta"] == sign * 4
    assert event.payload["actual_delta"] == expected - before
    assert event.payload["rolls"] == ([2, 1] if random else [])
    replay = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([]))
    ).submit(trigger("0"))
    assert replay.event_refs == result.event_refs


@pytest.mark.parametrize(
    "patch",
    [
        {"resource_id": "gold"},
        {"resource_id": "state.arbitrary"},
        {"actor_id": "other"},
        {"quantity": {"kind": "fixed", "value": True}},
        {"quantity": {"kind": "fixed", "value": -1}},
        {"quantity": {"kind": "dice", "count": 0, "sides": 6}},
        {"quantity": {"kind": "dice", "count": True, "sides": 6}},
        {"quantity": {"kind": "dice", "count": 101, "sides": 6}},
        {"quantity": {"kind": "dice", "count": 1, "sides": 1}},
        {"quantity": {"kind": "dice", "count": 1, "sides": 1001}},
        {"quantity": "1d6+POW"},
    ],
)
def test_closed_effect_contract_rejects_invalid_inputs(patch):
    payload = {
        "type": "change_actor_resource",
        "resource_id": "san",
        "direction": "decrease",
        "quantity": {"kind": "fixed", "value": 1},
        "reason_code": "test",
    }
    with pytest.raises(ValidationError):
        TypeAdapter(ActionEffect).validate_python(payload | patch)
