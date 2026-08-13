from __future__ import annotations

import unittest
from types import SimpleNamespace

from collaboration_framework.contracts import CommittedResult, PlayerInput
from collaboration_framework.host.application.action_plan_narrator import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
)
from collaboration_framework.host.application.narrator import (
    NarrationValidationError,
    Narrator,
    narration_subject_rejection_reason,
    narration_text_rejection_reason,
    normalize_narration_text,
)
from collaboration_framework.host.schemas import ActionPlanNarrationContext


class NarrationTextPolicyTests(unittest.TestCase):
    def test_normalizes_literal_newline_escapes_without_general_decoding(self) -> None:
        cases = {
            "第一段\\n第二段": "第一段\n第二段",
            "第一段\\r\\n第二段": "第一段\n第二段",
            "第一段\\r第二段": "第一段\n第二段",
            "第一段\\n\\n第二段": "第一段\n\n第二段",
            "第一段\n第二段": "第一段\n第二段",
            "制表符\\t保持原样": "制表符\\t保持原样",
            "C:\\temp\\file.txt": "C:\\temp\\file.txt",
            "普通反斜杠\\\\保持原样": "普通反斜杠\\\\保持原样",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                normalized = normalize_narration_text(text)
                self.assertEqual(normalized, expected)
                self.assertEqual(normalize_narration_text(normalized), expected)

    def test_normalizes_before_protocol_tail_detection(self) -> None:
        normalized = normalize_narration_text(
            "托马斯说完便沉默。\\nclaimed_fact_ids: []"
        )

        self.assertEqual(narration_text_rejection_reason(normalized), "protocol_tail")

    def test_rejects_protocol_field_assignments_and_json_tails(self) -> None:
        cases = {
            "托马斯看着你。 claimed_fact_ids: [],": "protocol_tail",
            "托马斯看着你 claimed_fact_ids: []": "protocol_tail",
            'suggested_actions: ["继续询问"]': "protocol_tail",
            'suggested_actions: [\n  "继续询问",\n  "查看书架"\n]': "protocol_tail",
            "'claimedFactIds'：null": "protocol_tail",
            '他说完便沉默下来。\n"suggestedActions": []': "protocol_tail",
            "他说完便沉默下来。\n```json\nclaimed_fact_ids: []\n```": "protocol_tail",
            '托马斯沉默。\ntext: "托马斯沉默。"': "protocol_tail",
            "托马斯沉默。\nkind: narration": "protocol_tail",
            "'text'：'托马斯沉默。'": "protocol_tail",
            '"kind"：clarification': "protocol_tail",
            "托马斯沉默。\ntext:": "protocol_tail",
            "托马斯沉默。\nkind:": "protocol_tail",
            "托马斯沉默。\nclaimed_fact_ids:": "protocol_tail",
            "托马斯沉默。\n```json\nsuggestedActions:\n```": "protocol_tail",
            (
                '{"kind":"narration","text":"托马斯看着你。","claimed_fact_ids":[]}'
            ): "protocol_tail",
            (
                '托马斯后退一步 {"kind":"narration","text":"他保持沉默",'
                '"claimed_fact_ids":[]}'
            ): "protocol_tail",
            (
                "现场只剩下雨声。\n"
                "```json\n"
                '{"kind":"clarification","text":"你指的是哪一扇门？"}\n'
                "```"
            ): "protocol_tail",
            (
                "现场只剩下雨声。\n"
                '{"properties":{"kind":{"type":"string"},'
                '"claimed_fact_ids":{"type":"array"}}'
            ): "schema_fragment",
            (
                '现场只剩下雨声。\n{"required":["kind","text","claimed_fact_ids"]'
            ): "schema_fragment",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(narration_text_rejection_reason(text), expected)

    def test_allows_natural_narration_and_non_protocol_technical_discussion(
        self,
    ) -> None:
        cases = (
            "托马斯抬起眼睛，耐心等着你继续问下去。",
            "雨点敲打着窗框。\n\n屋里只剩壁炉燃烧的细响。",
            "他问你 claimed_fact_ids 是什么意思。",
            "纸上写着 claimed_fact_ids: []，旁边说明这是一个空列表。",
            "日志中的 not_claimed_fact_ids: [] 是另一个测试字段。",
            '纸上写着 text: "叙事"，旁边说明这是正文字段。',
            "手册把 kind: narration 称为叙事类型。",
            '终端显示 {"status":"ok","items":[]}，没有更多提示。',
            '她念出 {"kind":"artifact","name":"旧铜钥匙"}，随后合上笔记。',
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(narration_text_rejection_reason(text))

    def test_rejects_first_person_subjects_outside_quoted_spans(self) -> None:
        cases = (
            "我带着你们进入墓园。",
            "我当过兵，知道该怎么办。",
            "我们继续向前走。",
            "咱们沿着墓碑间的小路前进。",
            "托马斯说：“我会保护你们。随后我们继续前进。",
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    narration_subject_rejection_reason(text),
                    "subject_ownership",
                )

    def test_allows_first_person_in_dialogue_and_quoted_titles(self) -> None:
        cases = (
            "你对托马斯说：“我会保护你们。”",
            "托马斯说：「我叔叔以前常来这里。」",
            "管理员说：『我们没有保存那份报纸。』",
            "你听见她低声说：‘我记得那个人。’",
            '托马斯说："我会和你一起去。"',
            "托马斯说：'我会和你一起去。'",
            "你翻开《我的秘密生涯》，发现其中缺了几页。",
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(narration_subject_rejection_reason(text))


class _CandidateNarrationModel:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, context):
        del context
        return {
            "kind": "narration",
            "text": self.text,
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


class NarratorSubjectPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_narrator_rejects_first_person_subject_in_prose(self) -> None:
        context = SimpleNamespace(
            action_result=SimpleNamespace(visible_facts=()),
        )

        with self.assertRaises(NarrationValidationError) as raised:
            await Narrator(_CandidateNarrationModel("我带着你们进入墓园。")).narrate(
                context
            )

        self.assertEqual(raised.exception.reason, "subject_ownership")


class _PersistentNarrationModel:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, context):
        return {
            "kind": "narration",
            "text": self.text,
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class PersistentNarrationPolicyTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, *, results=()):
        view = SimpleNamespace(
            room_id="room",
            player_id="player",
            actor_id="actor",
            background="背景",
            scene=SimpleNamespace(visible_entities=()),
        )
        return ActionPlanNarrationContext.model_construct(
            background="背景",
            player_input=PlayerInput(
                room_id="room",
                player_id="player",
                actor_id="actor",
                client_action_id="action",
                utterance="行动",
            ),
            plan_goal="行动",
            termination_status="resolved",
            completed_steps=(
                SimpleNamespace(
                    step_index=0,
                    semantic_goal="行动",
                    outcome="success",
                    view_revision="1",
                    event_refs=("event-1",),
                    committed_results=results,
                ),
            ),
            player_view=view,
            allowed_evidence_refs=("event-1",),
        )

    async def test_rejects_uncommitted_unconscious_claim(self):
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("守墓人昏迷了。")
            ).narrate(self._context())

    async def test_allows_committed_unconscious_claim(self):
        result = CommittedResult(
            kind="character_state",
            target_id="butler",
            state_key="consciousness",
            state_value="unconscious",
            event_ref="event-1",
        )
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("守墓人昏迷了。")
        ).narrate(self._context(results=(result,)))
        self.assertEqual(output.text, "守墓人昏迷了。")

    async def test_allows_previous_turn_unconscious_state_from_player_view(self):
        """上一回合已公开的 NPC 状态必须能约束本回合的询问叙事。"""
        entity = SimpleNamespace(
            id="butler",
            name="守墓人",
            aliases=("墓地看守",),
            observable_state=(
                SimpleNamespace(key="consciousness", value="unconscious"),
            )
        )
        context = self._context()
        context.player_view.scene.visible_entities = (entity,)
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("守墓人双眼紧闭，仍然没有醒来。")
        ).narrate(context)
        self.assertIn("仍然没有醒来", output.text)

    async def test_rejects_uncommitted_sleeping_synonyms(self):
        """没有证据时，闭眼、未醒和躺倒等同义事实也必须被拒绝。"""
        for text in (
            "守墓人双眼紧闭。",
            "守墓人仍未醒来。",
            "守墓人躺在墓园草地上。",
        ):
            with self.subTest(text=text), self.assertRaises(
                ActionPlanNarrationValidationError
            ):
                await ActionPlanNarrator(
                    _PersistentNarrationModel(text)
                ).narrate(self._context())

    async def test_rejects_uncommitted_inverse_persistent_claims(self):
        """持久状态的反向变化没有证据时同样不能由主持人补写。"""
        for text in (
            "守墓人醒来了。",
            "门已经关上。",
            "锁已经解开。",
            "绳索已经解除，目标恢复自由。",
            "箱子已经修好。",
        ):
            with self.subTest(text=text), self.assertRaises(
                ActionPlanNarrationValidationError
            ):
                await ActionPlanNarrator(
                    _PersistentNarrationModel(text)
                ).narrate(self._context())

    async def test_allows_inverse_persistent_claims_from_player_view(self):
        """最终玩家视图存在精确状态时，反向持久变化可以正常叙述。"""
        cases = (
            ("consciousness", "conscious", "守墓人醒来了。"),
            ("posture", "standing", "守墓人站起来了。"),
            ("restraint", "free", "守墓人恢复自由。"),
            ("injury", "none", "守墓人伤势痊愈。"),
            ("open", False, "守墓人面前的门已经关上。"),
            ("locked", False, "守墓人面前的锁已经解开。"),
            ("broken", False, "守墓人身旁的箱子已经修好。"),
        )
        for key, value, text in cases:
            with self.subTest(key=key, value=value):
                entity = SimpleNamespace(
                    id="butler",
                    name="守墓人",
                    aliases=("墓地看守",),
                    observable_state=(SimpleNamespace(key=key, value=value),),
                )
                context = self._context()
                context.player_view.scene.visible_entities = (entity,)
                output = await ActionPlanNarrator(
                    _PersistentNarrationModel(text)
                ).narrate(context)
                self.assertEqual(output.text, text)

    async def test_rejects_ambiguous_pronoun_when_multiple_entities_match(self):
        """多个 NPC 都有同类状态时，未绑定的“他”不能任选证据。"""
        entities = tuple(
            SimpleNamespace(
                id=entity_id,
                name=name,
                aliases=(),
                observable_state=(
                    SimpleNamespace(key="consciousness", value="unconscious"),
                ),
            )
            for entity_id, name in (("butler", "守墓人"), ("guard", "守卫"))
        )
        context = self._context()
        context.player_view.scene.visible_entities = entities
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("他昏迷了。")
            ).narrate(context)

    async def test_rejects_unbound_pronoun_when_other_visible_npc_lacks_evidence(self):
        """多个 NPC 同场时，即使只有一个有证据也不能用“他”隐式绑定目标。"""
        entities = (
            SimpleNamespace(
                id="butler",
                kind="npc",
                name="守墓人",
                aliases=(),
                observable_state=(
                    SimpleNamespace(key="consciousness", value="unconscious"),
                ),
            ),
            SimpleNamespace(
                id="guard",
                kind="npc",
                name="守卫",
                aliases=(),
                observable_state=(),
            ),
        )
        context = self._context()
        context.player_view.scene.visible_entities = entities
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("他昏迷了。")
            ).narrate(context)

    async def test_allows_unbound_pronoun_with_single_visible_npc(self):
        """场景只有一个可见 NPC 且有精确证据时，保留“他”的兼容语义。"""
        entity = SimpleNamespace(
            id="butler",
            kind="npc",
            name="守墓人",
            aliases=(),
            observable_state=(
                SimpleNamespace(key="consciousness", value="unconscious"),
            ),
        )
        context = self._context()
        context.player_view.scene.visible_entities = (entity,)
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("他昏迷了。")
        ).narrate(context)
        self.assertEqual(output.text, "他昏迷了。")

    async def test_requires_all_named_entities_to_have_matching_evidence(self):
        """同一句点名多个实体时，所有实体都必须有对应状态证据。"""
        entities = (
            SimpleNamespace(
                id="butler",
                name="守墓人",
                aliases=(),
                observable_state=(
                    SimpleNamespace(key="consciousness", value="unconscious"),
                ),
            ),
            SimpleNamespace(
                id="guard",
                name="守卫",
                aliases=(),
                observable_state=(),
            ),
        )
        context = self._context()
        context.player_view.scene.visible_entities = entities
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("守墓人和守卫都昏迷了。")
            ).narrate(context)

    async def test_injury_levels_are_mutually_exclusive_and_critical_is_checked(self):
        """重伤、轻伤、危重伤分别绑定自己的标准值。"""
        for text, value in (
            ("守墓人重伤了。", "major"),
            ("守墓人伤势危重。", "critical"),
        ):
            with self.subTest(text=text):
                entity = SimpleNamespace(
                    id="butler",
                    name="守墓人",
                    aliases=(),
                    observable_state=(SimpleNamespace(key="injury", value=value),),
                )
                context = self._context()
                context.player_view.scene.visible_entities = (entity,)
                output = await ActionPlanNarrator(
                    _PersistentNarrationModel(text)
                ).narrate(context)
                self.assertEqual(output.text, text)
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("守墓人伤势危重。")
            ).narrate(self._context())


if __name__ == "__main__":
    unittest.main()
