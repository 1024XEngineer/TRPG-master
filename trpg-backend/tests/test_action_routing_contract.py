"""PR1 输入路由 DTO 的结构化接收者契约测试。"""

import pytest
from pydantic import ValidationError

from app.dto.ws import ActionRecipientPayload, ActionSubmitPayload


def test_recipient_accepts_keeper_and_explicit_npc_shape() -> None:
    """Keeper 可隐式/显式使用，NPC 只能带实体 ID 且必须显式选择。"""

    assert ActionRecipientPayload(kind="keeper", explicit=False).entity_id is None
    assert ActionRecipientPayload(kind="keeper", explicit=True).entity_id is None
    assert (
        ActionRecipientPayload(kind="npc", entity_id=" thomas ", explicit=True).entity_id
        == "thomas"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "keeper", "entity_id": "thomas", "explicit": True},
        {"kind": "npc", "entity_id": None, "explicit": True},
        {"kind": "npc", "entity_id": "thomas", "explicit": False},
    ],
)
def test_recipient_rejects_ambiguous_shapes(payload: dict[str, object]) -> None:
    """非法 recipient 必须在 WebSocket 业务处理前被 Pydantic 拒绝。"""

    with pytest.raises(ValidationError):
        ActionRecipientPayload.model_validate(payload)


def test_action_submit_requires_recipient() -> None:
    """新协议不允许服务端从玩家原话猜测接收者。"""

    with pytest.raises(ValidationError):
        ActionSubmitPayload.model_validate({"clientActionId": "action-1", "utterance": "查看房间"})
