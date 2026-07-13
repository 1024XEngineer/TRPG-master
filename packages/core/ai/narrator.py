"""Narrator —— 对应 master §4.5，LLM，流式（5.2.2 narration.push streaming=true）。

旁白和 NPC 对话共用同一个类型/接口，靠 persona 参数区分（AI编排详细设计 §三：
分界线是"能不能被交互"，不是"是不是同一次模型调用"；MVP 阶段可共用同一个
底层模型配置）。
"""

from __future__ import annotations

from typing import AsyncIterator, Literal, Protocol, runtime_checkable

from openai import AsyncOpenAI

from core.ai.config import PROVIDER_BASE_URLS, DEFAULT_MODEL_ROLE_CONFIGS, get_api_key
from core.rules.models import ActionResult
from core.view.models import PlayerView

Persona = Literal["narrator", "npc", "qa"]


@runtime_checkable
class Narrator(Protocol):
    def narrate(self, persona: Persona, view: PlayerView, result: ActionResult) -> AsyncIterator[str]:
        ...


class StubNarrator:
    async def narrate(self, persona: Persona, view: PlayerView, result: ActionResult) -> AsyncIterator[str]:
        raise NotImplementedError("Narrator.narrate: 待接入 LLM（role='narrator'|'npc'）")
        yield ""  # pragma: no cover — 保留生成器签名形状


_SYSTEM_PROMPT = (
    "你是一款克苏鲁的呼唤(COC)桌游跑团的AI主持人(Keeper)。"
    "你的任务是把「场景描述」和「本次行动的裁决结果」转述成一段沉浸感强、"
    "略带诡异/悬疑氛围的旁白，第二人称或不带人称均可，2~4 句话，不要分点、"
    "不要加标题。只使用下面给你的信息演绎，不要编造未提及的具体线索内容或"
    "NPC底牌；如果行动没有命中任何预设内容(resolutionKind=improvised)，"
    "就用氛围化的描写带过，不要暗示这里一定有什么。"
)


def _build_user_content(view: PlayerView, result: ActionResult) -> str:
    lines = [f"当前场景描述：{view.visible_scene_description}"]
    if view.visible_clues:
        clue_lines = "；".join(f"{c.name}：{c.content}" for c in view.visible_clues if c.content)
        if clue_lines:
            lines.append(f"玩家已知线索：{clue_lines}")
    lines.append(f"本次行动结果摘要：{result.public_event_summary}")
    lines.append(f"裁决类型：{result.resolution_kind}")
    return "\n".join(lines)


class LLMNarrator:
    """真实实现——通过 DeepSeek(兼容 OpenAI SDK)流式生成旁白，见 config.py。"""

    async def narrate(self, persona: Persona, view: PlayerView, result: ActionResult) -> AsyncIterator[str]:
        config = DEFAULT_MODEL_ROLE_CONFIGS[persona]  # persona 与 ModelRole 在 narrator/npc/qa 三值上同名复用
        client = AsyncOpenAI(api_key=get_api_key(config.provider), base_url=PROVIDER_BASE_URLS[config.provider])

        stream = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_content(view, result)},
            ],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
