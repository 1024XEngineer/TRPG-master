"""The effect registry's structural guarantees (issue #347 Phase 2).

`engine/adjudication.py` used to answer four separate questions about an
effect type in four unrelated `isinstance` chains, and nothing noticed when
one of them missed a type. These tests pin the guarantee that replaced that:
one registration per effect type, complete, or the suite fails.
"""

from __future__ import annotations

import typing
import unittest

from collaboration_framework.contracts import ActionEffect
from collaboration_framework.registry import effects as effect_registry


def effect_type_names() -> set[str]:
    """Every `type` literal in the ActionEffect discriminated union."""

    annotated_args = typing.get_args(ActionEffect)
    variants = typing.get_args(annotated_args[0])
    return {variant.model_fields["type"].default for variant in variants}


class RegistryCompletenessTests(unittest.TestCase):
    def test_every_effect_type_is_registered(self) -> None:
        """A new effect type with no registration must break the build.

        This is the mechanism issue #347 §6 asks for: adding an effect type is
        one registration, and forgetting it is caught here rather than showing
        up as a silent runtime no-op.
        """

        self.assertEqual(effect_type_names(), set(effect_registry.EFFECTS))

    def test_no_registration_exists_for_an_unknown_type(self) -> None:
        self.assertNotIn("made_up_effect", effect_registry.EFFECTS)

    def test_every_registration_can_apply_and_classify(self) -> None:
        for name, registration in effect_registry.EFFECTS.items():
            with self.subTest(effect=name):
                self.assertTrue(callable(registration.authority))
                self.assertTrue(callable(registration.apply))
                self.assertTrue(callable(registration.target_ref))


class AccessDeclarationTests(unittest.TestCase):
    """The reads/writes declarations from #347 §4.4."""

    def test_declared_fields_exist_on_their_effect_type(self) -> None:
        variants = {
            variant.model_fields["type"].default: variant
            for variant in typing.get_args(typing.get_args(ActionEffect)[0])
        }
        for name, registration in effect_registry.EFFECTS.items():
            model = variants[name]
            refs = registration.reads + registration.writes + registration.must_not_exist
            for ref in refs:
                with self.subTest(effect=name, field=ref.field):
                    self.assertIn(
                        ref.field,
                        model.model_fields,
                        f"{name} declares a {ref.field} it does not have",
                    )

    def test_runtime_creators_declare_their_own_id_as_must_not_exist(self) -> None:
        """`ensure_runtime_*` name an id that must NOT already exist.

        That is neither a read nor a write of an existing vocabulary entry, so
        #347 §4.4 gives it its own declaration rather than overloading either.
        """

        for name, own_field in (
            ("ensure_runtime_location", "location_id"),
            ("ensure_runtime_entity", "entity_id"),
        ):
            with self.subTest(effect=name):
                registration = effect_registry.EFFECTS[name]
                self.assertEqual(
                    [ref.field for ref in registration.must_not_exist],
                    [own_field],
                )
                self.assertEqual(
                    [ref.field for ref in registration.writes],
                    [own_field],
                )

    def test_only_runtime_creators_introduce_new_ids(self) -> None:
        creators = {
            name
            for name, registration in effect_registry.EFFECTS.items()
            if registration.writes
        }
        self.assertEqual(
            creators, {"ensure_runtime_location", "ensure_runtime_entity"}
        )


class NoOpValidationIsExplicitTests(unittest.TestCase):
    """Three effect types genuinely have nothing to validate.

    Before the registry they were the types with no `elif` branch, so "passes
    validation" and "someone forgot to write the branch" looked identical.
    They now say so explicitly, and this test is what keeps that a decision
    rather than an omission.
    """

    def test_types_without_content_to_check_declare_no_validator(self) -> None:
        for name in ("narrative_only", "mark_core_resolved", "set_ending_availability"):
            with self.subTest(effect=name):
                self.assertIsNone(effect_registry.EFFECTS[name].validate)

    def test_every_other_type_has_a_validator(self) -> None:
        exempt = {"narrative_only", "mark_core_resolved", "set_ending_availability"}
        for name, registration in effect_registry.EFFECTS.items():
            if name in exempt:
                continue
            with self.subTest(effect=name):
                self.assertIsNotNone(registration.validate)


class EntityStorageRoutingTests(unittest.TestCase):
    """`resolve_entity_storage` — the P3 deduplication (#347 §3.3).

    move_entity / change_entity_state / consume_entity each inlined the same
    `state.item_instances.get(...)` check, three copies of one rule. The
    end-to-end consequence (create a runtime object, then take it, in one
    sequence) is covered by
    `test_projection_v3.py::AdjudicationAgainstV3Tests`; this pins the
    extracted helper itself.
    """

    def _state(self, **overrides):
        from collaboration_framework.engine import ActorState, GameState

        base = {
            "room_id": "room",
            "scene_id": "start",
            "actors": {
                "actor": ActorState(
                    player_id="player",
                    name="调查员",
                    source_character_id="character",
                    source_character_version=1,
                )
            },
            "entities": {},
        }
        base.update(overrides)
        return GameState(**base)

    def test_an_id_with_an_item_instance_routes_to_the_versioned_record(self) -> None:
        from collaboration_framework.contracts import (
            ItemComponent,
            ItemCustody,
            ItemDisplay,
            ItemInstance,
        )

        item = ItemInstance(
            id="pebble",
            room_id="room",
            origin="runtime",
            definition_id="pebble",
            display=ItemDisplay(name="一枚普通石子"),
            item_component=ItemComponent(),
            custody=ItemCustody(kind="location", ref_id="library", form="loose"),
            created_event_id="evt_created",
            last_event_id="evt_created",
            updated_revision="1",
        )
        state = self._state(item_instances={"pebble": item})
        self.assertEqual(
            effect_registry.resolve_entity_storage(state, "pebble"), "item_instance"
        )

    def test_an_id_without_one_routes_to_the_generic_record(self) -> None:
        state = self._state(runtime_entities={"librarian": {"kind": "npc"}})
        self.assertEqual(
            effect_registry.resolve_entity_storage(state, "librarian"),
            "generic_entity",
        )

    def test_an_unknown_id_routes_to_the_generic_record(self) -> None:
        # Existence is the vocabulary pass's job, not routing's; an id that got
        # this far is already known to exist.
        self.assertEqual(
            effect_registry.resolve_entity_storage(self._state(), "nothing"),
            "generic_entity",
        )


class EventEmissionTests(unittest.TestCase):
    def test_only_narrative_only_emits_no_event(self) -> None:
        """`event_type` used to be a local variable each branch had to remember
        to set, with a `None` check at the end standing in for "unregistered".
        Which types legitimately record nothing is now declared."""

        silent = {
            name
            for name, registration in effect_registry.EFFECTS.items()
            if not registration.emits_event
        }
        self.assertEqual(silent, {"narrative_only"})


if __name__ == "__main__":
    unittest.main()
