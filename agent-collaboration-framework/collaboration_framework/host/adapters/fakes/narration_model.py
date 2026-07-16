"""Deterministic no-network narration model for offline integration tests."""

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.schemas import NarrationContext


class FakeNarrationModel:
    async def generate(self, context: NarrationContext) -> JsonObject:
        if context.action_result.resolution == "unrecognized":
            return {
                "kind": "clarification",
                "text": context.intent.clarification_question
                or "我没有理解这次行动，请换一种说法。",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        if context.action_result.visible_facts:
            return {
                "kind": "narration",
                "text": " ".join(fact.text for fact in context.action_result.visible_facts),
                "claimed_fact_ids": [
                    fact.id for fact in context.action_result.visible_facts
                ],
                "suggested_actions": [],
            }
        return {
            "kind": "narration",
            "text": "这个行动已经由规则边界处理。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }
