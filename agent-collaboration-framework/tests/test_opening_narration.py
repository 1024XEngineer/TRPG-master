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

    def test_authored_prompt_keeps_scene_constraints_and_omits_unrelated_context(self):
        view = player_view(multiplayer=False)
        view = view.model_copy(
            update={
                "self_actor": view.self_actor.model_copy(
                    update={
                        "public_status_summary": "失明，双手被绳索捆住。",
                    }
                ),
            }
        )
        context = ContextAssembler().for_opening(
            view,
            opening_text="你在门厅醒来，双手被缚。",
            opening_key_facts=("双手被绳索捆住。",),
        )
        payload = context.to_prompt_dict()
        self.assertEqual(payload["opening_key_facts"], ["双手被绳索捆住。"])
        self.assertEqual(payload["scene"]["time"], "深夜")
        self.assertEqual(payload["scene"]["description"], view.scene.description)
        self.assertEqual(payload["participants"][0]["status_summary"], "失明，双手被绳索捆住。")
        self.assertEqual(payload["addressing_mode"], "second_person")
        for key in ("background", "solo_background_summary", "narration_retry_hint"):
            self.assertNotIn(key, payload)
        self.assertNotIn("id", payload["scene"])
        self.assertNotIn("actor_id", payload["participants"][0])
        self.assertNotIn("narrative_details", payload["scene"])
        # Context and source remain intact for deterministic fallback.
        self.assertEqual(context.scene.id, "foyer")
        self.assertIn("旧宅附近", context.solo_background_summary)
        self.assertTrue(
            deterministic_opening_narration(context).text.startswith(context.opening_text)
        )

    def test_legacy_prompt_keeps_background_without_inventing_facts(self):
        context = ContextAssembler().for_opening(player_view(multiplayer=False))
        payload = context.to_prompt_dict()
        self.assertEqual(payload["background"], context.background)
        self.assertEqual(payload["solo_background_summary"], context.solo_background_summary)
        self.assertNotIn("opening_text", payload)
        self.assertNotIn("opening_key_facts", payload)

    def test_multiplayer_context_contains_all_public_identities_and_no_private_data(
        self,
    ) -> None:
        context = ContextAssembler().for_opening(player_view(multiplayer=True))
        encoded = context.model_dump_json()

        self.assertEqual(
            [(item.name, item.occupation, item.status_summary) for item in context.participants],
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
                    await OpeningNarrator(CandidateOpeningModel(candidate)).narrate(context)

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
        self.assertIsNone(narration_subject_rejection_reason(text, addressing_mode="named_actor"))

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


class AuthoredOpeningTests(unittest.IsolatedAsyncioTestCase):
    def test_source_survives_multiplayer_template_without_reconstruction(self):
        source = "你醒来了。门外传来一句话：“请等候。”\n\n桌上有三封信，今晚之前不能打开。"
        context = (
            ContextAssembler()
            .for_opening(player_view(multiplayer=True), opening_text=source)
            .model_copy(update={"addressing_mode": "named_actor"})
        )
        output = deterministic_opening_narration(context)
        self.assertTrue(output.text.startswith(source + "\n"))
        self.assertIn("杜明", output.text)
        self.assertIn("林夏", output.text)
        self.assertNotIn("旧宅附近度过童年", output.text)

    async def test_model_preserves_source_with_explicit_public_address_edits(self):
        source = "你来到门厅。桌上有三封信，今晚之前不能打开。\n\n门外有人说：“你欠我100美元。”"
        context = (
            ContextAssembler()
            .for_opening(player_view(multiplayer=True), opening_text=source)
            .model_copy(update={"addressing_mode": "named_actor"})
        )
        for address in (
            "杜明与林夏",
            "记者杜明和医生林夏",
            "杜明（记者）、林夏（医生）",
        ):
            # Dialogue stays literal; only the source's prose address is adapted.
            text = source.replace("你来到", f"{address}来到").replace("\n\n", "\n")
            with self.subTest(address=address):
                output = await OpeningNarrator(CandidateOpeningModel({"text": text})).narrate(
                    context
                )
                self.assertEqual(output.text, text)

    async def test_model_accepts_reordered_and_paraphrased_facts(self):
        source = "你们来到门厅。桌上有三封信，今晚之前不能打开。\n\n门外有人说：“你欠我100美元。”"
        context = (
            ContextAssembler()
            .for_opening(
                player_view(multiplayer=True),
                opening_text=source,
                opening_key_facts=("桌上的三封信今晚之前不能打开。", "门外有人讨要100美元。"),
            )
            .model_copy(update={"addressing_mode": "named_actor"})
        )
        text = (
            "门外响起讨要一百美元的声音。杜明和林夏所在的门厅里，"
            "桌上摆着三封信，要等到今晚才能拆开。"
        )
        output = await OpeningNarrator(CandidateOpeningModel({"text": text})).narrate(context)
        self.assertEqual(output.text, text)

    async def test_solo_second_person_does_not_require_name_or_occupation(self):
        context = ContextAssembler().for_opening(
            player_view(multiplayer=False),
            opening_text="你醒来，发现双手被绳索捆住。",
        )
        text = "醒来时，你发现双手被绳索捆住。"
        output = await OpeningNarrator(CandidateOpeningModel({"text": text})).narrate(context)
        self.assertEqual(output.text, text)
        # A single visible participant in a shared named-actor opening still needs identity.
        with self.assertRaises(OpeningNarrationValidationError):
            await OpeningNarrator(CandidateOpeningModel({"text": "双手被绳索捆住。"})).narrate(
                context.model_copy(update={"addressing_mode": "named_actor"})
            )

    async def test_model_accepts_verbatim_source_with_character_introduction(self):
        source = "你们来到门厅。桌上有三封信。"
        context = ContextAssembler().for_opening(player_view(multiplayer=True), opening_text=source)
        text = f"杜明是一名记者，林夏是一名医生。\n{source}"
        output = await OpeningNarrator(CandidateOpeningModel({"text": text})).narrate(context)
        self.assertEqual(output.text, text)
