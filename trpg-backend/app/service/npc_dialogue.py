"""NPC 场景对话事件服务：冻结受众、持久化玩家原话和 NPC 回放。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from math import ceil

from collaboration_framework.contracts import JsonObject, PlayerView, VisibleEntity
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.openai_models import StructuredJsonClient
from app.adapters.structured_http import StructuredOutputError
from app.core.config import (
    Settings,
    get_settings,
    model_client_retry_policy,
)
from app.dto.ws import DialogueNpcPayload, DialoguePlayerPayload
from app.models.content import ModuleAsset
from app.models.engine import HostActionQueueItem
from app.models.event import Event, EventAudience
from app.models.room import Room

_DIALOGUE_INSTRUCTIONS = """你正在扮演当前场景中的 NPC，而不是全知守秘人。
只能依据输入中的公开场景、NPC 公开描述和最近对话回复，不得读取或编造隐藏模组内容、
玩家秘密、背包、线索或世界状态。玩家说要移动、检定、攻击或使用物品时，只把它当成
NPC 听到的一句话；不得裁决行动已经发生。输出 1 至 3 条 NPC 回复，主要 NPC 必须第一条，
speaker_id 只能从 allowed_responders 逐字复制。只输出符合 JSON schema 的 JSON。"""


class NpcDialogueMessage(BaseModel):
    """结构化模型输出中的单条 NPC 发言。"""

    speaker_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1000)


class NpcDialogueOutput(BaseModel):
    """限制模型一次最多生成三名 NPC 的有序回复。"""

    npc_messages: tuple[NpcDialogueMessage, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_total_budget(self) -> NpcDialogueOutput:
        if sum(len(item.text) for item in self.npc_messages) > 2400:
            raise ValueError("NPC 回复总长度不能超过 2400 字")
        return self


class NpcPublicSnapshot(BaseModel):
    """模型可见的 NPC 公开快照。"""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    observable_state: tuple[dict[str, object], ...] = ()


class RecentDialogueItem(BaseModel):
    """当前 viewer 有权读取且涉及主要 NPC 的近期对话。"""

    speaker_id: str
    speaker_name: str
    text: str


class NpcDialogueContext(BaseModel):
    """严格的玩家安全 NPC 模型输入，不包含 Keeper 能力或 Engine 写能力。"""

    room_id: str
    player_id: str
    actor_id: str
    actor_name: str
    actor_public_status: str = ""
    scene_id: str
    scene_name: str
    scene_description: str
    interlocutor_id: str
    allowed_responders: tuple[NpcPublicSnapshot, ...]
    recent_dialogue: tuple[RecentDialogueItem, ...] = ()
    utterance: str


class FakeNpcDialogueModel:
    """测试和本地试玩使用的确定性 Host 替身。"""

    async def generate(self, context: NpcDialogueContext) -> NpcDialogueOutput:
        primary = next(
            item for item in context.allowed_responders if item.id == context.interlocutor_id
        )
        return NpcDialogueOutput(
            npc_messages=(
                NpcDialogueMessage(
                    speaker_id=primary.id,
                    text=f"{context.actor_name}，我听见了：{context.utterance}",
                ),
            )
        )


class PromptNpcDialogueModel:
    """复用现有 StructuredJsonClient 的真实 NPC 对话模型适配器。"""

    def __init__(self, client: StructuredJsonClient) -> None:
        self._client = client

    async def generate(self, context: NpcDialogueContext) -> NpcDialogueOutput:
        payload: JsonObject = context.model_dump(mode="json")
        error_feedback: str | None = None
        for attempt in range(2):
            try:
                raw = await self._client.generate(
                    schema_name="trpg_npc_dialogue",
                    schema=NpcDialogueOutput.model_json_schema(mode="serialization"),
                    instructions=_DIALOGUE_INSTRUCTIONS,
                    input_payload=(
                        payload
                        if error_feedback is None
                        else {**payload, "validation_feedback": error_feedback}
                    ),
                )
            except StructuredOutputError as exc:
                if attempt == 1:
                    raise ValueError("NPC 模型连续返回非法 JSON") from exc
                error_feedback = "上次响应不是合法 JSON，请只输出符合 schema 的 JSON 对象。"
                continue
            try:
                output = NpcDialogueOutput.model_validate(raw)
                allowed_ids = {item.id for item in context.allowed_responders}
                if output.npc_messages[0].speaker_id != context.interlocutor_id:
                    raise ValueError("主要 NPC 必须第一条回复")
                if any(item.speaker_id not in allowed_ids for item in output.npc_messages):
                    raise ValueError("speaker_id 不在 allowed_responders 中")
                return output
            except (ValidationError, ValueError) as exc:
                if attempt == 1:
                    raise ValueError("NPC 模型输出不符合契约") from exc
                # 只反馈契约错误，不回显私密数据或扩大模型权限。
                error_feedback = (
                    "上次输出未满足消息数量、顺序、speaker_id 或长度约束，请仅修复 JSON。"
                )
        raise AssertionError("unreachable")


def _is_available_npc(entity: VisibleEntity) -> bool:
    """NPC 必须可见且有意识；未知状态按可对话处理。"""

    if entity.kind != "npc":
        return False
    consciousness = next(
        (state.value for state in entity.observable_state if state.key == "consciousness"),
        None,
    )
    return consciousness not in {"dead", "unconscious"}


def visible_dialogue_npcs(view: PlayerView) -> tuple[VisibleEntity, ...]:
    """返回服务端允许绑定为结构化接收者的当前 NPC。"""

    return tuple(entity for entity in view.scene.visible_entities if _is_available_npc(entity))


def require_dialogue_npc(view: PlayerView, entity_id: str) -> VisibleEntity:
    """按稳定 ID 验证 NPC，绝不根据自然语言名称猜测。"""

    npc = next((item for item in visible_dialogue_npcs(view) if item.id == entity_id), None)
    if npc is None:
        raise ValueError("该 NPC 当前不可见、已失去意识或无法对话")
    return npc


class NpcDialogueService:
    """只负责 NPC 对话事件的持久化、受众冻结和回放恢复。"""

    def __init__(self, *, lease_seconds: int = 180) -> None:
        self.lease_seconds = max(180, lease_seconds)

    async def portrait_url(
        self,
        db: AsyncSession,
        *,
        room_id: str,
        entity_id: str,
    ) -> str | None:
        """按稳定实体 ID 查 NPC 头像；未映射时由前端使用默认头像。"""

        scenario_id = await db.scalar(select(Room.scenario_id).where(Room.id == room_id))
        if scenario_id is None:
            return None
        return await db.scalar(
            select(ModuleAsset.url).where(
                ModuleAsset.scenario_id == scenario_id,
                ModuleAsset.entity_id == entity_id,
                ModuleAsset.asset_type == "npc_portrait",
            )
        )

    async def persist_player_event(
        self,
        db: AsyncSession,
        *,
        item: HostActionQueueItem,
        view: PlayerView,
        audience_player_ids: tuple[str, ...],
        nickname: str,
    ) -> Event:
        """幂等保存玩家原话和冻结受众；已有 correlation 直接复用。"""

        correlation = f"{item.client_action_id}:player"
        existing = await db.scalar(
            select(Event).where(
                Event.room_id == item.room_id,
                Event.event_type == "dialogue.player",
                Event.correlation_id == correlation,
            )
        )
        if existing is not None:
            return existing
        primary = require_dialogue_npc(view, item.recipient_entity_id or "")
        responders = visible_dialogue_npcs(view)
        now = datetime.now(UTC)
        event = Event(
            id=str(uuid.uuid4()),
            room_id=item.room_id,
            player_id=item.player_id,
            event_type="dialogue.player",
            correlation_id=correlation,
            visibility="scene_scoped",
            actor_id=item.actor_id,
            scene_id=view.scene.id,
            view_revision=view.revision,
            created_at=now,
            payload={},
        )
        payload = DialoguePlayerPayload(
            message_id=event.id,
            player_id=item.player_id,
            client_action_id=item.client_action_id,
            nickname=nickname,
            character_name=view.self_actor.name,
            speaker_id=item.actor_id,
            interlocutor_id=primary.id,
            interlocutor_name=primary.name,
            listener_ids=tuple(npc.id for npc in responders),
            participant_ids=(item.actor_id, *(npc.id for npc in responders)),
            allowed_responder_ids=tuple(npc.id for npc in responders),
            utterance=item.utterance,
            scene_id=view.scene.id,
            source_revision=view.revision,
            sent_at=now,
            audience_player_ids=audience_player_ids,
        )
        event.payload = payload.model_dump(by_alias=True, mode="json")
        db.add(event)
        db.add_all(
            EventAudience(event_id=event.id, player_id=target_id)
            for target_id in audience_player_ids
        )
        await db.commit()
        await db.refresh(event)
        return event

    async def persist_player_dialogue(
        self,
        db: AsyncSession,
        *,
        view: PlayerView,
        player_id: str,
        actor_id: str,
        client_action_id: str,
        utterance: str,
        interlocutor_id: str,
        audience_player_ids: tuple[str, ...],
        nickname: str,
    ) -> Event:
        """把 @NPC 的原话落成 dialogue.player；回放时仍按冻结受众恢复。"""

        correlation = f"{client_action_id}:player"
        existing = await db.scalar(
            select(Event).where(
                Event.room_id == view.room_id,
                Event.event_type == "dialogue.player",
                Event.correlation_id == correlation,
            )
        )
        if existing is not None:
            return existing
        primary = require_dialogue_npc(view, interlocutor_id)
        responders = visible_dialogue_npcs(view)
        now = datetime.now(UTC)
        event = Event(
            id=str(uuid.uuid4()),
            room_id=view.room_id,
            player_id=player_id,
            event_type="dialogue.player",
            correlation_id=correlation,
            visibility="scene_scoped",
            actor_id=actor_id,
            scene_id=view.scene.id,
            view_revision=view.revision,
            created_at=now,
            payload={},
        )
        payload = DialoguePlayerPayload(
            message_id=event.id,
            player_id=player_id,
            client_action_id=client_action_id,
            nickname=nickname,
            character_name=view.self_actor.name,
            speaker_id=actor_id,
            interlocutor_id=primary.id,
            interlocutor_name=primary.name,
            listener_ids=tuple(npc.id for npc in responders),
            participant_ids=(actor_id, *(npc.id for npc in responders)),
            allowed_responder_ids=tuple(npc.id for npc in responders),
            utterance=utterance,
            scene_id=view.scene.id,
            source_revision=view.revision,
            sent_at=now,
            audience_player_ids=audience_player_ids,
        )
        event.payload = payload.model_dump(by_alias=True, mode="json")
        db.add(event)
        db.add_all(
            EventAudience(event_id=event.id, player_id=target_id)
            for target_id in audience_player_ids
        )
        await db.commit()
        await db.refresh(event)
        return event

    async def persist_replies(
        self,
        db: AsyncSession,
        *,
        item: HostActionQueueItem,
        view: PlayerView,
        player_event: Event,
        audience_player_ids: tuple[str, ...],
        output: NpcDialogueOutput,
        audience_actor_ids: tuple[str, ...],
    ) -> tuple[Event, ...]:
        """在一个事务中保存全部回复、受众和队列完成状态。"""

        names = {npc.id: npc.name for npc in visible_dialogue_npcs(view)}
        responders = tuple(names)
        events: list[Event] = []
        now = datetime.now(UTC)
        for ordinal, message in enumerate(output.npc_messages):
            correlation = f"{item.client_action_id}:npc:{ordinal}"
            existing = await db.scalar(
                select(Event).where(
                    Event.room_id == item.room_id,
                    Event.event_type == "dialogue.npc",
                    Event.correlation_id == correlation,
                )
            )
            if existing is not None:
                events.append(existing)
                continue
            # 同一批回复共享同一个事务时间窗，但重放时仍需要稳定顺序；因此在微秒级
            # 递增 created_at/sent_at，避免多个事件完全同秒时只能退化到随机 UUID 排序。
            sent_at = now + timedelta(microseconds=ordinal)
            event = Event(
                id=str(uuid.uuid4()),
                room_id=item.room_id,
                player_id=item.player_id,
                event_type="dialogue.npc",
                correlation_id=correlation,
                visibility="scene_scoped",
                actor_id=message.speaker_id,
                scene_id=view.scene.id,
                view_revision=view.revision,
                created_at=sent_at,
                payload={},
            )
            listeners = (
                *audience_actor_ids,
                *(npc for npc in responders if npc != message.speaker_id),
            )
            payload = DialogueNpcPayload(
                message_id=event.id,
                speaker_id=message.speaker_id,
                speaker_name=names[message.speaker_id],
                listener_ids=listeners,
                participant_ids=(message.speaker_id, *listeners),
                text=message.text,
                scene_id=view.scene.id,
                source_dialogue_id=player_event.id,
                source_action_id=item.client_action_id,
                ordinal=ordinal,
                source_revision=view.revision,
                sent_at=sent_at,
                audience_player_ids=audience_player_ids,
            )
            event.payload = payload.model_dump(by_alias=True, mode="json", exclude={"avatar_url"})
            db.add(event)
            db.add_all(
                EventAudience(event_id=event.id, player_id=target_id)
                for target_id in audience_player_ids
            )
            events.append(event)
        await db.flush()
        item.status = "completed"
        item.result_event_ids = [event.id for event in events]
        item.lease_owner = None
        item.lease_expires_at = None
        item.next_attempt_at = None
        item.updated_at = now
        await db.commit()
        return tuple(events)

    async def persist_scripted_replies(
        self,
        db: AsyncSession,
        *,
        room_id: str,
        player_id: str,
        client_action_id: str,
        view: PlayerView,
        source_dialogue_id: str,
        audience_player_ids: tuple[str, ...],
        audience_actor_ids: tuple[str, ...],
        npc_messages: tuple[tuple[str, str], ...],
    ) -> tuple[Event, ...]:
        """把守秘人回合后的结构化 NPC 跟进发言复用成 dialogue.npc 事件。"""

        names = {npc.id: npc.name for npc in visible_dialogue_npcs(view)}
        responders = tuple(names)
        events: list[Event] = []
        now = datetime.now(UTC)
        for ordinal, (speaker_id, text) in enumerate(npc_messages):
            if speaker_id not in names:
                # 只跳过这条越权回复，不把已经完成的守秘人结果回滚成失败。
                continue
            correlation = f"{client_action_id}:followup-npc:{ordinal}"
            existing = await db.scalar(
                select(Event).where(
                    Event.room_id == room_id,
                    Event.event_type == "dialogue.npc",
                    Event.correlation_id == correlation,
                )
            )
            if existing is not None:
                events.append(existing)
                continue
            sent_at = now + timedelta(microseconds=ordinal)
            event = Event(
                id=str(uuid.uuid4()),
                room_id=room_id,
                player_id=player_id,
                event_type="dialogue.npc",
                correlation_id=correlation,
                visibility="scene_scoped",
                actor_id=speaker_id,
                scene_id=view.scene.id,
                view_revision=view.revision,
                created_at=sent_at,
                payload={},
            )
            listeners = (
                *audience_actor_ids,
                *(npc_id for npc_id in responders if npc_id != speaker_id),
            )
            payload = DialogueNpcPayload(
                message_id=event.id,
                speaker_id=speaker_id,
                speaker_name=names[speaker_id],
                listener_ids=listeners,
                participant_ids=(speaker_id, *listeners),
                text=text,
                scene_id=view.scene.id,
                source_dialogue_id=source_dialogue_id,
                source_action_id=client_action_id,
                ordinal=ordinal,
                source_revision=view.revision,
                sent_at=sent_at,
                audience_player_ids=audience_player_ids,
            )
            event.payload = payload.model_dump(by_alias=True, mode="json", exclude={"avatar_url"})
            db.add(event)
            db.add_all(
                EventAudience(event_id=event.id, player_id=target_id)
                for target_id in audience_player_ids
            )
            events.append(event)
        await db.commit()
        return tuple(events)


def build_npc_dialogue_service(settings: Settings | None = None) -> NpcDialogueService:
    """按当前 Host provider 计算 lease，但不再构造独立 NPC 生成模型。"""

    resolved = settings or get_settings()
    if resolved.host_model_provider == "deepseek":
        timeout = resolved.deepseek_timeout_seconds
    elif resolved.host_model_provider == "qwen":
        timeout = resolved.qwen_timeout_seconds
    else:
        timeout = resolved.openai_timeout_seconds
    retry_policy = model_client_retry_policy(resolved)
    # 一次生成最多包含“原请求 + 一次结构修复”；lease 必须覆盖两次请求各自的
    # 传输重试和指数退避，避免慢模型尚未返回就被其他 worker 重复领取。
    request_window = timeout * retry_policy.max_attempts + sum(
        retry_policy.delay_before(attempt) for attempt in range(1, retry_policy.max_attempts)
    )
    lease_seconds = ceil(request_window * 2 + 5)
    return NpcDialogueService(lease_seconds=lease_seconds)


npc_dialogue_service = build_npc_dialogue_service()


__all__ = [
    "FakeNpcDialogueModel",
    "NpcDialogueContext",
    "NpcDialogueOutput",
    "NpcDialogueService",
    "build_npc_dialogue_service",
    "npc_dialogue_service",
    "require_dialogue_npc",
    "visible_dialogue_npcs",
]
