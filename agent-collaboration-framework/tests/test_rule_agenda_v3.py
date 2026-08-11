"""Durable RuleAgenda ordering, suspension, and lease recovery (#226 §4)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    ModuleContentV3,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    AgendaItem,
    AgendaSource,
    GameState,
    InMemoryEngineStore,
    RevisionConflictError,
    RuleAgenda,
)
from collaboration_framework.engine.rules_v3 import (
    ordered_agenda_items,
    resume_agenda_rule,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
ROOM = "agenda-room"
PLAYER = "agenda-player"
ACTOR = "agenda-actor"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(**updates) -> GameState:
    values = {
        "room_id": ROOM,
        "scene_id": "cemetery",
        "actors": {
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
            )
        },
        "entities": {
            "cemetery_figure": {"true_form_seen": False},
            "case_tracker": {"first_ghoul_sight_resolved": False},
        },
    }
    values.update(updates)
    return GameState(**values)


def agenda(agenda_id: str, event_sequence: int, priority: int) -> RuleAgenda:
    return RuleAgenda(
        agenda_id=agenda_id,
        room_id=ROOM,
        module_id="paper-chase",
        module_version="3.0.0",
        correlation_id=f"correlation-{agenda_id}",
        root_source=AgendaSource(kind="event", id=f"event-{agenda_id}"),
        revision="4",
        current_rule_id=f"rule-{agenda_id}",
        current_branch_id="default",
        current_step_id="invoke",
        queue=(
            AgendaItem(
                source_event_id=f"event-{agenda_id}",
                event_sequence=event_sequence,
                rule_id=f"rule-{agenda_id}",
                rule_priority=priority,
                branch_id="default",
                status="running",
            ),
        ),
    )


class RuleAgendaOrderingTests(unittest.TestCase):
    def test_items_sort_by_event_then_priority_then_rule_id(self) -> None:
        items = (
            AgendaItem(
                source_event_id="event-2",
                event_sequence=2,
                rule_id="rule-a",
                rule_priority=900,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-z",
                rule_priority=20,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-b",
                rule_priority=80,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-a",
                rule_priority=80,
                branch_id="default",
            ),
        )
        ordered = ordered_agenda_items(items)
        self.assertEqual(
            [item.rule_id for item in ordered],
            ["rule-a", "rule-b", "rule-z", "rule-a"],
        )


class RuleAgendaRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_check_suspends_with_effect_and_cursor_in_same_state(
        self,
    ) -> None:
        content = module()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state())
        engine = AdjudicationEngineService(store)

        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="see-ghoul",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="看清墓地里的人影",
                    target=ActionTarget(kind="entity", id="cemetery_figure"),
                    method=ActionMethod(family="observe", description="仔细观察"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="cemetery_figure",
                            key="true_form_seen",
                            value=True,
                        ),
                    ),
                ),
            )
        )

        state = store.inspect_state(ROOM)
        self.assertTrue(state.entities["case_tracker"]["first_ghoul_sight_resolved"])
        self.assertEqual(len(state.rule_agendas), 1)
        persisted = next(iter(state.rule_agendas.values()))
        self.assertEqual(persisted.status, "awaiting_passive_check")
        self.assertEqual(persisted.current_rule_id, "first_sight_of_douglas")
        self.assertEqual(persisted.current_step_id, "san_check")
        self.assertGreater(persisted.step_count, 0)
        resumed_rule, resumed_walk = resume_agenda_rule(persisted, content)
        self.assertEqual(resumed_rule.id, "first_sight_of_douglas")
        self.assertEqual(resumed_walk.suspended_at, "san_check")

    async def test_expired_lease_is_reclaimed_without_replaying_agenda(self) -> None:
        first = agenda("first", event_sequence=1, priority=20)
        second = agenda("second", event_sequence=2, priority=900)
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module(),
            initial_state=game_state(
                rule_agendas={first.agenda_id: first, second.agenda_id: second}
            ),
        )
        now = datetime(2026, 8, 10, tzinfo=UTC)
        claimed = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=5),
        )
        assert claimed is not None
        self.assertEqual(claimed.agenda_id, "first")

        other = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-b",
            now=now,
            lease_expires_at=now + timedelta(seconds=20),
        )
        assert other is not None
        self.assertEqual(other.agenda_id, "second")

        recovered = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-c",
            now=now + timedelta(seconds=6),
            lease_expires_at=now + timedelta(seconds=30),
        )
        assert recovered is not None
        self.assertEqual(recovered.agenda_id, "first")
        self.assertGreater(recovered.lease_version, claimed.lease_version)
        with self.assertRaises(RevisionConflictError):
            await store.checkpoint_rule_agenda(
                agenda=claimed,
                worker_id="worker-a",
                expected_lease_version=claimed.lease_version,
                now=now + timedelta(seconds=6),
            )

        completed = recovered.model_copy(update={"status": "stable"})
        saved = await store.checkpoint_rule_agenda(
            agenda=completed,
            worker_id="worker-c",
            expected_lease_version=recovered.lease_version,
            now=now + timedelta(seconds=7),
        )
        self.assertEqual(saved.status, "stable")
        self.assertIsNone(saved.lease_owner)
