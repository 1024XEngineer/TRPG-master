"""使用现有结构化 Provider 将玩家可见对话压缩为可追溯摘要。"""

from __future__ import annotations

from typing import Any

from collaboration_framework.host.schemas import ConversationSummary
from pydantic import ValidationError

from app.adapters.openai_models import StructuredJsonClient

_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "maxLength": 6000},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "important_entities": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
    },
    "required": ["summary", "unresolved_questions", "important_entities"],
}

_INSTRUCTIONS = """你是 TRPG 对话摘要器。只压缩输入中当前玩家可见的对话和已确认信息。
不要新增事实、地点、人物关系或行动结果。玩家没有被规则引擎确认的说法必须写成“玩家声称……”。
保留关键行动、主持人已经描述的事件、人物、地点、线索、当前目标和未解决问题。
只输出符合 JSON schema 的 JSON，不要输出 Markdown 或解释。"""


class ConversationSummaryModel:
    """Provider-neutral 的摘要模型适配器。"""

    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def summarize(
        self,
        *,
        room_id: str,
        player_id: str,
        previous: ConversationSummary | None,
        visible_events: tuple[dict[str, Any], ...],
        source_revision: str | None,
        through_event_sequence: int,
    ) -> ConversationSummary:
        """生成摘要后补回不可由模型修改的作用域、游标和来源信息。"""
        raw = await self._client.generate(
            schema_name="trpg_conversation_summary",
            schema=_SUMMARY_SCHEMA,
            instructions=_INSTRUCTIONS,
            input_payload={
                "previous_summary": previous.model_dump(mode="json") if previous else None,
                "visible_events": visible_events,
            },
        )
        try:
            return ConversationSummary(
                room_id=room_id,
                player_id=player_id,
                summary=str(raw.get("summary", "")),
                unresolved_questions=tuple(str(x) for x in raw.get("unresolved_questions", ())),
                important_entities=tuple(str(x) for x in raw.get("important_entities", ())),
                through_event_sequence=through_event_sequence,
                source_revision=source_revision,
                source_event_ids=tuple(
                    str(item.get("id"))
                    for item in visible_events
                    if isinstance(item.get("id"), str)
                ),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError("摘要模型输出不符合契约") from exc
