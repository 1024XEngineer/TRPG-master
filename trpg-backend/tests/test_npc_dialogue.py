"""验证 NPC 对话的接收者边界、结构化输出和动作隔离。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from collaboration_framework.contracts import (
    ObservableStateView,
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleEntity,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.structured_http import StructuredOutputError
from app.core.config import Settings
from app.models.event import Event, EventAudience
from app.service import room as room_service
from app.service.npc_dialogue import (
    FakeNpcDialogueModel,
    NpcDialogueContext,
    NpcDialogueMessage,
    NpcDialogueOutput,
    NpcPublicSnapshot,
    PromptNpcDialogueModel,
    build_npc_dialogue_service,
    require_dialogue_npc,
    visible_dialogue_npcs,
)
from tests.test_engine_runtime import _start_room


def _view() -> PlayerView:
    """构造只含公开身份和三名可见实体的玩家视图。"""

    return PlayerView(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        background="测试场景",
        scene_id="cemetery",
        phase="playing",
        revision="revision-9",
        self_actor=SelfActorView(
            id="actor-1",
            name="林岚",
            public_status_summary="站在墓园入口。",
        ),
        scene=SceneView(
            id="cemetery",
            name="旧墓园",
            description="石碑间雾气低垂。",
            visible_entities=(
                VisibleEntity(
                    id="caretaker",
                    kind="npc",
                    name="守墓人",
                    aliases=("老人",),
                    description="沉默寡言的守墓人。",
                ),
                VisibleEntity(
                    id="sleeping-witness",
                    kind="npc",
                    name="昏迷的目击者",
                    description="倒在长椅上。",
                    observable_state=(
                        ObservableStateView(
                            key="consciousness",
                            label="意识",
                            value="unconscious",
                        ),
                    ),
                ),
                VisibleEntity(
                    id="gate",
                    kind="object",
                    name="铁门",
                    description="生锈的铁门。",
                ),
            ),
        ),
    )


def test_visible_dialogue_npcs_rejects_non_npc_and_unconscious() -> None:
    view = _view()

    assert [item.id for item in visible_dialogue_npcs(view)] == ["caretaker"]
    assert require_dialogue_npc(view, "caretaker").name == "守墓人"
    with pytest.raises(ValueError, match="无法对话"):
        require_dialogue_npc(view, "sleeping-witness")
    with pytest.raises(ValueError, match="无法对话"):
        require_dialogue_npc(view, "gate")


def test_npc_output_enforces_message_and_character_budgets() -> None:
    with pytest.raises(ValidationError):
        NpcDialogueOutput(npc_messages=())
    with pytest.raises(ValidationError):
        NpcDialogueOutput(
            npc_messages=tuple(
                NpcDialogueMessage(speaker_id=f"npc-{index}", text="回复") for index in range(4)
            )
        )
    with pytest.raises(ValidationError):
        NpcDialogueMessage(speaker_id="caretaker", text="字" * 1001)


def test_real_provider_lease_covers_timeout_retries_and_repair() -> None:
    """lease 按 Host provider 最坏调用窗口计算，不能固定早于模型超时。"""

    service = build_npc_dialogue_service(
        Settings(
            host_model_provider="qwen",
            qwen_api_key="test-key",
            qwen_timeout_seconds=120,
            model_client_max_attempts=5,
            model_client_retry_backoff_seconds=10,
        )
    )

    assert service.lease_seconds >= 1505


@pytest.mark.asyncio
async def test_fake_npc_treats_action_words_as_dialogue_only() -> None:
    """Fake 只生成一句 NPC 发言，不返回任何 Engine 效果或技能裁决。"""

    context = NpcDialogueContext(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        actor_name="林岚",
        scene_id="cemetery",
        scene_name="旧墓园",
        scene_description="石碑间雾气低垂。",
        interlocutor_id="caretaker",
        allowed_responders=(
            NpcPublicSnapshot(
                id="caretaker",
                name="守墓人",
                description="沉默寡言的守墓人。",
            ),
        ),
        utterance="我去地下室并使用侦查检查门。",
    )

    output = await FakeNpcDialogueModel().generate(context)

    assert output.npc_messages[0].speaker_id == "caretaker"
    assert "我去地下室并使用侦查检查门" in output.npc_messages[0].text
    assert set(output.model_dump()) == {"npc_messages"}


@pytest.mark.asyncio
async def test_prompt_model_repairs_illegal_speaker_once() -> None:
    """模型第一次添加场景外 NPC 时收到安全反馈，第二次只允许合法说话者。"""

    class RepairingClient:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        async def generate(self, **kwargs):
            self.payloads.append(kwargs["input_payload"])
            speaker = "offscene-npc" if len(self.payloads) == 1 else "caretaker"
            return {"npc_messages": [{"speaker_id": speaker, "text": "收到。"}]}

    context = NpcDialogueContext(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        actor_name="林岚",
        scene_id="cemetery",
        scene_name="旧墓园",
        scene_description="石碑间雾气低垂。",
        interlocutor_id="caretaker",
        allowed_responders=(NpcPublicSnapshot(id="caretaker", name="守墓人"),),
        utterance="请记住蓝色钟摆。",
    )
    client = RepairingClient()

    output = await PromptNpcDialogueModel(client).generate(context)  # type: ignore[arg-type]

    assert output.npc_messages[0].speaker_id == "caretaker"
    assert "validation_feedback" in client.payloads[1]


@pytest.mark.asyncio
async def test_prompt_model_repairs_invalid_json_once() -> None:
    """结构化 client 解码失败时立即进行一次受限修复，不进入 Engine。"""

    class InvalidOnceClient:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise StructuredOutputError("invalid json")
            assert "validation_feedback" in kwargs["input_payload"]
            return {"npc_messages": [{"speaker_id": "caretaker", "text": "收到。"}]}

    context = NpcDialogueContext(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        actor_name="林岚",
        scene_id="cemetery",
        scene_name="旧墓园",
        scene_description="石碑间雾气低垂。",
        interlocutor_id="caretaker",
        allowed_responders=(NpcPublicSnapshot(id="caretaker", name="守墓人"),),
        utterance="请记住蓝色钟摆。",
    )
    client = InvalidOnceClient()

    output = await PromptNpcDialogueModel(client).generate(context)  # type: ignore[arg-type]

    assert client.calls == 2
    assert output.npc_messages[0].speaker_id == "caretaker"


@pytest.mark.asyncio
async def test_scene_dialogue_replay_uses_frozen_audience(db_session: AsyncSession) -> None:
    """未在事件受众中的房间成员后来进入场景，也不能补看旧 NPC 对话。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=4072,
        player_count=2,
        prepare_checkpoint=False,
    )
    event = Event(
        id=str(uuid.uuid4()),
        room_id=room.id,
        player_id=players[0].id,
        event_type="dialogue.npc",
        correlation_id="frozen-audience:npc:0",
        visibility="scene_scoped",
        actor_id="caretaker",
        scene_id="cemetery",
        view_revision="revision-1",
        payload={
            "messageId": "npc-message-1",
            "speakerId": "caretaker",
            "speakerName": "守墓人",
            "listenerIds": ["actor-1"],
            "participantIds": ["caretaker", "actor-1"],
            "text": "只让当时在场的人听见。",
            "sceneId": "cemetery",
            "sourceDialogueId": "player-message-1",
            "sourceActionId": "action-1",
            "ordinal": 0,
            "sourceRevision": "revision-1",
            "sentAt": datetime.now(UTC).isoformat(),
            "audiencePlayerIds": [players[0].id],
        },
        created_at=datetime.now(UTC),
    )
    db_session.add(event)
    db_session.add(EventAudience(event_id=event.id, player_id=players[0].id))
    await db_session.commit()

    visible = await room_service.list_conversation_events(
        db_session,
        room.id,
        players[0].reconnect_token,
    )
    hidden = await room_service.list_conversation_events(
        db_session,
        room.id,
        players[1].reconnect_token,
    )

    assert [item.type for item in visible] == ["dialogue.npc"]
    assert hidden == []
