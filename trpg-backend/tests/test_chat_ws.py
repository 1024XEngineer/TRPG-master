"""issue #107 的 WS/REST 行为测试：讨论区落库与回显、行动锁、历史分页、退房清理。

复用 tests/test_ws.py 的装置模式（同步 TestClient + websocket_connect）。

⚠️ 本文件全部用**单条 WS 连接**：Starlette TestClient 的每个 websocket_connect
各起一个独立 portal 线程 + 独立事件循环，同一房间开两条连接时，广播要往另一个
事件循环的 websocket send —— 跨循环 await 直接挂死（conftest.py 顶部注释里
"各循环各连接"说的就是这件事；test_ws.py 现有的双连接用例之所以能跑，是因为
那两条连接在**不同房间**、从不互相广播）。「同房间双客户端都能收到广播」这类
断言只有 SDK e2e（真 uvicorn、单事件循环）能做——见
e2e/tests/discussion-chat.e2e.ts，那边有完整的双客户端覆盖；这里守住的是
落库/幂等/锁语义/鉴权/清理这些单连接就能证明的行为。

锁相关用例直接覆盖 `action_lock_manager`，不依赖任何叙事实现的时序。
"""

from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.service.action_lock import RoomActionLockManager
from tests.test_ws import (
    ROOMS_BASE,
    advance_to_building,
    complete_character,
    create_room,
    receive_until,
    register_and_login,
    start_game,
)


@pytest.fixture
def sync_client() -> Iterator[TestClient]:
    yield TestClient(app)


def _join_ws(ws, player: dict) -> None:
    ws.send_json(
        {
            "type": "room.join",
            "playerId": player["playerId"],
            "payload": {"reconnectToken": player["reconnectToken"]},
        }
    )
    assert ws.receive_json()["type"] == "session.bound"


def _send_chat(ws, player: dict, text: str, client_message_id: str) -> None:
    ws.send_json(
        {
            "type": "chat.send",
            "playerId": player["playerId"],
            "payload": {"text": text, "clientMessageId": client_message_id},
        }
    )


def _submit_action(ws, player: dict, utterance: str) -> None:
    ws.send_json(
        {
            "type": "action.plan.submit",
            "playerId": player["playerId"],
            "payload": {"clientActionId": str(uuid4()), "utterance": utterance},
        }
    )


class _ConversationCheckIntentModel:
    async def generate(self, context):  # noqa: ANN001
        return {
            "kind": "action",
            "verb": "investigate",
            "target": {"matched": True, "id": context.player_view.scene.id},
            "check": {
                "route": "default",
                "proposed_skills": ["library-use", "stealth"],
            },
            "summary": context.player_input.utterance,
        }


class _ConversationClarificationIntentModel:
    async def generate(self, context):  # noqa: ANN001
        return {
            "kind": "unknown",
            "verb": "unknown",
            "target": {"matched": False, "raw": context.player_input.utterance},
            "check": {"route": "none"},
            "summary": "需要澄清",
            "clarification_question": "你指的是哪一本书？",
        }


# ── 讨论区：落库 + 广播回显 ───────────────────────────


def test_chat_send_echoes_broadcast_with_full_payload(sync_client: TestClient) -> None:
    """chat.send 落库后广播 chat.message（发送者自己也靠广播回显，前端不做
    本地乐观插入）。payload 带齐渲染所需字段，时间戳带时区后缀（UtcDatetime
    的全项目约定）。"""
    token = register_and_login(sync_client, "chat_host")
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)
        _send_chat(ws, room, "我们先去图书馆吧", "msg-1")
        envelope = ws.receive_json()

    assert envelope["type"] == "chat.message"
    assert envelope["payload"]["text"] == "我们先去图书馆吧"
    assert envelope["payload"]["nickname"] == "房主"
    assert envelope["payload"]["playerId"] == room["playerId"]
    assert envelope["payload"]["clientMessageId"] == "msg-1"
    assert envelope["payload"]["sentAt"].endswith(("Z", "+00:00"))


