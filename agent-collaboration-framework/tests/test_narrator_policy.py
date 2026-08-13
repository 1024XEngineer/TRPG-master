from __future__ import annotations

import unittest
from types import SimpleNamespace

from collaboration_framework.host.application.narrator import (
    NarrationValidationError,
    Narrator,
    narration_subject_rejection_reason,
    narration_text_rejection_reason,
    normalize_narration_text,
)


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
            "suggested_actions: [\"继续询问\"]": "protocol_tail",
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
            (
                '托马斯沉默。","claimed_evidence_refs":["evt_1"],'
                '"suggested_actions":["继续调查"]}'
            ): "protocol_tail",
            "托马斯沉默。\n```json\nsuggestedActions:\n```": "protocol_tail",
            (
                '{"kind":"narration","text":"托马斯看着你。",'
                '"claimed_fact_ids":[]}'
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
                "现场只剩下雨声。\n"
                '{"required":["kind","text","claimed_fact_ids"]'
            ): "schema_fragment",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(narration_text_rejection_reason(text), expected)

    def test_allows_natural_narration_and_non_protocol_technical_discussion(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
