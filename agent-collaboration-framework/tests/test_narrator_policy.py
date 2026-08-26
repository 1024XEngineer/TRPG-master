from __future__ import annotations

import unittest
from types import SimpleNamespace

from collaboration_framework.contracts import CommittedResult, PlayerInput
from collaboration_framework.host.application.action_plan_narrator import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
)
from collaboration_framework.host.application.narration_policy import (
    narration_atmosphere_rejection_reason,
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
            (
                '托马斯沉默。","claimed_evidence_refs":["evt_1"],'
                '"suggested_actions":["继续调查"]}'
            ): "protocol_tail",
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

    def test_named_actor_rejects_unquoted_second_person(self) -> None:
        self.assertEqual(
            narration_subject_rejection_reason(
                "你打开了抽屉。",
                addressing_mode="named_actor",
            ),
            "subject_ownership",
        )
        self.assertEqual(
            narration_subject_rejection_reason(
                "陈探员打开了抽屉。",
                addressing_mode="named_actor",
            ),
            None,
        )

    def test_named_actor_allows_second_person_in_dialogue(self) -> None:
        self.assertIsNone(
            narration_subject_rejection_reason(
                "托马斯问：「你是谁？」",
                addressing_mode="named_actor",
            )
        )
        self.assertIsNone(
            narration_subject_rejection_reason(
                "陈探员对托马斯说：“我会保护你们。”",
                addressing_mode="named_actor",
            )
        )

    def test_second_person_mode_still_allows_unquoted_you(self) -> None:
        self.assertIsNone(
            narration_subject_rejection_reason(
                "你打开了抽屉。",
                addressing_mode="second_person",
            )
        )

    def test_rejects_repeated_atmosphere_opening_from_previous_narration(self) -> None:
        previous = (
            "夜色如墨，阿诺兹堡公共墓地沉浸在死一般的寂静中。"
            "凌铭辉守在那块沉重的石板旁。"
        )
        repeated = (
            "夜色如墨，阿诺兹堡公共墓地沉浸在死一般的寂静中。"
            "JOJO 站在那块沉重的石板旁，想知道为什么打不开。"
        )
        self.assertEqual(
            narration_atmosphere_rejection_reason(repeated, previous),
            "atmosphere_repeat",
        )
        self.assertIsNone(
            narration_atmosphere_rejection_reason(
                "石板纹丝不动。缝隙里只有陈腐的气味，没有能撬开的着力点。",
                previous,
            )
        )
        self.assertIsNone(narration_atmosphere_rejection_reason(repeated, None))
        self.assertIsNone(
            narration_atmosphere_rejection_reason("石板纹丝不动。", previous)
        )

    def test_rejects_paraphrased_afternoon_window_openings(self) -> None:
        opening = (
            "大厦，午后阳光透过办公室的百叶窗，洒在托马斯·金博尔那张布满皱纹的脸上。"
            "他双手交叉放在桌上，身前摊开一封泛黄的信件。"
        )
        accept = (
            "午后的光从金博尔宅会客室的百叶窗渗进来，你在托马斯·金博尔对面缓缓坐下，"
            "把手里的公文包搁在膝上。他略略向前倾身，眼神里既有期待，也有一丝不易察觉的疲惫。"
        )
        study = (
            "你从托马斯的会客室起身，穿过金博尔宅安静的走廊，推开书房的门。"
            "午后的光线透过木框玻璃窗洒进来，落在满架的书籍上。"
        )
        leave = (
            "午后的阳光透过书房的窗户洒在排列整齐的书脊上。"
            "你把笔记本收进公文包，关上书房的门。"
        )
        self.assertEqual(
            narration_atmosphere_rejection_reason(accept, opening),
            "atmosphere_repeat",
        )
        self.assertEqual(
            narration_atmosphere_rejection_reason(leave, study),
            "atmosphere_repeat",
        )
        self.assertIsNone(
            narration_atmosphere_rejection_reason(
                "你点了点头，接下这份委托。托马斯像是松了一口气。",
                opening,
            )
        )
        self.assertIsNone(
            narration_atmosphere_rejection_reason(
                "你把笔记本收进公文包，关上书房的门，走向公共墓地。",
                study,
            )
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


class _PersistentNarrationWithNpcRepliesModel:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, context):
        return {
            "kind": "narration",
            "text": self.text,
            "claimed_evidence_refs": [],
            "suggested_actions": [],
            "npc_replies": [
                {"speaker_id": "thomas", "text": "我已经记住了。"},
            ],
        }


class PersistentNarrationPolicyTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, *, results=(), inventory=(), utterance="行动"):
        view = SimpleNamespace(
            room_id="room",
            player_id="player",
            actor_id="actor",
            background="背景",
            scene=SimpleNamespace(visible_entities=()),
            inventory=inventory,
        )
        return ActionPlanNarrationContext.model_construct(
            background="背景",
            player_input=PlayerInput(
                room_id="room",
                player_id="player",
                actor_id="actor",
                client_action_id="action",
                utterance=utterance,
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

    async def test_named_actor_mode_rejects_unquoted_you(self):
        context = self._context().model_copy(
            update={
                "addressing_mode": "named_actor",
                "acting_character_name": "陈探员",
            }
        )
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel("你打开了抽屉。")
            ).narrate(context)
        self.assertEqual(raised.exception.reason, "subject_ownership")

    async def test_named_actor_mode_rejects_repeated_atmosphere_opening(self):
        previous = "夜色如墨，阿诺兹堡公共墓地沉浸在死一般的寂静中。凌铭辉守在石板旁。"
        context = self._context().model_copy(
            update={
                "addressing_mode": "named_actor",
                "acting_character_name": "JOJO",
                "previous_published_narration": previous,
            }
        )
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel(
                    "夜色如墨，阿诺兹堡公共墓地沉浸在死一般的寂静中。"
                    "JOJO 站在石板旁，却说不清为什么打不开。"
                )
            ).narrate(context)
        self.assertEqual(raised.exception.reason, "atmosphere_repeat")

    async def test_named_actor_mode_rejects_paraphrased_afternoon_opening(self):
        opening = (
            "大厦，午后阳光透过办公室的百叶窗，洒在托马斯·金博尔那张布满皱纹的脸上。"
        )
        context = self._context().model_copy(
            update={
                "addressing_mode": "named_actor",
                "acting_character_name": "大厦",
                "previous_published_narration": opening,
            }
        )
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel(
                    "午后的光从金博尔宅会客室的百叶窗渗进来，"
                    "大厦在托马斯·金博尔对面坐下，接下委托。"
                )
            ).narrate(context)
        self.assertEqual(raised.exception.reason, "atmosphere_repeat")

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
            ),
        )
        context = self._context()
        context.player_view.scene.visible_entities = (entity,)
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("守墓人双眼紧闭，仍然没有醒来。")
        ).narrate(context)
        self.assertIn("仍然没有醒来", output.text)

    async def test_rejects_inventory_claim_when_final_view_has_no_item(self):
        result = CommittedResult(
            kind="inventory",
            target_id="fixed_archive",
            event_ref="event-1",
        )

        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel("你把那册资料收好，放进背包。")
            ).narrate(self._context(results=(result,)))

        self.assertEqual(
            raised.exception.reason,
            "persistent_claim_without_evidence:inventory_acquisition",
        )

    async def test_allows_acquisition_confirmed_by_result_and_final_inventory(self):
        result = CommittedResult(
            kind="inventory",
            target_id="runtime_volume",
            event_ref="event-1",
        )
        inventory = (
            SimpleNamespace(id="runtime_volume", name="一本薄诗集"),
        )

        output = await ActionPlanNarrator(
            _PersistentNarrationModel("你拿起诗集，将它放进背包。")
        ).narrate(self._context(results=(result,), inventory=inventory))

        self.assertIn("放进背包", output.text)

    async def test_rejects_different_item_even_when_another_pickup_was_confirmed(self):
        result = CommittedResult(
            kind="inventory",
            target_id="runtime_branch",
            event_ref="event-1",
        )
        inventory = (
            SimpleNamespace(id="runtime_branch", name="一根干树枝"),
        )

        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("你把那本手册装进背包。")
            ).narrate(self._context(results=(result,), inventory=inventory))

    async def test_rejects_uncommitted_sleeping_synonyms(self):
        """没有证据时，闭眼、未醒和躺倒等同义事实也必须被拒绝。"""
        for text in (
            "守墓人双眼紧闭。",
            "守墓人仍未醒来。",
            "守墓人躺在墓园草地上。",
        ):
            with (
                self.subTest(text=text),
                self.assertRaises(ActionPlanNarrationValidationError),
            ):
                await ActionPlanNarrator(_PersistentNarrationModel(text)).narrate(
                    self._context()
                )

    async def test_allows_object_prone_environment_description(self):
        """死物使用“躺在/躺着”描述位置时，不应触发角色姿态校验。"""
        context = self._context()
        context.player_view.scene.visible_entities = (
            SimpleNamespace(
                id="key",
                name="一把钥匙",
                aliases=(),
                kind="object",
                observable_state=(),
            ),
        )

        output = await ActionPlanNarrator(
            _PersistentNarrationModel("一把钥匙躺在桌上。")
        ).narrate(context)

        self.assertEqual(output.text, "一把钥匙躺在桌上。")

    async def test_allows_unbound_object_description_without_visible_npc(self):
        """纯物件场景中未点名实体的环境描写也不应被误判为角色姿态。"""
        context = self._context()
        context.player_view.scene.visible_entities = (
            SimpleNamespace(
                id="notebook",
                name="一本笔记",
                aliases=(),
                kind="object",
                observable_state=(),
            ),
        )

        output = await ActionPlanNarrator(
            _PersistentNarrationModel("桌上躺着一本笔记。")
        ).narrate(context)

        self.assertEqual(output.text, "桌上躺着一本笔记。")

    async def test_rejects_named_npc_prone_without_evidence(self):
        """点名 NPC 的躺倒描述仍必须有权威姿态证据。"""
        context = self._context()
        context.player_view.scene.visible_entities = (
            SimpleNamespace(
                id="butler",
                name="守墓人",
                aliases=(),
                kind="npc",
                observable_state=(),
            ),
        )

        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel("守墓人躺在墓园草地上。")
            ).narrate(context)

        self.assertEqual(
            raised.exception.reason,
            "persistent_claim_without_evidence:posture",
        )

    async def test_allows_named_npc_prone_with_evidence(self):
        """点名 NPC 且当前回合已提交姿态结果时允许叙述。"""
        context = self._context(
            results=(
                CommittedResult(
                    kind="character_state",
                    target_id="butler",
                    state_key="posture",
                    state_value="prone",
                    event_ref="event-1",
                ),
            )
        )
        context.player_view.scene.visible_entities = (
            SimpleNamespace(
                id="butler",
                name="守墓人",
                aliases=(),
                kind="npc",
                observable_state=(),
            ),
        )

        output = await ActionPlanNarrator(
            _PersistentNarrationModel("守墓人躺在墓园草地上。")
        ).narrate(context)

        self.assertEqual(output.text, "守墓人躺在墓园草地上。")

    async def test_allows_unprojected_companion_active_presence(self):
        """未进入标准场景投影的随行人物不能被全局在场校验误伤。"""
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("托马斯跟在你身边，正站在墓园入口。")
        ).narrate(self._context())

        self.assertEqual(output.text, "托马斯跟在你身边，正站在墓园入口。")

    async def test_rejects_dead_visible_npc_active_presence(self):
        """即使尸体仍然可见，死亡实体也不能被描述为站立或主动移动。"""
        entity = SimpleNamespace(
            id="butler",
            name="守墓人",
            aliases=("梅洛迪亚斯·杰弗逊",),
            observable_state=(SimpleNamespace(key="consciousness", value="dead"),),
        )
        context = self._context()
        context.player_view.scene.visible_entities = (entity,)
        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel("守墓人仍站在墓碑旁。")
            ).narrate(context)

        with self.assertRaises(ActionPlanNarrationValidationError):
            await ActionPlanNarrator(
                _PersistentNarrationModel(
                    "梅洛迪亚斯·杰弗逊的外套还在，人却已经不见了。"
                )
            ).narrate(context)

    async def test_rejects_search_question_when_dead_body_is_visible(self):
        """尸体已在当前 PlayerView 时，不能重新询问玩家要去哪里寻找。"""
        entity = SimpleNamespace(
            id="butler",
            name="守墓人",
            aliases=("梅洛迪亚斯·杰弗逊",),
            observable_state=(SimpleNamespace(key="consciousness", value="dead"),),
        )
        context = self._context(utterance="去找他的尸体")
        context.player_view.scene.visible_entities = (entity,)

        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel("你打算从哪里开始找？还是扩大范围搜寻尸体？")
            ).narrate(context)

        self.assertEqual(raised.exception.reason, "visible_corpse_search_conflict")

    async def test_allows_player_presence_without_visible_npc(self):
        """校验只限制 NPC 在场断言，不阻止主持人描述玩家自己的位置。"""
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("你站在寄宿屋的房间里。")
        ).narrate(self._context())
        self.assertEqual(output.text, "你站在寄宿屋的房间里。")

        plural_output = await ActionPlanNarrator(
            _PersistentNarrationModel("你们正坐在旅店的桌边。")
        ).narrate(self._context())
        self.assertEqual(plural_output.text, "你们正坐在旅店的桌边。")

    async def test_rejects_embedded_npc_dialogue_when_followup_replies_exist(self):
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationWithNpcRepliesModel(
                    '托马斯笑了笑，说：“我已经记住了。”'
                )
            ).narrate(self._context())

        self.assertEqual(raised.exception.reason, "npc_dialogue_embedded_in_text")


if __name__ == "__main__":
    unittest.main()
