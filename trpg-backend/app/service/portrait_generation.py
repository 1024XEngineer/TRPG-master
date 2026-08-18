"""Application service for deriving and generating a character portrait."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import structlog
from collaboration_framework.contracts import ModuleContent, ModuleContentV3
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.coc7_content import build_coc7_ruleset
from app.core.coc7_rules import evaluate_skill_base
from app.core.config import Settings, model_client_retry_policy, secret_value
from app.core.db import async_session_factory
from app.dto.game import RulesetRead
from app.dto.portrait import (
    CharacterPortraitSnapshot,
    PortraitGenerationRequest,
    PortraitGenerationTaskRead,
    PortraitPrompt,
    PortraitSkillSnapshot,
)
from app.models.content import Scenario
from app.models.engine import ModuleVersion
from app.models.room import Character, CharacterPortrait, Player, PortraitGenerationTask, Room
from app.models.user import UserCharacterTemplate, UserCharacterTemplatePortrait
from app.service.portrait_reference import PortraitReferenceImage, load_portrait_reference_image
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


class PortraitGenerationCancelled(RuntimeError):
    """后台执行器内部使用的取消信号，不直接暴露给 API。"""

    pass


@dataclass(frozen=True, slots=True)
class ImageGenerationOutput:
    image_url: str


@dataclass(frozen=True, slots=True)
class StoredPortrait:
    """头像读取接口所需的最小结果，不包含角色卡或生成提示词。"""

    content: bytes
    content_type: str
    content_hash: str


async def _sync_template_portrait(
    db: AsyncSession,
    character: Character,
    image: MaterializedPortrait,
    now: datetime,
) -> None:
    """将模板派生角色的最新头像回写到其账号级角色卡。"""
    if character.based_on_template_id is None:
        return
    user_id = await db.scalar(select(Player.user_id).where(Player.id == character.player_id))
    if user_id is None:
        return
    template = await db.scalar(
        select(UserCharacterTemplate)
        .where(
            UserCharacterTemplate.id == character.based_on_template_id,
            UserCharacterTemplate.user_id == user_id,
        )
        .with_for_update()
    )
    if template is None:
        return
    portrait = await db.get(UserCharacterTemplatePortrait, template.id)
    if portrait is None:
        db.add(
            UserCharacterTemplatePortrait(
                template_id=template.id,
                content=image.content,
                content_type=image.content_type,
                size_bytes=len(image.content),
                content_hash=image.content_hash,
                created_at=now,
                updated_at=now,
            )
        )
        return
    portrait.content = image.content
    portrait.content_type = image.content_type
    portrait.size_bytes = len(image.content)
    portrait.content_hash = image.content_hash
    portrait.updated_at = now


class PortraitPromptComposer(Protocol):
    async def compose(self, snapshot: CharacterPortraitSnapshot) -> PortraitPrompt: ...


class ImageGenerationProvider(Protocol):
    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput: ...


class ImageGenerationControl:
    """把上游任务 ID 安全回写数据库，并向 provider 传递取消状态。"""

    def __init__(
        self, generation_id: str, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.generation_id = generation_id
        self.cancelled = asyncio.Event()
        self._session_factory = session_factory

    async def set_provider_task_id(self, task_id: str) -> None:
        async with self._session_factory() as db:
            await db.execute(
                update(PortraitGenerationTask)
                .where(PortraitGenerationTask.generation_id == self.generation_id)
                .values(provider_task_id=task_id, updated_at=datetime.now(UTC))
            )
            await db.commit()


class ControlledImageGenerationProvider(Protocol):
    """新版 provider 可选协议；旧 provider 仍按基础协议正常工作。"""

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
        control: ImageGenerationControl | None = None,
    ) -> ImageGenerationOutput: ...


class MaterializedPortrait(Protocol):
    @property
    def content(self) -> bytes: ...

    @property
    def content_type(self) -> str: ...

    @property
    def content_hash(self) -> str: ...


class PortraitImageMaterializerProtocol(Protocol):
    async def materialize(self, image_url: str) -> MaterializedPortrait: ...


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
        if module_version.content_schema_version == 3:
            module_v3 = ModuleContentV3.model_validate(module_version.content_json)
            profile = module_v3.world_profile
            return "；".join(part for part in (profile.era, profile.region, profile.tone) if part)
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
            "偏漫画风格的精致角色立绘，清晰细致的线稿，轻厚涂与柔和赛璐璐上色，"
            "优雅的漫画角色插画质感，方形构图，腰部以上，人物居中，单人肖像，"
            "人物与背景铺满整个画布，背景自然延伸至四边，无边框无留白，身份信息："
            + "、".join(identity)
            + "。自然细腻的面部细节，符合年代与职业的服装和道具，"
            "柔和暖色光影，主体清晰，背景简洁。"
            + " ".join(facts)
            + " 严格保持参考图的绘画风格，但只借鉴线稿、上色、光影和插画完成度；"
            "不要复制参考图人物、金色卷发、绿色眼睛、绿色礼服、白色花饰、珠宝、蜡烛、"
            "书架、书房、姿势或构图。画面必须满幅，不要画框、卡纸、纸张边缘或画中画。"
            "不要呈现角色姓名或任何可读文字。"
        )
        negative = (
            "多人画面，文字，字母，字幕，水印，标志，用户界面，装饰边框，相框，卡纸，"
            "纸张边缘，空白页边，内框，外框，黑色描边框，相片边框，海报版式，画中画，"
            "重复肢体，手部畸形，面部扭曲，头部被裁切，低分辨率，照片写实，摄影棚照片"
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
        summary = "；".join(summary_parts) or "根据角色基本信息生成漫画风格肖像"
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
        image_materializer: PortraitImageMaterializerProtocol,
        reference_image: PortraitReferenceImage | None = None,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ) -> None:
        self._enabled = enabled
        self._prompt_composer = prompt_composer
        self._fallback_prompt_composer = fallback_prompt_composer
        self._image_provider = image_provider
        self._image_materializer = image_materializer
        self._reference_image = reference_image
        self._session_factory = session_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._controls: dict[str, ImageGenerationControl] = {}
        self._stopping = False

    def set_session_factory_for_testing(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """测试环境显式注入隔离数据库，避免后台协程绕过 FastAPI 依赖覆盖。"""
        self._session_factory = session_factory

    @staticmethod
    def _read(task: PortraitGenerationTask) -> PortraitGenerationTaskRead:
        return PortraitGenerationTaskRead.model_validate(task, from_attributes=True)

    async def create(
        self,
        db: AsyncSession,
        room_id: str,
        character_id: str,
        reconnect_token: str | None,
        payload: PortraitGenerationRequest,
    ) -> PortraitGenerationTaskRead:
        """验证归属并提交 queued 记录；提交成功后才允许调度后台执行。"""
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

        try:
            now = datetime.now(UTC)
            task = PortraitGenerationTask(
                generation_id=str(uuid.uuid4()),
                room_id=room_id,
                character_id=character_id,
                player_id=player.id,
                status="queued",
                cancel_requested=False,
                style=payload.style,
                size=payload.size,
                created_at=now,
                updated_at=now,
            )
            db.add(task)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise PortraitGenerationInProgressError("该角色的图片正在生成") from exc
        snapshot = self._read(task)
        self.schedule(task.generation_id)
        return snapshot

    def schedule(self, generation_id: str) -> None:
        """登记进程内协程；数据库唯一索引而非该字典负责并发正确性。"""
        if self._stopping or generation_id in self._tasks:
            return
        task = asyncio.create_task(self._run(generation_id), name=f"portrait-{generation_id}")
        self._tasks[generation_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(generation_id, None))

    async def get_current(
        self, db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
    ) -> PortraitGenerationTaskRead | None:
        await self._authorize_character(db, room_id, character_id, reconnect_token)
        task = await db.scalar(
            select(PortraitGenerationTask)
            .where(
                PortraitGenerationTask.room_id == room_id,
                PortraitGenerationTask.character_id == character_id,
            )
            .order_by(PortraitGenerationTask.created_at.desc())
            .limit(1)
        )
        return self._read(task) if task else None

    async def get_task(
        self,
        db: AsyncSession,
        room_id: str,
        character_id: str,
        generation_id: str,
        reconnect_token: str | None,
    ) -> PortraitGenerationTaskRead:
        await self._authorize_character(db, room_id, character_id, reconnect_token)
        task = await db.get(PortraitGenerationTask, generation_id)
        if task is None or task.room_id != room_id or task.character_id != character_id:
            raise PortraitCharacterNotFoundError("生图任务不存在")
        return self._read(task)

    async def cancel(
        self,
        db: AsyncSession,
        room_id: str,
        character_id: str,
        generation_id: str,
        reconnect_token: str | None,
    ) -> PortraitGenerationTaskRead:
        """先提交权威取消状态，再尽力中断本地与上游任务。"""
        await self._authorize_character(db, room_id, character_id, reconnect_token)
        task = await db.scalar(
            select(PortraitGenerationTask)
            .where(PortraitGenerationTask.generation_id == generation_id)
            .with_for_update()
        )
        if task is None or task.room_id != room_id or task.character_id != character_id:
            raise PortraitCharacterNotFoundError("生图任务不存在")
        if task.status in {"completed", "failed", "cancelled"}:
            return self._read(task)
        now = datetime.now(UTC)
        task.cancel_requested = True
        task.updated_at = now
        if task.status == "queued":
            task.status = "cancelled"
            task.finished_at = now
        else:
            task.status = "cancelling"
        provider_task_id = task.provider_task_id
        await db.commit()
        snapshot = self._read(task)
        control = self._controls.get(generation_id)
        if control:
            control.cancelled.set()
        cancel_method = getattr(self._image_provider, "cancel", None)
        if provider_task_id and callable(cancel_method):
            try:
                await cancel_method(provider_task_id)
            except Exception:
                logger.warning("portrait_provider_cancel_failed", generation_id=generation_id)
        local_task = self._tasks.get(generation_id)
        if local_task and task.status == "cancelling":
            local_task.cancel()
        return snapshot

    async def _authorize_character(
        self, db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
    ) -> Character:
        player = await get_player_by_reconnect_token(db, reconnect_token)
        character = await db.get(Character, character_id)
        if character is None or character.room_id != room_id:
            raise PortraitCharacterNotFoundError("角色不存在")
        if character.player_id != player.id:
            raise RoomAuthorizationError("不能访问其他玩家的生图任务")
        return character

    async def _is_cancelled(self, generation_id: str) -> bool:
        async with self._session_factory() as db:
            task = await db.get(PortraitGenerationTask, generation_id)
            return (
                task is None or task.cancel_requested or task.status in {"cancelling", "cancelled"}
            )

    async def _run(self, generation_id: str) -> None:
        """后台流水线：每个数据库阶段使用独立短会话，外部 IO 不占事务。"""
        control = ImageGenerationControl(generation_id, self._session_factory)
        self._controls[generation_id] = control
        stage = "provider"
        try:
            async with self._session_factory() as db:
                task = await db.get(PortraitGenerationTask, generation_id)
                if task is None or task.status != "queued" or task.cancel_requested:
                    return
                task.status = "generating"
                task.started_at = task.updated_at = datetime.now(UTC)
                await db.commit()
            if await self._is_cancelled(generation_id):
                raise PortraitGenerationCancelled()
            async with self._session_factory() as db:
                task = await db.get(PortraitGenerationTask, generation_id)
                if task is None:
                    return
                character = await db.get(Character, task.character_id)
                room = await find_room_by_id(db, task.room_id)
                if character is None:
                    raise PortraitCharacterNotFoundError("角色不存在")
                ruleset = (
                    await require_ruleset(db, room.system_id)
                    if room.system_id
                    else build_coc7_ruleset()
                )
                background = await _load_module_background(db, room)
                portrait_snapshot = build_character_portrait_snapshot(
                    character, ruleset, module_background=background
                )
                size = task.size
            try:
                prompt = await self._prompt_composer.compose(portrait_snapshot)
            except Exception as exc:
                logger.warning(
                    "portrait_prompt_fallback",
                    generation_id=generation_id,
                    error_type=type(exc).__name__,
                )
                prompt = await self._fallback_prompt_composer.compose(portrait_snapshot)
                prompt = prompt.model_copy(update={"source": "deterministic_fallback"})
            async with self._session_factory() as db:
                task = await db.get(PortraitGenerationTask, generation_id)
                if task is None or task.cancel_requested:
                    raise PortraitGenerationCancelled()
                task.prompt_summary, task.prompt_source = prompt.prompt_summary, prompt.source
                task.updated_at = datetime.now(UTC)
                await db.commit()
            if "control" in inspect.signature(self._image_provider.generate).parameters:
                controlled = cast(ControlledImageGenerationProvider, self._image_provider)
                output = await controlled.generate(
                    prompt=prompt.positive_prompt,
                    negative_prompt=prompt.negative_prompt,
                    size=size,
                    reference_image=self._reference_image,
                    control=control,
                )
            else:
                # 兼容仓库内已有的第三方/测试 provider；新版实现应接收 control。
                output = await self._image_provider.generate(
                    prompt=prompt.positive_prompt,
                    negative_prompt=prompt.negative_prompt,
                    size=size,
                    reference_image=self._reference_image,
                )
            if await self._is_cancelled(generation_id):
                raise PortraitGenerationCancelled()
            stage = "materialization"
            materialized = await self._image_materializer.materialize(output.image_url)
            if await self._is_cancelled(generation_id):
                raise PortraitGenerationCancelled()
            await self._complete(generation_id, materialized)
        except asyncio.CancelledError:
            # 进程关闭不是玩家取消：保留活动状态，交给下次启动标记 process_restarted。
            if not self._stopping:
                await self._finish_cancelled(generation_id)
        except PortraitGenerationCancelled:
            await self._finish_cancelled(generation_id)
        except PortraitImageContentRejectedError:
            await self._fail(generation_id, "content_rejected")
        except PortraitImageTimeoutError:
            await self._fail(generation_id, "timeout")
        except Exception:
            logger.exception("portrait_generation_failed", generation_id=generation_id)
            await self._fail(
                generation_id,
                "materialization_failed" if stage == "materialization" else "provider_failed",
            )
        finally:
            self._controls.pop(generation_id, None)

    async def _complete(self, generation_id: str, image: MaterializedPortrait) -> None:
        """条件抢占完成权并在同一事务替换头像；取消先提交则不产生写入。"""
        async with self._session_factory() as db:
            task = await db.scalar(
                select(PortraitGenerationTask)
                .where(PortraitGenerationTask.generation_id == generation_id)
                .with_for_update()
            )
            if task is None or task.status != "generating" or task.cancel_requested:
                await db.rollback()
                await self._finish_cancelled(generation_id)
                return
            now = datetime.now(UTC)
            # SQLite 的 FOR UPDATE 不提供真实行锁，因此必须先用条件 UPDATE 抢完成权；
            # 取消若已提交，rowcount 为 0，整个头像事务立即回滚。
            claimed = cast(
                CursorResult[Any],
                await db.execute(
                    update(PortraitGenerationTask)
                    .where(
                        PortraitGenerationTask.generation_id == generation_id,
                        PortraitGenerationTask.status == "generating",
                        PortraitGenerationTask.cancel_requested.is_(False),
                    )
                    .values(
                        status="completed",
                        portrait_version=image.content_hash,
                        finished_at=now,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if claimed.rowcount != 1:
                await db.rollback()
                await self._finish_cancelled(generation_id)
                return
            locked_character = await db.scalar(
                select(Character).where(Character.id == task.character_id).with_for_update()
            )
            if locked_character is None:
                await db.rollback()
                await self._fail(generation_id, "materialization_failed")
                return
            portrait = await db.get(CharacterPortrait, task.character_id)
            if portrait is None:
                portrait = CharacterPortrait(
                    character_id=task.character_id,
                    content=image.content,
                    content_type=image.content_type,
                    size_bytes=len(image.content),
                    content_hash=image.content_hash,
                    created_at=now,
                    updated_at=now,
                )
                db.add(portrait)
            else:
                portrait.content, portrait.content_type = image.content, image.content_type
                portrait.size_bytes, portrait.content_hash, portrait.updated_at = (
                    len(image.content),
                    image.content_hash,
                    now,
                )
            await _sync_template_portrait(db, locked_character, image, now)
            await db.commit()

    async def _finish_cancelled(self, generation_id: str) -> None:
        async with self._session_factory() as db:
            await db.execute(
                update(PortraitGenerationTask)
                .where(
                    PortraitGenerationTask.generation_id == generation_id,
                    PortraitGenerationTask.status.in_(("queued", "generating", "cancelling")),
                )
                .values(
                    status="cancelled",
                    cancel_requested=True,
                    finished_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            await db.commit()

    async def _fail(self, generation_id: str, failure_code: str) -> None:
        async with self._session_factory() as db:
            now = datetime.now(UTC)
            await db.execute(
                update(PortraitGenerationTask)
                .where(
                    PortraitGenerationTask.generation_id == generation_id,
                    PortraitGenerationTask.status.in_(("queued", "generating")),
                )
                .values(status="failed", failure_code=failure_code, finished_at=now, updated_at=now)
            )
            await db.commit()

    async def recover_interrupted(self) -> None:
        """启动时明确失败遗留活动任务，避免未知上游重复计费。"""
        async with self._session_factory() as db:
            now = datetime.now(UTC)
            await db.execute(
                update(PortraitGenerationTask)
                .where(
                    PortraitGenerationTask.status.in_(("queued", "generating", "cancelling")),
                )
                .values(
                    status="failed",
                    failure_code="process_restarted",
                    finished_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

    async def shutdown(self, timeout_seconds: float = 5.0) -> None:
        """有限等待本进程任务退出，遗留状态交给下次启动恢复。"""
        self._stopping = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout_seconds)

    @staticmethod
    async def get_player_portrait(
        db: AsyncSession,
        room_id: str,
        player_id: str,
        reconnect_token: str | None,
    ) -> StoredPortrait:
        """只允许房间成员读取同房间玩家的当前头像。"""
        requester = await get_player_by_reconnect_token(db, reconnect_token)
        if requester.room_id != room_id:
            raise RoomAuthorizationError("不能读取其他房间的角色头像")
        target = await db.get(Player, player_id)
        if target is None or target.room_id != room_id:
            raise PortraitCharacterNotFoundError("玩家不存在")
        row = await db.execute(
            select(
                CharacterPortrait.content,
                CharacterPortrait.content_type,
                CharacterPortrait.content_hash,
            )
            .join(Character, Character.id == CharacterPortrait.character_id)
            .where(Character.room_id == room_id, Character.player_id == player_id)
        )
        portrait = row.one_or_none()
        if portrait is None:
            raise PortraitCharacterNotFoundError("角色头像不存在")
        return StoredPortrait(
            content=portrait.content,
            content_type=portrait.content_type,
            content_hash=portrait.content_hash,
        )

    @staticmethod
    async def _replace_portrait(
        db: AsyncSession,
        character_id: str,
        image: MaterializedPortrait,
    ) -> None:
        """锁定角色后原子替换当前头像；提交失败时旧头像仍由事务回滚保留。"""
        try:
            locked_character = await db.scalar(
                select(Character).where(Character.id == character_id).with_for_update()
            )
            if locked_character is None:
                raise PortraitCharacterNotFoundError("角色不存在")
            portrait = await db.get(CharacterPortrait, character_id)
            now = datetime.now(UTC)
            if portrait is None:
                portrait = CharacterPortrait(
                    character_id=character_id,
                    content=image.content,
                    content_type=image.content_type,
                    size_bytes=len(image.content),
                    content_hash=image.content_hash,
                    created_at=now,
                    updated_at=now,
                )
                db.add(portrait)
            else:
                portrait.content = image.content
                portrait.content_type = image.content_type
                portrait.size_bytes = len(image.content)
                portrait.content_hash = image.content_hash
                portrait.updated_at = now
            await _sync_template_portrait(db, locked_character, image, now)
            await db.commit()
        except PortraitCharacterNotFoundError:
            await db.rollback()
            raise
        except SQLAlchemyError as exc:
            await db.rollback()
            raise PortraitImageGenerationError("角色头像保存失败") from exc


def build_portrait_generation_service(settings: Settings) -> PortraitGenerationService:
    """根据后端配置组装提示词和图片 provider，不在运行时隐式跨 provider 重试。"""

    from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
    from app.adapters.image_generation import (
        DashScopeImageProvider,
        MockImageProvider,
        SufyImageProvider,
    )
    from app.adapters.portrait_prompt import DeepSeekPortraitPromptComposer
    from app.service.portrait_image import PortraitImageMaterializer

    fallback = DeterministicPromptComposer()
    reference_image = load_portrait_reference_image(settings.portrait_reference_image_path)
    if settings.portrait_reference_image_path and reference_image is None:
        logger.warning("portrait_reference_unavailable")
    prompt_composer: PortraitPromptComposer = fallback
    if settings.portrait_prompt_provider == "deepseek" and settings.deepseek_api_key:
        prompt_composer = DeepSeekPortraitPromptComposer(
            DeepSeekChatCompletionsJsonClient(
                api_key=secret_value(settings.deepseek_api_key),
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                retry_policy=model_client_retry_policy(settings),
            )
        )

    provider_name = settings.portrait_image_provider
    if provider_name == "auto":
        # Sufy 是当前的高质量默认；只有它没有 Key 时才退到 DashScope，
        # 两者都没有时使用 mock，让开发者填一个需要的 Key 就能启用真实生图。
        if settings.sufy_api_key and secret_value(settings.sufy_api_key).strip():
            provider_name = "sufy"
        elif settings.dashscope_api_key and secret_value(settings.dashscope_api_key).strip():
            provider_name = "dashscope"
        else:
            provider_name = "mock"

    image_provider: ImageGenerationProvider = MockImageProvider()
    # 显式 provider 按配置互斥选择；真实服务失败时不自动切换其他 provider，
    # 以免隐藏错误或对同一次玩家操作重复计费。
    if provider_name == "dashscope" and settings.dashscope_api_key:
        image_provider = DashScopeImageProvider(
            api_key=secret_value(settings.dashscope_api_key),
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_image_model,
            timeout_seconds=settings.portrait_generation_timeout_seconds,
        )
    elif provider_name == "sufy" and settings.sufy_api_key:
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
        image_materializer=PortraitImageMaterializer(
            max_bytes=settings.portrait_max_image_bytes,
            timeout_seconds=settings.portrait_image_download_timeout_seconds,
        ),
        reference_image=reference_image,
    )
