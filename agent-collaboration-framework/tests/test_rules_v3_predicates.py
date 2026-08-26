"""Direct unit coverage for ``rules_v3._evaluate_predicate`` (issue #347 Phase 0).

Every known predicate branch, plus the unknown-name fallback, is exercised here
directly against a minimal ``GameState`` — no module fixture needed. Before this
file existed, none of the four known branches had a direct test; only the
unknown-predicate fallback was covered indirectly via
``test_projection_v3.py::test_an_unregistered_predicate_never_fires_a_rule``.
This is the safety net issue #347 Phase 1 (``registry/predicates.py``) extracts
against, so these assertions must keep passing unchanged after that refactor.
"""

from __future__ import annotations

import unittest

from collaboration_framework.contracts import PredicateCondition
from collaboration_framework.engine import ActorState, GameState
from collaboration_framework.engine.models import WorldTimePoint, WorldTimeState
from collaboration_framework.engine.rules_v3 import _evaluate_predicate

ROOM = "predicate-room"
ACTOR = "predicate-actor"
PLAYER = "predicate-player"


def game_state(**overrides) -> GameState:
    base = {
        "room_id": ROOM,
        "scene_id": "start",
        "actors": {
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
            )
        },
        "entities": {},
    }
    base.update(overrides)
    return GameState(**base)


def predicate(name: str, **args) -> PredicateCondition:
    return PredicateCondition(predicate=name, args=args)


class EntityStateIsTests(unittest.TestCase):
    def test_matches_when_flag_equals_expected_value(self) -> None:
        state = game_state(entities={"door": {"locked": True}})
        condition = predicate("entity_state_is", entity_id="door", key="locked", value=True)
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_mismatched_value_reads_false(self) -> None:
        state = game_state(entities={"door": {"locked": False}})
        condition = predicate("entity_state_is", entity_id="door", key="locked", value=True)
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_missing_key_reads_false_by_default(self) -> None:
        # The docstring on entity_state()/_evaluate_predicate says an absent flag
        # reads as False, which is how authored `== false` conditions are meant
        # to fire on a fresh room. A missing key defaults `value` to True, so the
        # comparison (False == True) must be False.
        state = game_state(entities={"door": {}})
        condition = predicate("entity_state_is", entity_id="door", key="locked")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_missing_key_matches_explicit_false_expectation(self) -> None:
        state = game_state(entities={"door": {}})
        condition = predicate("entity_state_is", entity_id="door", key="locked", value=False)
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_non_string_entity_id_reads_false(self) -> None:
        state = game_state()
        condition = predicate("entity_state_is", entity_id=1, key="locked")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_non_string_key_reads_false(self) -> None:
        state = game_state(entities={"door": {"locked": True}})
        condition = predicate("entity_state_is", entity_id="door", key=1)
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))


