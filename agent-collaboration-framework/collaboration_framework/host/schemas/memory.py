"""玩家安全的长期记忆与对话摘要契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import ContractModel

MemoryKind = Literal[
    "action",
    "visit",
    "conversation",
    "clue",
    "world_event",
    "relationship_change",
    "goal",
]
MemoryEpistemicStatus = Literal[
    "confirmed", "experienced", "heard", "asserted", "presentation"
]
MemoryVisibility = Literal["public", "player_scoped", "entity_scoped"]


class MemoryEntry(ContractModel):
    """一条可追溯、只读的长期经历投影。"""

    memory_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    object_id: str | None = None
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=2000)
    epistemic_status: MemoryEpistemicStatus
    visibility: MemoryVisibility
    participants: tuple[str, ...] = ()
    # 明确在场并听到该互动的实体；空值表示系统无法证明听众。
    listener_ids: tuple[str, ...] = ()
    location_id: str | None = None
    source_event_id: str = Field(min_length=1)
    source_sequence: int = Field(ge=0)
    source_revision: str | None = None


class ConversationSummary(ContractModel):
    """当前玩家可见的玩家与主持对话滚动摘要。"""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    summary: str = Field(default="", max_length=6000)
    unresolved_questions: tuple[str, ...] = ()
    important_entities: tuple[str, ...] = ()
    through_event_sequence: int = Field(default=0, ge=0)
    source_revision: str | None = None
    source_event_ids: tuple[str, ...] = ()


class MemoryContext(ContractModel):
    """绑定当前玩家作用域的有限长期记忆和对话摘要。"""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    as_of_revision: str = Field(min_length=1)
    entries: tuple[MemoryEntry, ...] = ()
    conversation_summary: ConversationSummary | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "MemoryContext":
        """拒绝跨房间或跨玩家的长期上下文拼接。"""
        for entry in self.entries:
            if entry.room_id != self.room_id:
                raise ValueError("MemoryEntry room_id 与当前上下文不一致")
        if self.conversation_summary is not None and (
            self.conversation_summary.room_id != self.room_id
            or self.conversation_summary.player_id != self.player_id
        ):
            raise ValueError("ConversationSummary scope 与当前上下文不一致")
        return self
