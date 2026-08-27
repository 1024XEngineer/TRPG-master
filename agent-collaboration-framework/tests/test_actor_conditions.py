from __future__ import annotations

import unittest
from dataclasses import replace

from collaboration_framework.engine.conditions import (
    active_conditions,
    apply_condition,
    consume_condition,
    has_active_condition,
    remove_condition,
)
from collaboration_framework.engine.models import (
    ActorResources,
    ActorState,
    ConditionExpiry,
    GameState,
)
from collaboration_framework.registry import predicates, rulesets


def state() -> GameState:
    return GameState(
        room_id="room",
        scene_id="scene",
        actors={
            "actor": ActorState(
                player_id="player",
                name="Investigator",
                source_character_id="character",
                source_character_version=1,
                resources=ActorResources(san=50),
            )
        },
        entities={},
    )


class ActorConditionTests(unittest.TestCase):
    def test_legacy_strings_are_migrated_and_projected(self) -> None:
        actor = ActorState(
            player_id="player",
            name="Investigator",
            source_character_id="character",
            source_character_version=1,
            conditions=("unconscious",),
        )
        self.assertEqual(actor.conditions, ("unconscious",))
        self.assertEqual(actor.condition_states[0].source, "legacy_snapshot")

    def test_apply_is_idempotent_and_has_structured_expiry(self) -> None:
        first = apply_condition(
            state(),
            actor_id="actor",
            condition_id="unconscious",
            source="coc7.apply_condition",
            application_reason="failed check",
            application_key="rule:step:actor",
            expiry=ConditionExpiry(kind="time_point", reference_id="hour_18"),
        )
        second = apply_condition(
            first.state,
            actor_id="actor",
            condition_id="unconscious",
            source="coc7.apply_condition",
            application_reason="failed check",
            application_key="rule:step:actor",
        )
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(second.state.actors["actor"].conditions, ("unconscious",))
        self.assertEqual(first.condition.expiry.reference_id, "hour_18")
        self.assertTrue(has_active_condition(first.state, "actor", "unconscious"))

    def test_remove_and_consume_close_the_authoritative_record(self) -> None:
        applied = apply_condition(
            state(),
            actor_id="actor",
            condition_id="unconscious",
            source="test",
            application_reason="test",
            application_key="k",
        )
        removed = remove_condition(
            applied.state,
            actor_id="actor",
            condition_id="unconscious",
            reason="woke up",
        )
        self.assertEqual(removed.condition.status, "removed")
        self.assertEqual(active_conditions(removed.state, "actor"), ())

        reapplied = apply_condition(
            removed.state,
            actor_id="actor",
            condition_id="unconscious",
            source="test",
            application_reason="test",
            application_key="k2",
        )
        consumed = consume_condition(
            reapplied.state,
            actor_id="actor",
            condition_id="unconscious",
            reason="condition used",
        )
        self.assertEqual(consumed.condition.status, "consumed")
        self.assertFalse(has_active_condition(consumed.state, "actor", "unconscious"))

    def test_coc7_action_emits_once_and_rejects_unknown_conditions(self) -> None:
        action = rulesets.require_world_action("coc-7e", "coc7.apply_condition")
        context = rulesets.RulesetActionContext(
            state=state(),
            actor_id="actor",
            actor_binding="actor",
            parameters={
                "condition": "unconscious",
                "expiry": {"kind": "time_task", "reference_id": "task-1"},
            },
            request_id="request",
            operation_key="rule:step:actor",
        )
        first = action(context)
        second = action(replace(context, state=first.state))
        self.assertEqual(first.event_type, "actor.condition_applied")
        self.assertIsNone(second.event_type)
        with self.assertRaises(rulesets.RulesetActionError) as raised:
            action(
                replace(context, parameters={"condition": "unknown"})
            )
        self.assertEqual(raised.exception.code, "RULESET_CONDITION_UNKNOWN")

    def test_coc7_action_rebuilds_only_active_condition_projection(self) -> None:
        action = rulesets.require_world_action("coc-7e", "coc7.apply_condition")
        applied = action(
            rulesets.RulesetActionContext(
                state=state(),
                actor_id="actor",
                actor_binding="actor",
                parameters={"condition": "unconscious"},
                request_id="request",
                operation_key="first",
            )
        )
        removed = remove_condition(
            applied.state,
            actor_id="actor",
            condition_id="unconscious",
            reason="woke up",
        )
        reapplied = action(
            rulesets.RulesetActionContext(
                state=removed.state,
                actor_id="actor",
                actor_binding="actor",
                parameters={"condition": "injured_foot"},
                request_id="request",
                operation_key="second",
            )
        )

        actor = reapplied.state.actors["actor"]
        self.assertEqual(actor.conditions, ("injured_foot",))
        self.assertFalse(
            predicates.evaluate(
                "actor_has_condition",
                {"condition_id": "unconscious"},
                state=reapplied.state,
                actor_id="actor",
            )
        )


if __name__ == "__main__":
    unittest.main()