class TimeOfDayIsTests(unittest.TestCase):
    def test_default_world_time_is_day(self) -> None:
        state = game_state()  # WorldTimeState default is hour 12 -> "day"
        condition = predicate("time_of_day_is", value="day")
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_default_world_time_does_not_match_night(self) -> None:
        state = game_state()
        condition = predicate("time_of_day_is", value="night")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_night_hour_matches_night(self) -> None:
        state = game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=0, hour_of_day=2),
                current_point_id="hour_02",
            )
        )
        condition = predicate("time_of_day_is", value="night")
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_the_stored_segment_wins_over_the_hour(self) -> None:
        """05:00 声明成 morning 之后，day 谓词在这一点成立（#415 §阶段一）。

        硬编码 06–18 的旧推导会把它判成 night——这是逐点覆盖要解决的事。
        """

        state = game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=0, hour_of_day=5),
                current_point_id="hour_05",
                current_time_segment="morning",
            )
        )

        self.assertTrue(
            _evaluate_predicate(
                predicate("time_of_day_is", value="day"), state=state, actor_id=ACTOR
            )
        )
        self.assertFalse(
            _evaluate_predicate(
                predicate("time_of_day_is", value="night"), state=state, actor_id=ACTOR
            )
        )

    def test_four_segment_values_separate_two_points_that_are_both_night(self) -> None:
        """追书人的 `surveillance_available` 布尔闩就是因为这里区分不开才存在的。

        22:00 与 02:00 都读作 night，粗粒度谓词会在两个点各触发一次；四段值
        让规则说得出「只在凌晨」。
        """

        evening = game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=0, hour_of_day=22),
                current_point_id="hour_22",
                current_time_segment="evening",
            )
        )
        late_night = game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=1, hour_of_day=2),
                current_point_id="hour_02",
                current_time_segment="late_night",
            )
        )
        query = predicate("time_of_day_is", value="late_night")

        self.assertFalse(_evaluate_predicate(query, state=evening, actor_id=ACTOR))
        self.assertTrue(_evaluate_predicate(query, state=late_night, actor_id=ACTOR))
        # 而粗粒度的 night 对两者都成立——既有写法不需要迁移。
        coarse = predicate("time_of_day_is", value="night")
        self.assertTrue(_evaluate_predicate(coarse, state=evening, actor_id=ACTOR))
        self.assertTrue(_evaluate_predicate(coarse, state=late_night, actor_id=ACTOR))

    def test_an_unknown_query_value_reads_false(self) -> None:
        state = game_state()
        condition = predicate("time_of_day_is", value="dusk")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))


class TimePointIsTests(unittest.TestCase):
    """#245 §8 的 CurrentTimePointPredicate（#415 §阶段三）。"""

    def at(self, point_id: str, *, day: int = 0, hour: int = 0) -> GameState:
        return game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=day, hour_of_day=hour),
                current_point_id=point_id,
            )
        )

    def test_matches_only_the_exact_declared_point(self) -> None:
        state = self.at("hour_20", hour=20)

        self.assertTrue(
            _evaluate_predicate(
                predicate("time_point_is", value="hour_20"), state=state, actor_id=ACTOR
            )
        )
        # hour_18 与 hour_20 同为 evening，粗粒度谓词分不开，这个谓词分得开。
        self.assertFalse(
            _evaluate_predicate(
                predicate("time_point_is", value="hour_18"), state=state, actor_id=ACTOR
            )
        )

    def test_a_missing_or_non_string_value_reads_false(self) -> None:
        state = self.at("hour_20", hour=20)

        self.assertFalse(
            _evaluate_predicate(predicate("time_point_is"), state=state, actor_id=ACTOR)
        )
        self.assertFalse(
            _evaluate_predicate(
                predicate("time_point_is", value=20), state=state, actor_id=ACTOR
            )
        )


class WorldTimeAtLeastTests(unittest.TestCase):
    def at(self, *, day: int, hour: int) -> GameState:
        return game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=day, hour_of_day=hour),
                current_point_id="point",
            )
        )

    def test_compares_on_the_absolute_hour_across_days(self) -> None:
        """跨天由 `absolute_hour` 保证：D1 02:00 晚于 D0 18:00。"""

        query = predicate("world_time_at_least", day_index=1, hour_of_day=0)

        self.assertFalse(
            _evaluate_predicate(query, state=self.at(day=0, hour=18), actor_id=ACTOR)
        )
        self.assertTrue(
            _evaluate_predicate(query, state=self.at(day=1, hour=2), actor_id=ACTOR)
        )

    def test_the_boundary_moment_itself_counts_as_at_least(self) -> None:
        query = predicate("world_time_at_least", day_index=1, hour_of_day=2)

        self.assertTrue(
            _evaluate_predicate(query, state=self.at(day=1, hour=2), actor_id=ACTOR)
        )

    def test_a_non_integer_bound_reads_false(self) -> None:
        state = self.at(day=3, hour=12)

        for args in ({"day_index": "1"}, {"hour_of_day": None}, {"day_index": True}):
            with self.subTest(args=args):
                self.assertFalse(
                    _evaluate_predicate(
                        predicate("world_time_at_least", **args), state=state, actor_id=ACTOR
                    )
                )


