"""Rule step and world action registries (issue #347 Phases 3 and 4).

These two phases are registration-and-static-checking only. The tests that
matter most here are the ones pinning what must *not* have changed:
`invoke_ruleset_action` is executable only when its world action is registered,
and unknown action ids still fail explicitly at runtime.
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
    "create_npc_action_opportunity",
}

# 就地做完然后接着往下走的 kind。它们和 `effect` 是同一类行为，只是待提交的
# 东西不是 `step.effect` 而是步骤自身——目标时间要等到提交那一刻才解析得出来
# （#415 §阶段四）。
SCHEDULING_KINDS = {"create_time_task", "cancel_time_task"}


def step_kind_names() -> set[str]:
    variants = typing.get_args(typing.get_args(RuleStepSpec)[0])
    return {variant.model_fields["kind"].default for variant in variants}


class RegistryCompletenessTests(unittest.TestCase):
    def test_every_step_kind_is_registered(self) -> None:
        """A kind added to the union but missed here must break the build —
        the failure mode that used to slip through four separate dispatch
        sites."""

        self.assertEqual(step_kind_names(), set(rule_step_registry.STEP_KINDS))

    def test_only_the_registered_kinds_drive_the_walk(self) -> None:
        behaviors: dict[str, set[str]] = {}
        for kind, registration in rule_step_registry.STEP_KINDS.items():
            behaviors.setdefault(registration.walk_behavior, set()).add(kind)
        self.assertEqual(behaviors["terminal"], {"finish"})
        self.assertEqual(
            behaviors["produces_effect_and_continues"],
            {"effect", "invoke_ruleset_action"},
        )
        self.assertEqual(
            behaviors["schedules_time_task_and_continues"], SCHEDULING_KINDS
        )
        self.assertEqual(behaviors["suspends"], SUSPENDING_KINDS)

    def test_the_two_time_task_kinds_no_longer_park_the_agenda(self) -> None:
        """#415 §阶段四 给了它们执行器，所以不再是「无人推进的挂起点」。"""

        for kind in SCHEDULING_KINDS:
            with self.subTest(kind=kind):
                registration = rule_step_registry.STEP_KINDS[kind]
                self.assertIsNone(registration.agenda_status)
                self.assertIsNone(registration.failure_code)


class AgendaStatusTests(unittest.TestCase):
    def test_simple_kinds_map_to_their_boundary(self) -> None:
        self.assertEqual(
            rule_step_registry.agenda_status_for("adjudicated_check", None),
            "awaiting_active_check",
        )

    def test_kinds_without_a_worker_fail_instead_of_hanging(self) -> None:
        """These four park on the Agenda with nothing to resume them.

        Until #398 they reported `running`, which is exactly what a kind that
        *does* have a worker reports while waiting for it — so an Agenda that
        would never move looked identical to one about to. They fail, and
        say why.

        `presentation` and `await_player_input` wore a more specific name for
        the same hang: `awaiting_presentation` and `awaiting_player_input` have
        zero consumers anywhere, so nothing was ever going to advance them
        either (#288 §6 closed `PresentationStep` as not wired).

        `create_time_task` / `cancel_time_task` 曾经也在这份名单上，#415
        §阶段四 给了它们执行器之后移出去了。
        """

        for kind in (
            "presentation",
            "await_player_input",
            "create_npc_action_opportunity",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    rule_step_registry.agenda_status_for(kind, None), "failed"
                )
                self.assertEqual(
                    rule_step_registry.agenda_failure_code_for(kind),
                    rule_step_registry.STEP_KIND_HAS_NO_EXECUTOR,
                )

    def test_kinds_with_a_boundary_carry_no_failure_code(self) -> None:
        for kind in ("check", "adjudicated_check"):
            with self.subTest(kind=kind):
                self.assertIsNone(rule_step_registry.agenda_failure_code_for(kind))

    def test_a_failing_status_always_comes_with_a_code(self) -> None:
        """`failed` without a code silently becomes `resolved` again.

        `_settled_status(None)` reads "the rule chain finished", so a boundary
        that answers `failed` and then hands back `None` re-creates the exact
        silent success #398 exists to remove. The pair is asserted over every
        registered kind — plus `effect` / `finish`, which answer `failed`
        because they have no suspension semantics at all, and which the old
        version of this test happened to leave out — and over an unregistered
        one.
        """

        for kind in (*rule_step_registry.STEP_KINDS, "kind_nobody_registered"):
            with self.subTest(kind=kind):
                status = rule_step_registry.agenda_status_for(kind, None)
                code = rule_step_registry.agenda_failure_code_for(kind)
                self.assertEqual(
                    status == "failed",
                    code is not None,
                    f"{kind}: status={status!r} code={code!r}",
                )

    def test_kinds_that_never_suspend_say_so_when_a_walk_stops_on_them(self) -> None:
        for kind in ("effect", "finish"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    rule_step_registry.agenda_status_for(kind, None), "failed"
                )
                self.assertEqual(
                    rule_step_registry.agenda_failure_code_for(kind),
                    rule_step_registry.STEP_KIND_CANNOT_SUSPEND,
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

    def test_an_unregistered_kind_fails(self) -> None:
        """Publish-time validation rejects kinds outside the union, so reaching
        one here means the graph outran the Engine — and a kind nobody
        registered has, by definition, no executor."""

        self.assertEqual(
            rule_step_registry.agenda_status_for("made_up_kind", None), "failed"
        )
        self.assertEqual(
            rule_step_registry.agenda_failure_code_for("made_up_kind"),
            rule_step_registry.UNREGISTERED_STEP_KIND,
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
    def test_the_table_contains_the_executable_condition_action(self) -> None:

        self.assertEqual(
            world_action_registry.SUPPORTED_WORLD_ACTIONS,
            frozenset({"coc7.apply_condition"}),
        )

    def test_no_action_id_is_currently_executable(self) -> None:
        self.assertTrue(world_action_registry.is_registered("coc7.apply_condition"))
        for action_id in ("coc7e.sanity_check", "attack", "anything"):
            with self.subTest(action_id=action_id):
                self.assertFalse(world_action_registry.is_registered(action_id))


if __name__ == "__main__":
    unittest.main()
