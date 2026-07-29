from __future__ import annotations

import unittest

from collaboration_framework.host.application.narrator import (
    narration_text_rejection_reason,
)


class NarrationTextPolicyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
