from __future__ import annotations

import unittest

from collaboration_framework.host.application.narrator import split_narration_chunks


class NarrationChunkingTests(unittest.TestCase):
    def test_concatenated_chunks_reproduce_the_source_text(self) -> None:
        cases = (
            "",
            "短句。",
            "雨点敲打着窗框。屋里只剩壁炉燃烧的细响，книга 摊在桌上。",
            "你推开门。\n\n走廊尽头有一盏灯还亮着，灯下站着一个人影。",
            "他低声问：「你真的要进去吗？」你没有回答，只是握紧了手电筒。",
            "没有任何句末标点的一整段叙述文字就这样一直延续下去",
            "第一句！第二句？第三句……第四句。",
            "  前导空白也要原样保留。  ",
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertEqual("".join(split_narration_chunks(text)), text)

    def test_empty_text_yields_no_chunks(self) -> None:
        self.assertEqual(split_narration_chunks(""), ())

    def test_splits_at_sentence_boundaries(self) -> None:
        text = "雨点敲打着窗框，声音单调。屋里只剩壁炉燃烧的细响，空气发闷。"

        chunks = split_narration_chunks(text)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("。"))

    def test_keeps_closing_quote_with_its_sentence(self) -> None:
        text = "他低声问：「你真的要进去吗？」你没有回答，只是握紧了手电筒。"

        chunks = split_narration_chunks(text)

        self.assertTrue(chunks[0].endswith("」"))

    def test_merges_fragments_shorter_than_the_minimum(self) -> None:
        text = "好。真的吗？走吧。"

        chunks = split_narration_chunks(text)

        self.assertEqual(chunks, (text,))

    def test_short_but_complete_final_sentence_stays_its_own_chunk(self) -> None:
        """短叙事不能因为末句偏短就整段塌成单片、退回非流式（issue #203）。"""

        text = "托马斯·金博尔坐在你面前，正等待你回应委托。\n陈探员此刻就在这里。"

        chunks = split_narration_chunks(text)

        self.assertEqual(len(chunks), 2)
        self.assertEqual("".join(chunks), text)

    def test_trailing_fragment_is_merged_into_the_previous_chunk(self) -> None:
        text = "长度足够的第一句叙述文字放在这里。尾巴"

        chunks = split_narration_chunks(text)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].endswith("尾巴"))

    def test_text_without_sentence_end_is_a_single_chunk(self) -> None:
        text = "没有任何句末标点的一整段叙述文字就这样一直延续下去"

        self.assertEqual(split_narration_chunks(text), (text,))


if __name__ == "__main__":
    unittest.main()