def test_chat_send_is_idempotent_on_duplicate_client_message_id(
    sync_client: TestClient,
) -> None:
    """重连后重发同一条消息（相同 clientMessageId）：库里只有一行，第二次广播
    与第一次是同一条消息（messageId 相同），其他人不会看到重复气泡。"""
    token = register_and_login(sync_client, "idem_host")
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)
        _send_chat(ws, room, "只发一次的消息", "dup-1")
        first = ws.receive_json()
        _send_chat(ws, room, "只发一次的消息", "dup-1")
        second = ws.receive_json()

    assert first["payload"]["messageId"] == second["payload"]["messageId"]

    history = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/messages",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    assert len(history) == 1


# ── action.plan.submit：原话广播 + 叙事回复 ───────────


def test_action_submit_broadcasts_utterance_then_narration(sync_client: TestClient) -> None:
    """action.plan.submit 先广播发起者的**原话**（action.broadcast，修"聊天记录像
    被隔离"的 bug——此前原话只在发送方本地插入），再广播守秘人回复
    （narration.push）。双客户端的"对方也能看到"断言在 e2e（见文件头说明）。"""
    token = register_and_login(sync_client, "act_host")
    room = create_room(sync_client, token)

    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)
        _submit_action(ws, room, "我推开吱呀作响的木门")
        echo, _ = receive_until(ws, lambda message: message.get("type") == "action.broadcast")
        narration, _ = receive_until(ws, lambda message: message.get("type") == "narration.push")

    assert echo["type"] == "action.broadcast"
    assert echo["payload"]["utterance"] == "我推开吱呀作响的木门"
    assert echo["payload"]["nickname"] == "房主"
    assert echo["payload"]["characterName"] == "陈探员"
    assert echo["payload"]["playerId"] == room["playerId"]
    assert narration["type"] == "narration.push"
    assert narration["payload"]["text"]


# ── 行动锁 ───────────────────────────────────────────


def test_lock_released_after_turn_failure(sync_client: TestClient) -> None:
    """AI 调用失败后锁必须释放（finally 兜底），否则房间永久锁死——issue #107
    验收标准。PlayerView 尚不存在时输入不会被接受或广播。"""
    token = register_and_login(sync_client, "fail_host")
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)

        _submit_action(ws, room, "我尝试翻译古籍")
        failure, _ = receive_until(ws, lambda message: message["type"] == "turn.failed")
        assert failure["payload"]["code"] == "ROOM_RUNTIME_NOT_FOUND"

        # 立刻重试——若锁没被释放，这里会收到 ACTION_IN_PROGRESS。
        _submit_action(ws, room, "我再次尝试翻译")
        failure, _ = receive_until(ws, lambda message: message["type"] == "turn.failed")
        assert failure["payload"]["code"] == "ROOM_RUNTIME_NOT_FOUND"