class DaysElapsedAtLeastTests(unittest.TestCase):
    def on_day(self, day: int) -> GameState:
        return game_state(
            world_time=WorldTimeState(
                current=WorldTimePoint(day_index=day, hour_of_day=12),
                current_point_id="hour_12",
            )
        )

    def test_opening_day_is_zero(self) -> None:
        """与运行态一致：开局当天是第 0 天，所以「第三天」写作 2。"""

        query = predicate("days_elapsed_at_least", value=2)

        self.assertFalse(_evaluate_predicate(query, state=self.on_day(1), actor_id=ACTOR))
        self.assertTrue(_evaluate_predicate(query, state=self.on_day(2), actor_id=ACTOR))
        self.assertTrue(_evaluate_predicate(query, state=self.on_day(5), actor_id=ACTOR))

    def test_a_non_integer_value_reads_false(self) -> None:
        self.assertFalse(
            _evaluate_predicate(
                predicate("days_elapsed_at_least", value="2"),
                state=self.on_day(5),
                actor_id=ACTOR,
            )
        )


class InformationIsTests(unittest.TestCase):
    def test_party_wide_discovered_fact_matches(self) -> None:
        state = game_state(discovered_facts=("clue_a",))
        condition = predicate("information_is", id="clue_a")
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_actor_scoped_discovered_fact_matches(self) -> None:
        state = game_state(actor_discovered_facts={ACTOR: ("clue_b",)})
        condition = predicate("information_is", id="clue_b")
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_undiscovered_fact_reads_false(self) -> None:
        state = game_state()
        condition = predicate("information_is", id="clue_c")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_another_actors_fact_does_not_leak(self) -> None:
        state = game_state(actor_discovered_facts={"someone-else": ("clue_d",)})
        condition = predicate("information_is", id="clue_d")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_non_string_id_reads_false(self) -> None:
        state = game_state()
        condition = predicate("information_is", id=1)
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))


class PartyLocationIsTests(unittest.TestCase):
    def test_matches_committed_party_location(self) -> None:
        condition = predicate("party_location_is", id="start")
        self.assertTrue(_evaluate_predicate(condition, state=game_state(), actor_id=ACTOR))

    def test_rejects_other_or_malformed_location(self) -> None:
        self.assertFalse(
            _evaluate_predicate(
                predicate("party_location_is", id="outside"),
                state=game_state(),
                actor_id=ACTOR,
            )
        )
        self.assertFalse(
            _evaluate_predicate(
                predicate("party_location_is", id=1),
                state=game_state(),
                actor_id=ACTOR,
            )
        )


class CoreResolvedTests(unittest.TestCase):
    def test_default_args_expect_true_and_matches_resolved_state(self) -> None:
        state = game_state(core_resolved=True)
        condition = predicate("core_resolved")
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_default_args_do_not_match_unresolved_state(self) -> None:
        state = game_state(core_resolved=False)
        condition = predicate("core_resolved")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_explicit_false_matches_unresolved_state(self) -> None:
        state = game_state(core_resolved=False)
        condition = predicate("core_resolved", value=False)
        self.assertTrue(_evaluate_predicate(condition, state=state, actor_id=ACTOR))


class UnknownPredicateFallbackTests(unittest.TestCase):
    def test_unknown_predicate_name_reads_false(self) -> None:
        state = game_state()
        condition = predicate("made_up_predicate", anything="here")
        self.assertFalse(_evaluate_predicate(condition, state=state, actor_id=ACTOR))

    def test_unknown_predicate_name_does_not_raise(self) -> None:
        state = game_state()
        condition = predicate("another_unregistered_name")
        try:
            _evaluate_predicate(condition, state=state, actor_id=ACTOR)
        except Exception as exc:  # pragma: no cover - failure path only
            self.fail(f"unknown predicate must not raise, got {exc!r}")


if __name__ == "__main__":
    unittest.main()
