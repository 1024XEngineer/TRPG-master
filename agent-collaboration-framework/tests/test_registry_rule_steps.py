"""Rule step and world action registries (issue #347 Phases 3 and 4).

These two phases are registration-and-static-checking only. The tests that
matter most here are the ones pinning what must *not* have changed:
`invoke_ruleset_action` still has no executor, and a module using it still
publishes.
"""

from __future__ import annotations

import typing
import unittest

from collaboration_framework.contracts.module_v3 import RuleStepSpec
from collaboration_framework.registry import rule_steps as rule_step_registry
from collaboration_framework.registry import world_actions as world_action_registry

SUSPENDING_KINDS = {
    "check",
    "adjudicated_check",
    "presentation",
    "await_player_input",
    "invoke_ruleset_action",
    "create_npc_action_opportunity",
    "create_time_task",
    "cancel_time_task",
}


def step_kind_names() -> set[str]:
    variants = typing.get_args(typing.get_args(RuleStepSpec)[0])
    return {variant.model_fields["kind"].default for variant in variants}


class RegistryCompletenessTests(unittest.TestCase):
    def test_every_step_kind_is_registered(self) -> None:
        """A kind added to the union but missed here must break the build —
        the failure mode that used to slip through four separate dispatch
        sites."""

        self.assertEqual(step_kind_names(), set(rule_step_registry.STEP_KINDS))

    def test_exactly_two_kinds_drive_the_walk(self) -> None:
        behaviors: dict[str, set[str]] = {}
        for kind, registration in rule_step_registry.STEP_KINDS.items():
            behaviors.setdefault(registration.walk_behavior, set()).add(kind)
        self.assertEqual(behaviors["terminal"], {"finish"})
        self.assertEqual(behaviors["produces_effect_and_continues"], {"effect"})
        self.assertEqual(behaviors["suspends"], SUSPENDING_KINDS)


class AgendaStatusTests(unittest.TestCase):
    def test_simple_kinds_map_to_their_boundary(self) -> None:
        for kind, expected in (
            ("adjudicated_check", "awaiting_active_check"),
            ("presentation", "awaiting_presentation"),
            ("await_player_input", "awaiting_player_input"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    rule_step_registry.agenda_status_for(kind, None), expected
                )

    def test_kinds_without_a_worker_report_running(self) -> None:
        """These four park on the Agenda with nothing to resume them. That was
        true before the registry and must stay true after it."""

        for kind in (
            "invoke_ruleset_action",
            "create_npc_action_opportunity",
            "create_time_task",
            "cancel_time_task",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    rule_step_registry.agenda_status_for(kind, None), "running"
                )

    def test_check_splits_on_its_own_initiation_kind(self) -> None:
        from collaboration_framework.contracts.module_v3 import CheckStep, RuleCheckSpec

        def check_step(initiation_kind: str) -> CheckStep:
            return CheckStep(
                id="s1",
                check=RuleCheckSpec(
                    profile_id="p",
                    actor_binding="actor",
                    initiation_kind=initiation_kind,
                ),
                result_routes={"regular_success": "s2"},
            )

        self.assertEqual(
            rule_step_registry.agenda_status_for("check", check_step("passive_rule")),
            "awaiting_passive_check",
        )
        self.assertEqual(
            rule_step_registry.agenda_status_for("check", check_step("active_action")),
            "awaiting_active_check",
        )

    def test_an_unregistered_kind_reports_running(self) -> None:
        self.assertEqual(
            rule_step_registry.agenda_status_for("made_up_kind", None), "running"
        )


class ActorBindingTests(unittest.TestCase):
    def test_the_value_every_authored_module_uses_is_registered(self) -> None:
        self.assertTrue(rule_step_registry.is_registered_actor_binding("actor"))

    def test_unknown_bindings_are_not_registered(self) -> None:
        self.assertFalse(rule_step_registry.is_registered_actor_binding("everyone"))

    def test_the_value_space_mirrors_binding_slot_source(self) -> None:
        """`BindingSlotSpec.source` already enumerates this same concept for
        agent_match triggers; the two must not drift apart."""

        from collaboration_framework.contracts.module_v3 import BindingSlotSpec

        source_values = set(
            typing.get_args(BindingSlotSpec.model_fields["source"].annotation)
        )
        self.assertEqual(rule_step_registry.ACTOR_BINDINGS, frozenset(source_values))


class WorldActionRegistryTests(unittest.TestCase):
    def test_the_table_is_empty(self) -> None:
        """Empty is the correct state, not an unfinished one — see the module
        docstring. This test exists so that adding a name is a deliberate act
        that has to update it."""

        self.assertEqual(world_action_registry.SUPPORTED_WORLD_ACTIONS, frozenset())

    def test_no_action_id_is_currently_executable(self) -> None:
        for action_id in ("coc7e.sanity_check", "attack", "anything"):
            with self.subTest(action_id=action_id):
                self.assertFalse(world_action_registry.is_registered(action_id))

    def test_v2_force_action_names_were_not_migrated_in(self) -> None:
        """`engine/capabilities.py` still carries v2's `_SUPPORTED_FORCE_ACTIONS`.
        Those belong to a runtime that no longer exists; migrating them here
        would claim v3 capabilities nothing implements."""

        from collaboration_framework.engine.capabilities import _SUPPORTED_FORCE_ACTIONS

        for action in _SUPPORTED_FORCE_ACTIONS:
            with self.subTest(action=action):
                self.assertFalse(world_action_registry.is_registered(action))


if __name__ == "__main__":
    unittest.main()
