"""World-scoped ruleset adapter registry tests (#485 PR 1)."""

from __future__ import annotations

import unittest

from collaboration_framework.registry import rulesets
from collaboration_framework.registry.check_profiles import COC7_CHECK_PROFILES


class RulesetAdapterRegistryTests(unittest.TestCase):
    def test_coc7_adapter_owns_the_existing_sanity_profile(self) -> None:
        adapter = rulesets.require_adapter("coc-7e")

        self.assertEqual(adapter.check_profiles, COC7_CHECK_PROFILES)
        self.assertIs(
            rulesets.check_profile_for("coc-7e", "coc7.sanity"),
            COC7_CHECK_PROFILES["coc7.sanity"],
        )

    def test_capabilities_are_scoped_to_world_ref(self) -> None:
        self.assertIsNotNone(rulesets.check_profile_for("coc-7e", "coc7.sanity"))
        self.assertIsNone(rulesets.check_profile_for("other-world", "coc7.sanity"))
        self.assertIsNone(
            rulesets.check_profile_for("coc-7e", "profile-with-a-collision")
        )

    def test_future_capability_tables_are_empty_until_their_executors_exist(self) -> None:
        adapter = rulesets.require_adapter("coc-7e")

        self.assertEqual(adapter.check_outcome_handlers, {})
        self.assertEqual(adapter.world_actions, {})
        self.assertIsNone(
            rulesets.check_outcome_handler_for("coc-7e", "coc7.sanity")
        )
        self.assertIsNone(rulesets.world_action_for("coc-7e", "coc7.apply_condition"))

    def test_unknown_world_has_an_explicit_failure_path(self) -> None:
        self.assertFalse(rulesets.is_registered("other-world"))
        with self.assertRaisesRegex(
            rulesets.RulesetRegistryError,
            "no ruleset adapter.*other-world",
        ):
            rulesets.require_adapter("other-world")

    def test_registry_rejects_duplicate_world_refs(self) -> None:
        adapter = rulesets.RulesetAdapter(world_ref="duplicate")

        with self.assertRaisesRegex(ValueError, "duplicate ruleset adapter"):
            rulesets.RulesetAdapterRegistry((adapter, adapter))

    def test_adapter_catalogues_are_immutable(self) -> None:
        adapter = rulesets.require_adapter("coc-7e")

        with self.assertRaises(TypeError):
            adapter.check_profiles["new.profile"] = COC7_CHECK_PROFILES["coc7.sanity"]


if __name__ == "__main__":
    unittest.main()
