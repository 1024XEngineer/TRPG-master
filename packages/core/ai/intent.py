"""IntentParser —— 对应 master §4.5，LLM，按 role='intent' 查 ModelRoleConfig 选实现。

任务是"在 menu 给的候选里找最匹配的一项，找不到就把原话装进 text"——软判据
在上游 LLM 求值，落成 Ref 这个二态确定性结构；RulesEngine 之后只读这个结构。
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI
from pydantic import TypeAdapter

from core.ai.config import PROVIDER_BASE_URLS, DEFAULT_MODEL_ROLE_CONFIGS, get_api_key
from core.rules.models import Intent, IntentUnknown
from core.view.models import PlayerView, SceneActionMenu


@runtime_checkable
class IntentParser(Protocol):
    async def parse_intent(self, utterance: str, view: PlayerView, menu: SceneActionMenu) -> Intent:
        ...


class StubIntentParser:
    async def parse_intent(self, utterance: str, view: PlayerView, menu: SceneActionMenu) -> Intent:
        raise NotImplementedError("IntentParser.parse_intent: 待接入 LLM（role='intent'）")


_INTENT_ADAPTER: TypeAdapter[Intent] = TypeAdapter(Intent)

_SYSTEM_PROMPT = """你是一个 COC 跑团游戏的意图解析器。给定玩家的自然语言输入、当前场景描述、\
和当前场景里可交互对象的候选列表，把玩家的话分类成下面几种意图之一，只输出一个 JSON 对象，不要输出\
任何其他文字或代码块标记：

1. 调查/查看某个物体、线索、细节：
   {"kind": "investigate", "target": {"matched": true, "id": "<候选实体的id>"}}
   如果玩家说的目标不在候选列表里，用：
   {"kind": "investigate", "target": {"matched": false, "text": "<玩家提到的目标原文>"}}
2. 移动去另一个场景：
   {"kind": "move", "toScene": {"matched": true, "id": "<候选出口的sceneId>"}}（或 matched:false + text）
3. 和某个 NPC 说话：
   {"kind": "talk", "npc": {"matched": true, "id": "<候选NPC的id>"}, "utterance": "<玩家想说的话>"}
4. 玩家主动要求做一次技能检定（比如"我要做一次侦查检定"）：
   {"kind": "skillCheck", "skill": "<技能名>"}
5. 玩家在跳出角色扮演提问（问规则、问剧情走向等，不是角色的动作）：
   {"kind": "ask", "question": "<问题原文>"}
6. 完全无法归类：
   {"kind": "unknown", "raw": "<玩家原话>"}

只能使用候选列表里明确存在的 id，绝不允许编造不存在的 id。"""


class LLMIntentParser:
    """真实实现——通过 DeepSeek(兼容 OpenAI SDK) 解析,输出必须是 Intent 判别式联合类型之一。"""

    async def parse_intent(self, utterance: str, view: PlayerView, menu: SceneActionMenu) -> Intent:
        config = DEFAULT_MODEL_ROLE_CONFIGS["intent"]
        client = AsyncOpenAI(api_key=get_api_key(config.provider), base_url=PROVIDER_BASE_URLS[config.provider])

        candidates = {
            "entities": [{"id": e.id, "name": e.name} for e in menu.entities],
            "exits": [{"sceneId": ex.scene_id, "title": ex.title} for ex in menu.exits],
        }
        user_content = (
            f"当前场景描述：{view.visible_scene_description}\n"
            f"可交互候选（只能用这里面的 id）：{json.dumps(candidates, ensure_ascii=False)}\n"
            f"玩家输入：{utterance}"
        )

        response = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        try:
            data = json.loads(raw)
            return _INTENT_ADAPTER.validate_python(data)
        except Exception:
            # 软判据求值失败（JSON 不合法/字段不符合任何 Intent 变体）→ 保底归为 unknown，
            # 触发 §6.6 脱本导回状态机，而不是让异常往上层炸穿
            return IntentUnknown(raw=utterance)