def test_action_lock_semantics() -> None:
    """锁管理器本身的语义（不开 WS）：占用中拒绝、按房间隔离、释放后可得、
    超时自动过期、旧持有者不能误释放新持有者的锁（stale release 修复）。
    """
    manager = RoomActionLockManager()

    def acquire(room_id: str, action_id: str = "action-1") -> str | None:
        return manager.try_acquire(
            room_id,
            player_id="player-1",
            actor_id="actor-1",
            client_action_id=action_id,
            revision="0",
        )

    token1 = acquire("room-1")
    assert token1 is not None
    snapshot = manager.snapshot("room-1")
    assert snapshot is not None
    assert (
        snapshot.player_id,
        snapshot.actor_id,
        snapshot.client_action_id,
        snapshot.revision,
    ) == ("player-1", "actor-1", "action-1", "0")
    assert acquire("room-1") is None, "占用中必须拒绝"
    assert acquire("room-2") is not None, "锁按房间隔离"

    manager.release("room-1", token1)
    token2 = acquire("room-1", "action-2")
    assert token2 is not None, "释放后必须可再次获取"

    # stale release：旧 token 不能释放新持有者的锁
    manager.release("room-1", token1)  # token1 已过期，不匹配 token2
    assert acquire("room-1") is None, "旧 token release 不能误删新锁"
    manager.release("room-1", token2)  # 正确 token 才能释放

    # 超时兜底：把到期时间人为拨到过去，模拟"拿了锁但 release 没被走到"。
    assert acquire("room-1", "action-3") is not None
    current = manager._locks["room-1"]
    manager._locks["room-1"] = replace(current, expires_at=0.0)
    assert manager.snapshot("room-1") is None, "读取快照时应惰性清理过期锁"
    assert acquire("room-1") is not None, "过期的锁必须能被抢占（防永久锁死）"

    manager.release("room-does-not-exist", "any-token")  # 释放不存在的锁是无害空操作


# ── 历史消息 REST ────────────────────────────────────


def test_messages_pagination_with_before_cursor(sync_client: TestClient) -> None:
    token = register_and_login(sync_client, "page_host")
    room = create_room(sync_client, token)
    headers = {"X-Reconnect-Token": room["reconnectToken"]}

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)
        for i in range(3):
            _send_chat(ws, room, f"第{i + 1}条", f"pg-{i}")
            ws.receive_json()

    page1 = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/messages", params={"limit": 2}, headers=headers
    ).json()["data"]
    assert [m["text"] for m in page1] == ["第3条", "第2条"]  # 倒序，最新在前

    page2 = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/messages",
        params={"limit": 2, "before": page1[-1]["messageId"]},
        headers=headers,
    ).json()["data"]
    assert [m["text"] for m in page2] == ["第1条"]


def test_messages_rejects_non_member(sync_client: TestClient) -> None:
    token = register_and_login(sync_client, "member_host")
    room = create_room(sync_client, token)
    # 另一个房间的人拿自己的 reconnect_token 来查这个房间 → 拒绝
    other_token = register_and_login(sync_client, "outsider")
    other_room = create_room(sync_client, other_token)

    response = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/messages",
        headers={"X-Reconnect-Token": other_room["reconnectToken"]},
    )
    assert response.status_code == 403


# ── 退房清理 / 复盘纯净 ──────────────────────────────


def test_end_game_clears_chat_and_replay_stays_clean(sync_client: TestClient) -> None:
    """房主结束游戏后聊天记录被清空；聊天从头到尾不出现在 replay 里
    （issue #107 验收标准：聊天是临时工作记忆，不进复盘）。"""

    token = register_and_login(sync_client, "end_host")
    room = create_room(sync_client, token)
    headers = {"X-Reconnect-Token": room["reconnectToken"]}
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        _join_ws(ws, room)
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        from tests.test_ws import receive_until

        receive_until(ws, lambda message: message.get("type") == "narration.push")
        _send_chat(ws, room, "这句话不该进复盘", "end-1")
        receive_until(ws, lambda message: message.get("type") == "chat.message")

    # 聊天在 end 之前查得到
    assert (
        len(
            sync_client.get(f"{ROOMS_BASE}/{room['roomId']}/messages", headers=headers).json()[
                "data"
            ]
        )
        == 1
    )

    end_response = sync_client.post(f"{ROOMS_BASE}/{room['roomId']}/end", headers=headers)
    assert end_response.status_code == 200

    # end 之后聊天被清空
    assert (
        sync_client.get(f"{ROOMS_BASE}/{room['roomId']}/messages", headers=headers).json()["data"]
        == []
    )

    # replay 里从头到尾没有聊天内容
    replay = sync_client.get(f"{ROOMS_BASE}/{room['roomId']}/replay", headers=headers).json()[
        "data"
    ]
    assert "这句话不该进复盘" not in str(replay)
