"""Deterministic no-network Intent model used by the integration fixture."""

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.schemas import IntentContext


class FakeIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
        text = context.player_input.utterance.lower()
        target = next(
            (
                entity
                for entity in context.player_view.visible_entities
                if any(
                    candidate and candidate.lower() in text
                    for candidate in (entity.id, entity.name, *entity.aliases)
                )
            ),
            None,
        )
        if target is None:
            return {
                "kind": "unknown",
                "verb": "unknown",
                "target": {"matched": False, "raw": context.player_input.utterance},
                "check": {"route": "none"},
                "approach": None,
                "summary": context.player_input.utterance,
                "clarification_question": "你想对当前场景中的哪个目标做什么？",
            }

        if any(word in text for word in ("聊", "问", "交谈", "说")):
            kind, verb = "dialogue", "talk"
        elif any(word in text for word in ("砸", "撞", "破坏")):
            kind, verb = "action", "smash"
        elif any(word in text for word in ("打开", "开柜", "用钥匙")):
            kind, verb = "action", "open"
        elif any(word in text for word in ("调查", "检查", "观察", "看看", "看")):
            kind, verb = "action", "investigate"
        else:
            kind, verb = "action", "interact"

        # This fake uses exact fixture hints. A production model adapter may use
        # semantic matching, but it must still choose only from this trusted menu.
        checkpoint = next(
            (
                option
                for option in context.player_view.checkpoint_options
                if option.target_id == target.id and option.action_hint == verb
            ),
            None,
        )
        check: JsonObject
        if checkpoint is None:
            check = {"route": "none"}
        else:
            check = {
                "route": "module",
                "checkpoint_id": checkpoint.id,
                "proposed_skills": list(checkpoint.skills),
            }
        return {
            "kind": kind,
            "verb": verb,
            "target": {"matched": True, "id": target.id},
            "check": check,
            "approach": context.player_input.utterance,
            "summary": context.player_input.utterance,
            "clarification_question": None,
        }
