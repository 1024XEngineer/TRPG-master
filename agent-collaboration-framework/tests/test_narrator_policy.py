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


class _DeclaringNarrationModel:
    """按 #512 的申报范式返回叙事：正文之外还自报背包与状态变化。"""

    def __init__(self, text, *, inventory_ids=(), state_changes=()):
        self.text = text
        self.inventory_ids = inventory_ids
        self.state_changes = state_changes

    async def generate(self, context):
        return {
            "kind": "narration",
            "text": self.text,
            "claimed_evidence_refs": [],
            "claimed_inventory_ids": list(self.inventory_ids),
            "claimed_state_changes": [
                {"entity_id": entity_id, "key": key, "value": value}
                for entity_id, key, value in self.state_changes
            ],
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
    def _context(
        self,
        *,
        results=(),
        inventory=(),
        utterance="行动",
        entities=(),
        loose_items=(),
    ):
        view = SimpleNamespace(
            room_id="room",
            player_id="player",
            actor_id="actor",
            background="背景",
            scene=SimpleNamespace(
                visible_entities=entities,
                loose_items=loose_items,
            ),
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

    async def test_allows_transient_handling_during_inspection_without_inventory_move(self):
        output = await ActionPlanNarrator(
            _PersistentNarrationModel(
                "你拿起传单仔细查看，发现它并不是印刷品，而是精确的手绘作品。"
            )
        ).narrate(self._context())

        self.assertIn("手绘作品", output.text)

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


# 《幸福蛙蛙村》lane_manor 的权威投影：两件场景物件与一位在场 NPC。
# 传单在模组里是 kind=object 的可见实体，不是 loose_item——权威物品名闭集
# 必须同时覆盖这两个来源，#512 的验收用例正压在这上面。
_FLYER = SimpleNamespace(
    id="resort_flyer",
    kind="object",
    name="蛙蛙度假村传单",
    aliases=(),
    observable_state=(),
)
_COMMISSION = SimpleNamespace(
    id="lane_commission",
    kind="object",
    name="莱恩夫妇的委托",
    aliases=(),
    observable_state=(),
)
_MADAM_LANE = SimpleNamespace(
    id="madam_lane", kind="npc", name="莱恩夫人", aliases=(), observable_state=()
)
_LANE_MANOR = (_FLYER, _COMMISSION, _MADAM_LANE)

# Issue #512 验收用例。传单与委托都在场，最终 inventory 为空。
_TRANSIENT_HANDLING_CASES = (
    "你拿起电话，拨打了传单上的号码，但电话那头传来的只是一阵持续的忙音，无人接听。",
    "你拿起听筒贴到耳边，线路那头一片死寂。",
    "你拿起桌上的照片，指腹擦过詹姆斯的脸。",
    "你拿起茶杯抿了一口，茶已经凉了。",
    "你拿起手册翻到第一页。",
    "莱恩夫人拿起手帕擦了擦眼角。",
    "你拿起门边的雨伞掂了掂重量。",
    "你拿起传单，仔细端详上面的图案。",
)
_ACQUISITION_CLAIM_CASES = (
    "你把传单收进外套口袋。",
    "你把蛙蛙度假村传单放进背包。",
    "你顺手把那张传单带走了。",
)


class InventoryClaimDeclarationTests(unittest.IsolatedAsyncioTestCase):
    """#512：取得判定由动词词表改为申报 + 对引擎真值的集合包含判断。"""

    _context = PersistentNarrationPolicyTests._context

    async def test_transient_handling_is_not_an_acquisition_claim(self):
        """临时取用是开集搭配，词表追不上；它本就不声称物品进了背包。"""
        context = self._context(entities=_LANE_MANOR)
        for text in _TRANSIENT_HANDLING_CASES:
            with self.subTest(text=text):
                output = await ActionPlanNarrator(
                    _PersistentNarrationModel(text)
                ).narrate(context)
                self.assertEqual(output.text, text)

    async def test_rejects_unsupported_acquisition_of_a_scene_item(self):
        """声称权威物品进了背包、而最终 inventory 里没有它时仍然必须拒绝。"""
        context = self._context(entities=_LANE_MANOR)
        for text in _ACQUISITION_CLAIM_CASES:
            with self.subTest(text=text):
                with self.assertRaises(ActionPlanNarrationValidationError) as raised:
                    await ActionPlanNarrator(
                        _PersistentNarrationModel(text)
                    ).narrate(context)
                self.assertEqual(
                    raised.exception.reason,
                    "persistent_claim_without_evidence:inventory_acquisition",
                )

    async def test_allows_deposit_once_the_item_reached_final_inventory(self):
        """同一句话在传单确实入包后必须通过——判据是最终 inventory，不是措辞。"""
        context = self._context(
            entities=_LANE_MANOR,
            inventory=(SimpleNamespace(id="resort_flyer", name="蛙蛙度假村传单"),),
        )
        output = await ActionPlanNarrator(
            _DeclaringNarrationModel(
                "你把传单收进背包。", inventory_ids=("resort_flyer",)
            )
        ).narrate(context)
        self.assertEqual(output.claimed_inventory_ids, ("resort_flyer",))

    async def test_rejects_inventory_declaration_absent_from_final_inventory(self):
        """过度申报：申报的 id 不在最终 inventory，集合校验当场挡掉。"""
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _DeclaringNarrationModel(
                    "你把传单收进背包。", inventory_ids=("resort_flyer",)
                )
            ).narrate(self._context(entities=_LANE_MANOR))
        self.assertEqual(raised.exception.reason, "inventory_claim_scope")

    async def test_rejects_state_declaration_absent_from_engine_truth(self):
        """状态申报同样只做集合包含判断，写不出引擎认得的三元组就过不去。"""
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _DeclaringNarrationModel(
                    "守墓人靠在墓碑上。",
                    state_changes=(("butler", "consciousness", "unconscious"),),
                )
            ).narrate(self._context())
        self.assertEqual(raised.exception.reason, "state_claim_scope")

    async def test_allows_state_declaration_backed_by_committed_result(self):
        result = CommittedResult(
            kind="character_state",
            target_id="butler",
            state_key="consciousness",
            state_value="unconscious",
            event_ref="event-1",
        )
        output = await ActionPlanNarrator(
            _DeclaringNarrationModel(
                "守墓人昏迷了。",
                state_changes=(("butler", "consciousness", "unconscious"),),
            )
        ).narrate(self._context(results=(result,)))
        self.assertEqual(len(output.claimed_state_changes), 1)

    async def test_under_declared_claim_carries_the_offending_sentence(self):
        """申报不足时优先修复正文而不是丢弃它：错误必须带上可剔除的那一句。"""
        text = "你在门厅站定，四下打量。你把传单收进外套口袋。远处传来钟声。"
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(_PersistentNarrationModel(text)).narrate(
                self._context(entities=_LANE_MANOR)
            )
        error = raised.exception
        self.assertIsNotNone(error.output)
        self.assertEqual(len(error.offending_spans), 1)
        start, end = error.offending_spans[0]
        self.assertEqual(text[start:end], "你把传单收进外套口袋。")
        self.assertEqual(
            text[:start] + text[end:],
            "你在门厅站定，四下打量。远处传来钟声。",
        )

    async def test_npc_subject_deposit_is_not_a_player_acquisition(self):
        """主语是在场 NPC 时，这句与玩家背包无关；判别沿用 #425 的实体类型口径。"""
        output = await ActionPlanNarrator(
            _PersistentNarrationModel("莱恩夫人把委托的信件收进口袋。")
        ).narrate(self._context(entities=_LANE_MANOR))
        self.assertIn("收进口袋", output.text)

    async def test_loose_scene_items_also_bind_takeaway_verbs(self):
        """权威物品名闭集必须覆盖场景散落物，不只是可见实体。"""
        loose = (SimpleNamespace(id="brass_key", name="一枚黄铜钥匙"),)
        with self.assertRaises(ActionPlanNarrationValidationError) as raised:
            await ActionPlanNarrator(
                _PersistentNarrationModel("你顺手把那枚黄铜钥匙带走了。")
            ).narrate(self._context(loose_items=loose))
        self.assertEqual(
            raised.exception.reason,
            "persistent_claim_without_evidence:inventory_acquisition",
        )


if __name__ == "__main__":
    unittest.main()
