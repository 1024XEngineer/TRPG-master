"""Application service for deriving and generating a character portrait."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Protocol

import structlog
from collaboration_framework.contracts import ModuleContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.core.coc7_rules import evaluate_skill_base
from app.core.config import Settings, secret_value
from app.dto.game import RulesetRead
from app.dto.portrait import (
    CharacterPortraitSnapshot,
    PortraitGenerationRequest,
    PortraitGenerationResult,
    PortraitPrompt,
    PortraitSkillSnapshot,
)
from app.models.content import Scenario
from app.models.engine import ModuleVersion
from app.models.room import Character, Room
from app.service.room import (
    RoomAuthorizationError,
    find_room_by_id,
    get_player_by_reconnect_token,
    require_ruleset,
)

logger = structlog.get_logger()


class PortraitGenerationDisabledError(RuntimeError):
    pass


class PortraitCharacterNotFoundError(ValueError):
    pass


class PortraitCharacterIncompleteError(ValueError):
    pass


class PortraitGenerationInProgressError(RuntimeError):
    pass


class PortraitImageGenerationError(RuntimeError):
    pass


class PortraitImageContentRejectedError(PortraitImageGenerationError):
    pass


class PortraitImageTimeoutError(PortraitImageGenerationError):
    pass


@dataclass(frozen=True, slots=True)
class ImageGenerationOutput:
    image_url: str


class PortraitPromptComposer(Protocol):
    async def compose(self, snapshot: CharacterPortraitSnapshot) -> PortraitPrompt: ...


class ImageGenerationProvider(Protocol):
    async def generate(
        self, *, prompt: str, negative_prompt: str, size: str
    ) -> ImageGenerationOutput: ...


def _visual_traits(attributes: dict[str, int]) -> list[str]:
    traits: list[str] = []
    mappings = {
        "APP": ("外在吸引力较弱，气质朴素低调", "外貌与人格吸引力突出"),
        "SIZ": ("身形小巧紧凑", "体型较大，身形高大"),
        "STR": ("肌肉感不明显，力量感较弱", "体格强健，肌肉感明显"),
        "CON": ("面色疲惫，体质显得较弱", "气色健康，精力充沛"),
        "DEX": ("动作略显僵硬，身体控制力较弱", "姿态灵敏，动作控制精准"),
        "POW": ("神情略显犹疑，气场较弱", "目光坚定，意志感强烈"),
    }
    for key, (low_trait, high_trait) in mappings.items():
        value = attributes.get(key)
        if value is None:
            continue
        if value <= 35:
            traits.append(low_trait)
        elif value >= 70:
            traits.append(high_trait)
    return traits


def build_character_portrait_snapshot(
    character: Character,
    ruleset: RulesetRead,
    *,
    module_background: str = "",
) -> CharacterPortraitSnapshot:
    """Build the stable, visual-only input passed to prompt composers."""
    attributes = dict(character.attributes or {})
    occupation = next(
        (item for item in ruleset.occupations if item.name == character.occupation),
        None,
    )
    skills: list[PortraitSkillSnapshot] = []
    saved_skills = character.skills or {}
    for spec in ruleset.skills:
        current = saved_skills.get(spec.id)
        if current is None:
            continue
        base = evaluate_skill_base(spec.base, attributes)
        allocated = max(0, current - base)
        if allocated == 0:
            continue
        skills.append(
            PortraitSkillSnapshot(
                id=spec.id,
                name=spec.name,
                value=current,
                allocated=allocated,
            )
        )
    skills.sort(key=lambda item: (-item.allocated, -item.value, item.id))

    return CharacterPortraitSnapshot(
        character_id=character.id,
        name=character.name or "未命名角色",
        age=character.age,
        gender=character.gender,
        residence=character.residence or "",
        birthplace=character.birthplace or "",
        occupation=character.occupation,
        occupation_description=occupation.description if occupation else "",
        occupation_categories=list(occupation.categories) if occupation else [],
        attributes=attributes,
        visual_traits=_visual_traits(attributes),
        prominent_skills=skills[:5],
        equipment=list(character.equipment or []),
        background=character.background or "",
        module_background=module_background,
    )


async def _load_module_background(db: AsyncSession, room: Room) -> str:
    scenario_id = room.scenario_id
    module_version_name = room.module_version
    if not scenario_id or not module_version_name:
        return ""

    scenario = await db.get(Scenario, scenario_id)
    if scenario is None:
        return ""
    module_version = await db.get(
        ModuleVersion,
        (scenario.module_id, module_version_name),
    )
    if module_version is None:
        return ""
    try:
        module = ModuleContent.model_validate(module_version.content_json)
    except ValueError:
        return ""
    return module.background


class DeterministicPromptComposer:
    async def compose(self, snapshot: CharacterPortraitSnapshot) -> PortraitPrompt:
        identity = [f"{snapshot.age}岁" if snapshot.age is not None else "成年人"]
        if snapshot.gender:
            identity.append(snapshot.gender)
        if snapshot.occupation:
            identity.append(snapshot.occupation)

        facts: list[str] = []
        if snapshot.visual_traits:
            facts.append("外形特征：" + "、".join(snapshot.visual_traits))
        if snapshot.occupation_description:
            facts.append("职业背景：" + snapshot.occupation_description)
        if snapshot.prominent_skills:
            facts.append(
                "主要受训技能：" + "、".join(skill.name for skill in snapshot.prominent_skills)
            )
        if snapshot.equipment:
            facts.append("适合出现在画面中的装备：" + "、".join(snapshot.equipment))
        if snapshot.birthplace or snapshot.residence:
            facts.append(
                "地域背景：" + "、".join(filter(None, [snapshot.birthplace, snapshot.residence]))
            )
        if snapshot.background:
            facts.append("人物背景与明确形象描述（最高优先级）：" + snapshot.background[:1200])
        if snapshot.module_background:
            facts.append(
                "模组故事背景（只用于时代、地点和氛围）：" + snapshot.module_background[:1200]
            )

        positive = (
            "一名TRPG人物的写实方形半身单人肖像，身份信息："
            + "、".join(identity)
            + "。自然真实的面部细节，符合年代与职业的服装和道具，"
            "具有电影感但主体清晰的光线，背景简洁。"
            + " ".join(facts)
            + " 不要呈现角色姓名或任何可读文字。"
        )
        negative = (
            "多人画面，文字，字母，字幕，水印，标志，用户界面，装饰边框，"
            "重复肢体，手部畸形，面部扭曲，头部被裁切，低分辨率"
        )
        summary_parts = []
        if snapshot.occupation:
            summary_parts.append(f"职业：{snapshot.occupation}")
        if snapshot.visual_traits:
            summary_parts.append("属性影响：" + "、".join(snapshot.visual_traits))
        if snapshot.prominent_skills:
            summary_parts.append(
                "主要技能：" + "、".join(skill.name for skill in snapshot.prominent_skills)
            )
        if snapshot.equipment:
            summary_parts.append("装备：" + "、".join(snapshot.equipment))
        if snapshot.background:
            summary_parts.append("已优先参考背景故事中的形象描述")
        if snapshot.module_background:
            summary_parts.append("已参考当前模组的时代、地点与叙事氛围")
        summary = "；".join(summary_parts) or "根据角色基本信息生成写实肖像"
        return PortraitPrompt(
            positive_prompt=positive[:3000],
            negative_prompt=negative,
            prompt_summary=summary[:1000],
            source="deterministic",
        )


class PortraitGenerationService:
    def __init__(
        self,
        *,
        enabled: bool,
        prompt_composer: PortraitPromptComposer,
        fallback_prompt_composer: PortraitPromptComposer,
        image_provider: ImageGenerationProvider,
    ) -> None:
        self._enabled = enabled
        self._prompt_composer = prompt_composer
        self._fallback_prompt_composer = fallback_prompt_composer
        self._image_provider = image_provider
        self._in_flight: set[tuple[str, str]] = set()
        self._in_flight_lock = asyncio.Lock()

    async def generate(
        self,
        db: AsyncSession,
        room_id: str,
        character_id: str,
        reconnect_token: str | None,
        payload: PortraitGenerationRequest,
    ) -> PortraitGenerationResult:
        if not self._enabled:
            raise PortraitGenerationDisabledError("角色图片生成功能未开启")

        player = await get_player_by_reconnect_token(db, reconnect_token)
        character = await db.get(Character, character_id)
        if character is None or character.room_id != room_id:
            raise PortraitCharacterNotFoundError("角色不存在")
        if character.player_id != player.id:
            raise RoomAuthorizationError("不能为其他玩家的角色生成图片")
        if character.status != "complete":
            raise PortraitCharacterIncompleteError("请先完成建卡再生成角色图片")

        room = await find_room_by_id(db, room_id)
        ruleset = (
            await require_ruleset(db, room.system_id)
            if room.system_id is not None
            else build_coc7_ruleset()
        )

        key = (room_id, character_id)
        async with self._in_flight_lock:
            if key in self._in_flight:
                raise PortraitGenerationInProgressError("该角色的图片正在生成")
            self._in_flight.add(key)

        try:
            module_background = await _load_module_background(db, room)
            snapshot = build_character_portrait_snapshot(
                character,
                ruleset,
                module_background=module_background,
            )
            try:
                prompt = await self._prompt_composer.compose(snapshot)
            except Exception as exc:
                logger.warning(
                    "portrait_prompt_fallback",
                    character_id=character_id,
                    error_type=type(exc).__name__,
                )
                prompt = await self._fallback_prompt_composer.compose(snapshot)
                prompt = prompt.model_copy(update={"source": "deterministic_fallback"})

            output = await self._image_provider.generate(
                prompt=prompt.positive_prompt,
                negative_prompt=prompt.negative_prompt,
                size=payload.size,
            )
            return PortraitGenerationResult(
                generation_id=str(uuid.uuid4()),
                image_url=output.image_url,
                prompt=prompt.positive_prompt,
                negative_prompt=prompt.negative_prompt,
                prompt_summary=prompt.prompt_summary,
                prompt_source=prompt.source,
            )
        finally:
            async with self._in_flight_lock:
                self._in_flight.discard(key)


def build_portrait_generation_service(settings: Settings) -> PortraitGenerationService:
    from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
    from app.adapters.image_generation import (
        DashScopeImageProvider,
        MockImageProvider,
        SufyImageProvider,
    )
    from app.adapters.portrait_prompt import DeepSeekPortraitPromptComposer

    fallback = DeterministicPromptComposer()
    prompt_composer: PortraitPromptComposer = fallback
    if settings.portrait_prompt_provider == "deepseek" and settings.deepseek_api_key:
        prompt_composer = DeepSeekPortraitPromptComposer(
            DeepSeekChatCompletionsJsonClient(
                api_key=secret_value(settings.deepseek_api_key),
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
            )
        )

    image_provider: ImageGenerationProvider = MockImageProvider()
    # provider 按配置互斥选择；真实服务失败时不自动切换其他 provider，
    # 以免隐藏错误或对同一次玩家操作重复计费。
    if settings.portrait_image_provider == "dashscope" and settings.dashscope_api_key:
        image_provider = DashScopeImageProvider(
            api_key=secret_value(settings.dashscope_api_key),
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_image_model,
            timeout_seconds=settings.portrait_generation_timeout_seconds,
        )
    elif settings.portrait_image_provider == "sufy" and settings.sufy_api_key:
        image_provider = SufyImageProvider(
            api_key=secret_value(settings.sufy_api_key),
            base_url=settings.sufy_base_url,
            model=settings.sufy_image_model,
            timeout_seconds=settings.portrait_generation_timeout_seconds,
        )

    return PortraitGenerationService(
        enabled=settings.character_portrait_enabled,
        prompt_composer=prompt_composer,
        fallback_prompt_composer=fallback,
        image_provider=image_provider,
    )
