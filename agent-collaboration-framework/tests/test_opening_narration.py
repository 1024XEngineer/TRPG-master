"""Opening context privacy, fallback rendering, and output-policy tests."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from collaboration_framework.contracts import (
    ActorResourceView,
    ActorValueView,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleActorView,
)
from collaboration_framework.host.application import (
    ContextAssembler,
    OpeningNarrationValidationError,
    OpeningNarrator,
    deterministic_opening_narration,
    narration_subject_rejection_reason,
)
from collaboration_framework.host.schemas import (
    OpeningNarrationContext,
    OpeningParticipant,
    OpeningSceneContext,
)


class CandidateOpeningModel:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def generate(self, context: OpeningNarrationContext):
        del context
        return self.payload


def player_view(*, multiplayer: bool) -> PlayerView:
    return PlayerView(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        background="1920 年代的阿卡姆，调查员受邀查看一座旧宅。",
        scene_id="foyer",
        phase="playing",
        revision="revision-1",
        self_actor=SelfActorView(
            id="actor-1",
            name="杜明",
            occupation="记者",
            attributes=(ActorValueView(id="str", name="力量", value=55),),
            skills=(ActorValueView(id="spot", name="侦查", value=60),),
            resources=(ActorResourceView(id="hp", name="生命", value=10),),
            equipment=("相机",),
            background_summary="杜明曾在这座旧宅附近度过童年。",
            public_status_summary="衣角沾着雨水。",
        ),
        scene=SceneView(
            id="foyer",
            name="旧宅门厅",
            description="昏黄灯光落在积灰的木地板上。",
            time="深夜",
            visible_actors=(
                (
                    VisibleActorView(
                        id="actor-2",
                        name="林夏",
                        occupation="医生",
                        status_summary="提着急救箱。",
                    ),
                )
                if multiplayer
                else ()
            ),
        ),
    )


class OpeningContextTests(unittest.TestCase):
    def test_solo_context_contains_only_player_safe_identity_and_background(
        self,
    ) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=False))

        self.assertEqual(context.participants[0].name, "杜明")
        self.assertEqual(context.participants[0].occupation, "记者")
        self.assertEqual(context.participants[0].status_summary, "衣角沾着雨水。")
        self.assertIn("旧宅附近", context.solo_background_summary)

    def test_multiplayer_context_contains_all_public_identities_and_no_private_data(
        self,
    ) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=True))
        encoded = context.model_dump_json()

        self.assertEqual(
            [
                (item.name, item.occupation, item.status_summary)
                for item in context.participants
            ],
            [
                ("杜明", "记者", "衣角沾着雨水。"),
                ("林夏", "医生", "提着急救箱。"),
            ],
        )
        self.assertEqual(context.solo_background_summary, "")
        for private_value in (
            "旧宅附近度过童年",
            "力量",
            "侦查",
            "生命",
            "相机",
            "attributes",
            "skills",
            "resources",
            "equipment",
            "known_information",
            "checkpoint_options",
        ):
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value, encoded)

    def test_context_rejects_duplicate_actors_and_multiplayer_solo_background(
        self,
    ) -> None:
        participant = OpeningParticipant(actor_id="same", name="杜明")
        with self.assertRaises(ValidationError):
            OpeningNarrationContext(
                background="公开背景",
                scene=OpeningSceneContext(id="foyer", name="门厅", description=""),
                participants=(participant, participant),
            )
        with self.assertRaises(ValidationError):
            OpeningNarrationContext(
                background="公开背景",
                scene=OpeningSceneContext(id="foyer", name="门厅", description=""),
                participants=(
                    participant,
                    OpeningParticipant(actor_id="other", name="林夏"),
                ),
                solo_background_summary="不应进入多人上下文",
            )


class OpeningNarratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_valid_public_opening(self) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=True))
        output = await OpeningNarrator(
            CandidateOpeningModel(
                {
                    "kind": "narration",
                    "text": "杜明与林夏一同站在旧宅门厅的昏黄灯光下。",
                    "claimed_fact_ids": [],
                    "suggested_actions": [],
                }
            )
        ).narrate(context)
        self.assertIn("杜明", output.text)
        self.assertIn("林夏", output.text)

    async def test_rejects_non_narration_claims_suggestions_protocol_and_missing_name(
        self,
    ) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=True))
        candidates = (
            {
                "kind": "clarification",
                "text": "杜明与林夏要做什么？",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            },
            {
                "kind": "narration",
                "text": "杜明与林夏站在门厅。",
                "claimed_fact_ids": ["invented"],
                "suggested_actions": [],
            },
            {
                "kind": "narration",
                "text": "杜明与林夏站在门厅。",
                "claimed_fact_ids": [],
                "suggested_actions": ["检查门厅"],
            },
            {
                "kind": "narration",
                "text": '杜明与林夏站在门厅。\n"kind": "narration"',
                "claimed_fact_ids": [],
                "suggested_actions": [],
            },
            {
                "kind": "narration",
                "text": "杜明独自站在门厅。",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            },
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(OpeningNarrationValidationError):
                    await OpeningNarrator(CandidateOpeningModel(candidate)).narrate(
                        context
                    )

    def test_deterministic_opening_mentions_scene_and_every_participant(self) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=True))
        text = deterministic_opening_narration(context).text

        for expected in ("旧宅门厅", "昏黄灯光", "杜明", "记者", "林夏", "医生"):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_named_actor_opening_fallback_omits_second_person_scene_description(
        self,
    ) -> None:
        context = OpeningNarrationContext(
            background="1920 年代的阿卡姆。",
            scene=OpeningSceneContext(
                id="kimball-house-outside",
                name="金博尔宅外",
                description="夜色笼罩着金博尔宅与通往公墓的道路，你可以在阴影中观察周围动静。",
            ),
            participants=(
                OpeningParticipant(actor_id="actor-1", name="陈探员", occupation="警探"),
                OpeningParticipant(actor_id="actor-2", name="杜明", occupation="记者"),
            ),
            addressing_mode="named_actor",
        )
        text = deterministic_opening_narration(context).text

        self.assertIn("金博尔宅外", text)
        self.assertIn("陈探员", text)
        self.assertIn("杜明", text)
        self.assertNotIn("你可以在阴影中观察周围动静", text)
        self.assertIsNone(
            narration_subject_rejection_reason(text, addressing_mode="named_actor")
        )

    def test_second_person_opening_fallback_keeps_scene_description(self) -> None:
        context = OpeningNarrationContext(
            background="1920 年代的阿卡姆。",
            scene=OpeningSceneContext(
                id="kimball-house-outside",
                name="金博尔宅外",
                description="夜色笼罩着金博尔宅与通往公墓的道路，你可以在阴影中观察周围动静。",
            ),
            participants=(
                OpeningParticipant(actor_id="actor-1", name="陈探员", occupation="警探"),
            ),
            addressing_mode="second_person",
        )
        text = deterministic_opening_narration(context).text

        self.assertIn("你可以在阴影中观察周围动静", text)
