"""一键建卡背景与装备生成的组装、调用与确定性回退。"""

from dataclasses import dataclass
from typing import Protocol

import structlog

from app.core.config import Settings, model_client_retry_policy, secret_value
from app.dto.character_background import CharacterBackgroundContext, CharacterBackgroundDraft

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class CharacterBackgroundGeneration:
    background: str
    equipment: list[str]


class CharacterBackgroundComposer(Protocol):
    async def compose(self, context: CharacterBackgroundContext) -> CharacterBackgroundDraft: ...


class CharacterBackgroundService:
    def __init__(self, composer: CharacterBackgroundComposer | None = None) -> None:
        self._composer = composer

    async def generate(
        self,
        context: CharacterBackgroundContext,
        *,
        fallback: str,
        fallback_equipment: list[str],
    ) -> CharacterBackgroundGeneration:
        if self._composer is None:
            return CharacterBackgroundGeneration(fallback, list(fallback_equipment))
        try:
            draft = await self._composer.compose(context)
            return CharacterBackgroundGeneration(draft.to_character_background(), draft.equipment)
        except Exception as exc:
            logger.warning(
                "character_background_fallback",
                error_type=type(exc).__name__,
            )
            return CharacterBackgroundGeneration(fallback, list(fallback_equipment))


def build_character_background_service(settings: Settings) -> CharacterBackgroundService:
    if settings.character_background_provider != "deepseek":
        return CharacterBackgroundService()

    from app.adapters.character_background import DeepSeekCharacterBackgroundComposer
    from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient

    assert settings.deepseek_api_key is not None
    composer = DeepSeekCharacterBackgroundComposer(
        DeepSeekChatCompletionsJsonClient(
            api_key=secret_value(settings.deepseek_api_key),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            retry_policy=model_client_retry_policy(settings),
        )
    )
    return CharacterBackgroundService(composer)


__all__ = [
    "CharacterBackgroundComposer",
    "CharacterBackgroundGeneration",
    "CharacterBackgroundService",
    "build_character_background_service",
]
