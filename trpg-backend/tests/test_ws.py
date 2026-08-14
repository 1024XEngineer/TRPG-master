"""WebSocket protocol, authorization, persistence, and reconnect regression tests."""

from dataclasses import replace

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ContractError,
    JsonObject,
    NarrativeOnlyEffect,
    RequiredAdjudicationCheck,
    SingleActionDecision,
    SkillCheckCandidate,
)
from collaboration_framework.engine import DiceRoller, SequenceDiceSource
from collaboration_framework.host.adapters.fakes import (
    FakeNarrationModel,
    FakeOpeningNarrationModel,
)
from collaboration_framework.host.application import ActionPlanNarrator
from collaboration_framework.host.schemas import (
    IntentContext,
    NarrationContext,
    OpeningNarrationContext,
)
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.controller import ws as ws_controller
from app.main import app

ROOMS_BASE = "/api/v1/rooms"


class _WsCandidateIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
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


class _WsAttackThenPlainIntentModel:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context: IntentContext) -> JsonObject:
        self.calls += 1
        if self.calls == 1:
            return {
                "kind": "action",
                "verb": "attack",
                "target": {"matched": True, "id": "thomas"},
                "check": {
                    "route": "default",
                    "proposed_skills": ["fighting-brawl"],
                },
                "summary": context.player_input.utterance,
            }
        return {
            "kind": "action",
            "verb": "talk",
            "target": {"matched": True, "id": "thomas"},
            "check": {"route": "none"},
            "summary": context.player_input.utterance,
        }


class _WsPlainIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
        return {
            "kind": "dialogue",
            "verb": "talk",
            "target": {"matched": True, "id": "thomas"},
            "check": {"route": "none"},
            "summary": context.player_input.utterance,
        }


class _WsSingleActionCheckPlanner:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context) -> SingleActionDecision:
        self.calls += 1
        return SingleActionDecision(
            adjudication=ActionAdjudication(
                request_id="application-owned",
                source_revision=context.player_view.revision,
                actor_id=context.player_input.actor_id,
                summary=context.player_input.utterance,
                target=ActionTarget(
                    kind="location",
                    id=context.player_view.scene.id,
                ),
                method=ActionMethod(
                    family="investigate",
                    description=context.player_input.utterance,
                ),
                check=RequiredAdjudicationCheck(
                    candidates=(
                        SkillCheckCandidate(
                            candidate_id="library-use",
                            skill_id="library-use",
                            difficulty="regular",
                            method_summary="查阅现场资料",
                            player_safe_reason="需要理解现场留下的文字线索",
                        ),
                    )
                ),
                success_effects=(NarrativeOnlyEffect(),),
            )
        )


class _WsCountingActionPlanNarration:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context) -> JsonObject:
        del context
        self.calls += 1
        return {
            "kind": "narration",
            "text": f"单动作恢复结果 {self.calls}",
            "claimed_evidence_refs": [],
            "suggested_actions": ["继续调查"],
        }


class _WsFirstPersonThenSafeNarration:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context) -> JsonObject:
        del context
        self.calls += 1
        return {
            "kind": "narration",
            "text": ("我带着你们进入墓地。" if self.calls == 1 else "你带着托马斯进入墓地。"),
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class _WsInvalidTwiceThenSafeNarration:
    leaked_text = "托马斯看着你。 claimed_fact_ids: [],"

    def __init__(self) -> None:
        self.calls = 0
        self._fake = FakeNarrationModel()

    async def generate(self, context: NarrationContext) -> JsonObject:
        self.calls += 1
        if self.calls <= 2:
            return {
                "kind": "narration",
                "text": self.leaked_text,
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        return await self._fake.generate(context)


class _WsEscapedNewlineNarration:
    async def generate(self, context: NarrationContext) -> JsonObject:
        return {
            "kind": "narration",
            "text": "第一段\\r\\n第二段\\n第三段",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


class _WsMissingParticipantOpening:
    async def generate(self, context: OpeningNarrationContext) -> JsonObject:
        del context
        return {
            "kind": "narration",
            "text": "这段模型输出遗漏了所有在场角色姓名。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


class _WsCountingOpening:
    """Count model calls while returning the deterministic valid opening."""

    def __init__(self) -> None:
        self.calls = 0
        self._fake = FakeOpeningNarrationModel()

    async def generate(self, context: OpeningNarrationContext) -> JsonObject:
        self.calls += 1
        return await self._fake.generate(context)


class _FailOnceActionPlanNarrator:
    def __init__(self, delegate: ActionPlanNarrator) -> None:
        self.delegate = delegate
        self.calls = 0

    async def narrate(self, context):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary narrator outage")
        return await self.delegate.narrate(context)


@pytest.fixture
def sync_client() -> TestClient:
    # 用同一个 app 实例的同步 TestClient——HTTP 部分照常发请求准备房间/角色
    # 数据，WS 部分用它的 websocket_connect（httpx 异步 client 不支持 WS）。
    return TestClient(app)


def register_and_login(client: TestClient, account: str = "host1") -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": "secret1", "nickname": "房主"},
    )
    assert response.status_code == 201
    return response.json()["data"]["token"]


def create_room(client: TestClient, token: str, max_players: int = 1) -> dict:
    """建房（issue #106 起要求登录，房间会关联到这个账号）。"""
    response = client.post(
        ROOMS_BASE,
        json={
            "roomName": "WS测试房间",
            "nickname": "房主",
            "maxPlayers": max_players,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()["data"]


def join_as(client: TestClient, room_code: str, account: str, nickname: str = "访客") -> dict:
    """用一个**新账号**加入房间。

    必须是新账号：房间成员的幂等键是账号，拿房主的 token 再 join 会被当成重连、
    原样返回房主身份，测不出"两个人"。
    """
    token = register_and_login(client, account)
    response = client.post(
        f"{ROOMS_BASE}/{room_code}/join",
        json={"nickname": nickname},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    result = response.json()["data"]
    result["authToken"] = token
    return result


def complete_character(
    client: TestClient,
    room_id: str,
    reconnect_token: str,
    name: str = "陈探员",
) -> None:
    headers = {"X-Reconnect-Token": reconnect_token}
    draft = client.post(f"{ROOMS_BASE}/{room_id}/characters", headers=headers)
    character_id = draft.json()["data"]["characterId"]
    client.patch(
        f"{ROOMS_BASE}/{room_id}/characters/{character_id}",
        json={
            "name": name,
            "attributes": {
                "STR": 50,
                "CON": 50,
                "POW": 50,
                "DEX": 50,
                "APP": 50,
                "SIZ": 50,
                "INT": 50,
                "EDU": 50,
                "LUCK": 50,
            },
            "derivedStats": {"HP": 12},
            "skills": {},
            "equipment": [],
            "occupation": None,
            "background": "",
            "notes": "",
        },
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room_id}/characters/{character_id}/complete", headers=headers)


def advance_to_building(client: TestClient, room: dict) -> None:
    headers = {"X-Reconnect-Token": room["reconnectToken"]}
    preview = client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    max_players = preview["maxPlayers"]
    modules = client.get("/api/v1/modules").json()["data"]
    module_id = next(
        module["id"]
        for module in modules
        if module["playersMin"] <= max_players <= module["playersMax"]
    )
    client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    client.post(f"{ROOMS_BASE}/{room['roomId']}/start-story", headers=headers)


def start_game(client: TestClient, room: dict, token: str) -> None:
    with client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        narration, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )
        view = next(message for message in progress if message.get("type") == "view.updated")
        assert view["type"] == "view.updated"
        assert view["payload"]["playerId"] == room["playerId"]
        assert narration["payload"]["messageId"] == "game-opening"
        assert any(message.get("type") == "room.state" for message in progress)


# `ws.receive_json()` 等的是 portal 里的一个 future，那一层没有超时：服务端只要
# 少发一条消息，用例就不是失败而是永久阻塞，整个 suite 跟着挂死，看不出卡在哪。
RECEIVE_TIMEOUT_SECONDS = 5.0


def receive_json(ws, *, timeout: float = RECEIVE_TIMEOUT_SECONDS):
    """带截止时间的 `ws.receive_json()`，让"消息没来"成为一条可读的失败。"""

    import json

    import anyio

    # 必须是 async：portal.call 在事件循环线程里跑它，而 receive() 是协程。
    # 写成同步函数的话协程从不会被 await，超时形同虚设。
    async def _receive_with_timeout():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    try:
        message = ws.portal.call(_receive_with_timeout)
    except TimeoutError as exc:
        raise AssertionError(f"WebSocket 在 {timeout}s 内没有再发送任何消息") from exc
    if message.get("type") == "websocket.close":
        raise AssertionError(f"WebSocket 已关闭: {message!r}")
    return json.loads(message["text"])


def receive_until(ws, predicate, *, limit: int = 24):
    seen = []
    for _ in range(limit):
        message = receive_json(ws)
        seen.append(message)
        if predicate(message):
            return message, seen
    raise AssertionError(f"expected WebSocket event not found; seen={seen!r}")


def receive_replayed_opening(ws) -> dict:
    """Consume and validate the persisted opening sent after an in-game join."""

    opening = ws.receive_json()
    assert opening["type"] == "narration.push"
    assert opening["payload"]["messageId"] == "game-opening"
    return opening


def receive_narration_stream(ws, *, limit: int = 60) -> tuple[dict, list[dict]]:
    """Receive up to the authoritative `narration.push`, returning it with its chunks."""

    push, seen = receive_until(
        ws,
        lambda message: message.get("type") == "narration.push",
        limit=limit,
    )
    chunks = [message for message in seen if message.get("type") == "narration.chunk"]
    return push, chunks


def assert_chunks_reconstruct_push(push: dict, chunks: list[dict]) -> None:
    """The progressive chunks must rebuild the authoritative text exactly (issue #203)."""

    assert chunks, "expected progressive narration chunks before the authoritative push"
    message_id = push["payload"]["messageId"]
    assert [chunk["payload"]["messageId"] for chunk in chunks] == [message_id] * len(chunks)
    assert [chunk["payload"]["sequence"] for chunk in chunks] == list(range(len(chunks)))
    assert "".join(chunk["payload"]["text"] for chunk in chunks) == push["payload"]["text"]


def test_connect_without_token_is_rejected(sync_client: TestClient) -> None:
    room = create_room(sync_client, register_and_login(sync_client))

    with pytest.raises(WebSocketDisconnect), sync_client.websocket_connect(f"/ws/{room['roomId']}"):
        pass


def test_room_join_binds_session(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {
                    "reconnectToken": room["reconnectToken"],
                    "roomCode": room["roomCode"],
                    "nickname": "房主",
                },
            }
        )
        envelope = ws.receive_json()

    assert envelope == {
        "type": "session.bound",
        "payload": {"roomId": room["roomId"], "playerId": room["playerId"]},
    }


def test_room_join_with_unknown_player_closes_connection(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws,
    ):
        ws.send_json(
            {
                "type": "room.join",
                "playerId": "not-a-real-player",
                "payload": {"reconnectToken": "whatever"},
            }
        )
        ws.receive_json()
        ws.receive_json()


def test_room_join_rejects_wrong_reconnect_token(sync_client: TestClient) -> None:
    """拿对的 playerId 但错的 reconnect_token 不能绑定——否则任何登录账号都能
    用公开预览里暴露的 playerId 冒充别人（PR #78 review）。"""
    host_token = register_and_login(sync_client, "host_real")
    room = create_room(sync_client, host_token)
    # 一个"攻击者"账号，登录态有效，但没有房主的 reconnect_token。
    attacker_token = register_and_login(sync_client, "attacker")

    with (
        pytest.raises(WebSocketDisconnect),
        sync_client.websocket_connect(f"/ws/{room['roomId']}?token={attacker_token}") as ws,
    ):
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],  # 房主的 playerId（预览里能拿到）
                "payload": {"reconnectToken": "not-the-real-token"},
            }
        )
        ws.receive_json()

    # 房主本人用正确的 token 仍然能正常绑定。
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={host_token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        assert ws.receive_json()["type"] == "session.bound"


def test_player_ready_updates_room_state(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json(
            {"type": "player.ready", "playerId": room["playerId"], "payload": {"ready": True}}
        )

        # 让服务端处理完 player.ready 再去查——最简单的办法是紧接着发一条
        # room.join 强制走一次同步的事件处理再返回。
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["players"][0]["ready"] is True


def test_game_start_pushes_opening_narration_and_advances_phase(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        envelope, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        _, retry_progress = receive_until(
            ws,
            lambda message: message.get("type") == "session.bound",
        )
        retry_join_view = ws.receive_json()
        retry_join_opening = receive_replayed_opening(ws)

    view = next(message for message in progress if message.get("type") == "view.updated")
    room_state = next(message for message in progress if message.get("type") == "room.state")
    assert view["type"] == "view.updated"
    assert view["payload"]["playerView"]["scene"]["name"] == "托马斯的会客室"
    assert envelope["type"] == "narration.push"
    assert envelope["payload"]["messageId"] == "game-opening"
    assert "托马斯的会客室" in envelope["payload"]["text"]
    assert room_state["type"] == "room.state"
    assert room_state["payload"]["phase"] == "InGame"
    assert any(message.get("type") == "opening.started" for message in progress)
    assert any(message.get("type") == "view.updated" for message in retry_progress)
    assert any(message.get("type") == "room.state" for message in retry_progress)
    assert retry_join_view["type"] == "view.updated"
    assert retry_join_opening["payload"] == envelope["payload"]
    assert not any(
        message.get("type") in {"opening.started", "narration.push"} for message in retry_progress
    )

    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "InGame"
    conversation = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/conversation",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    openings = [
        event
        for event in conversation
        if event["type"] == "narration.push" and event["payload"].get("messageId") == "game-opening"
    ]
    assert len(openings) == 1
    assert openings[0]["id"] == "game-opening"
    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    persisted_opening = next(
        event
        for event in replay
        if event["eventType"] == "narration.push"
        and event["payload"].get("messageId") == "game-opening"
    )
    assert persisted_opening["playerId"] is None
    assert persisted_opening["payload"] == envelope["payload"]


def test_room_join_replays_persisted_opening_without_regenerating(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reconnect gets the stored opening even if its history request was stale."""

    token = register_and_login(sync_client, "opening_reconnect_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    opening_model = _WsCountingOpening()
    # 开场叙事现在由 session_view_application 负责（与 v2 动作路径已拆开）。
    monkeypatch.setattr(
        ws_controller,
        "session_view_application",
        replace(
            ws_controller.session_view_application,
            opening_narration_model=opening_model,
        ),
    )

    start_game(sync_client, room, token)

    # Do not call GET /conversation here. This models the failure side of the
    # race: history returned before the opening commit, so WebSocket rejoin must
    # independently replay the authoritative persisted event.
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        opening, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert [message["type"] for message in progress[:2]] == [
        "session.bound",
        "view.updated",
    ]
    assert opening["payload"]["messageId"] == "game-opening"
    assert "托马斯的会客室" in opening["payload"]["text"]
    assert opening_model.calls == 1


def test_invalid_opening_model_falls_back_after_room_enters_in_game(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "opening_fallback_host")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    # 开场叙事现在由 session_view_application 负责（与 v2 动作路径已拆开）。
    monkeypatch.setattr(
        ws_controller,
        "session_view_application",
        replace(
            ws_controller.session_view_application,
            opening_narration_model=_WsMissingParticipantOpening(),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        opening, progress = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
        )

    assert opening["payload"]["messageId"] == "game-opening"
    assert "托马斯的会客室" in opening["payload"]["text"]
    assert "陈探员" in opening["payload"]["text"]
    room_state = next(message for message in progress if message.get("type") == "room.state")
    assert room_state["payload"]["phase"] == "InGame"


def test_game_start_rejects_non_host(sync_client: TestClient) -> None:
    token = register_and_login(sync_client)
    room = create_room(sync_client, token, max_players=2)
    # 访客必须在 Lobby 阶段加入（join_room 只在这个阶段放行），所以先加入
    # 再推进到 Building，两人都建完卡后再让访客尝试 game.start。
    guest = join_as(sync_client, room["roomCode"], "guest_non_host")
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    complete_character(sync_client, room["roomId"], guest["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={guest['authToken']}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": guest["playerId"], "payload": {}})

        # 非房主发起 game.start 会被拒绝：收到一条 FORBIDDEN 的 error 事件
        # （issue #77 起明确告知发起者，不再像旧版那样静默忽略）；房间阶段
        # 维持 Building 不变，不会有 narration.push。
        envelope = ws.receive_json()

    assert envelope["type"] == "error"
    assert envelope["payload"]["code"] == "FORBIDDEN"
    preview = sync_client.get(f"{ROOMS_BASE}/{room['roomCode']}").json()["data"]
    assert preview["phase"] == "Building"


def test_action_submit_broadcasts_narration_to_room_only(sync_client: TestClient) -> None:
    token_a = register_and_login(sync_client, "host_a")
    token_b = register_and_login(sync_client, "host_b")
    room_a = create_room(sync_client, token_a, max_players=2)
    room_b = create_room(sync_client, token_b)
    guest = join_as(sync_client, room_a["roomCode"], "guest_a")
    advance_to_building(sync_client, room_a)
    complete_character(sync_client, room_a["roomId"], room_a["reconnectToken"])
    complete_character(sync_client, room_a["roomId"], guest["reconnectToken"])
    start_game(sync_client, room_a, token_a)

    with (
        sync_client.websocket_connect(f"/ws/{room_a['roomId']}?token={token_a}") as ws_a,
        sync_client.websocket_connect(
            f"/ws/{room_a['roomId']}?token={guest['authToken']}"
        ) as ws_guest,
        sync_client.websocket_connect(f"/ws/{room_b['roomId']}?token={token_b}") as ws_b,
    ):
        ws_a.send_json(
            {
                "type": "room.join",
                "playerId": room_a["playerId"],
                "payload": {"reconnectToken": room_a["reconnectToken"]},
            }
        )
        ws_a.receive_json()  # session.bound
        ws_a.receive_json()  # current view.updated
        receive_replayed_opening(ws_a)
        ws_guest.send_json(
            {
                "type": "room.join",
                "playerId": guest["playerId"],
                "payload": {"reconnectToken": guest["reconnectToken"]},
            }
        )
        ws_guest.receive_json()  # session.bound
        ws_guest.receive_json()  # current view.updated
        receive_replayed_opening(ws_guest)
        ws_b.send_json(
            {
                "type": "room.join",
                "playerId": room_b["playerId"],
                "payload": {"reconnectToken": room_b["reconnectToken"]},
            }
        )
        ws_b.receive_json()  # session.bound

        ws_a.send_json(
            {
                "type": "action.plan.submit",
                # 信封里的 playerId 不能切换身份，后端只使用已经绑定的 Player。
                "playerId": guest["playerId"],
                "payload": {
                    "clientActionId": "action-broadcast-122",
                    "utterance": "我看看托马斯",
                },
            }
        )
        completed, progress = receive_until(
            ws_a,
            lambda message: message.get("message_type") == "turn.completed",
        )
        action_echo = next(
            message for message in progress if message.get("type") == "action.broadcast"
        )
        narration, _ = receive_until(
            ws_a,
            lambda message: message.get("type") == "narration.push",
        )
        guest_narration, _ = receive_until(
            ws_guest,
            lambda message: message.get("type") == "narration.push",
        )

        # 同一个动作重试可以再次收到技术确认，但不能再次产生叙事广播。
        ws_a.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room_a["playerId"],
                "payload": {
                    "clientActionId": "action-broadcast-122",
                    "utterance": "我看看托马斯",
                },
            }
        )
        retried, _ = receive_until(
            ws_a,
            lambda message: message.get("message_type") == "turn.completed",
        )
        ws_a.send_json(
            {
                "type": "room.join",
                "playerId": room_a["playerId"],
                "payload": {"reconnectToken": room_a["reconnectToken"]},
            }
        )
        next_after_retry, _ = receive_until(
            ws_a,
            lambda message: message.get("type") == "session.bound",
        )
        view_after_retry = ws_a.receive_json()
        opening_after_retry = receive_replayed_opening(ws_a)
        # room_b 没有收到任何广播——发一条 room.join 触发一次同步交互，确认
        # 收到的仍然是它自己的 session.bound，而不是串过来的 narration。
        ws_b.send_json(
            {
                "type": "room.join",
                "playerId": room_b["playerId"],
                "payload": {"reconnectToken": room_b["reconnectToken"]},
            }
        )
        envelope_b = ws_b.receive_json()

    assert completed["protocol_version"] == "1"
    assert completed["message_type"] == "turn.completed"
    assert completed["correlation_id"] == "action-broadcast-122"
    assert completed["payload"]["player_id"] == room_a["playerId"]
    assert completed["payload"]["actor_id"] == "actor_1"
    assert action_echo["type"] == "action.broadcast"
    assert action_echo["payload"]["utterance"] == "我看看托马斯"
    assert narration["type"] == "narration.push"
    assert narration["payload"]["messageId"] == "action-broadcast-122"
    assert guest_narration == narration
    assert retried["message_type"] == "turn.completed"
    assert next_after_retry["type"] == "session.bound"
    assert view_after_retry["type"] == "view.updated"
    assert opening_after_retry["payload"]["messageId"] == "game-opening"
    assert envelope_b["type"] == "session.bound"
    for event in progress:
        rendered = str(event)
        assert "call_id" not in rendered
        assert "arguments" not in rendered
        assert "raw_output" not in rendered

    replay = sync_client.get(
        f"{ROOMS_BASE}/{room_a['roomId']}/replay",
        headers={"X-Reconnect-Token": room_a["reconnectToken"]},
    ).json()["data"]
    action_narrations = [
        event
        for event in replay
        if event["eventType"] == "narration.push"
        and event["payload"]["text"] == narration["payload"]["text"]
    ]
    assert len(action_narrations) == 1
    assert action_narrations[0]["payload"]["messageId"] == "action-broadcast-122"


def test_turn_error_reason_keeps_contract_error_message_bounded() -> None:
    reason = ws_controller._turn_error_reason(
        ContractError("checkpoint 不在可信候选中\nwith extra whitespace")
    )

    assert reason == "checkpoint 不在可信候选中 with extra whitespace"
    assert "\n" not in reason


def test_opening_narration_streams_chunks_before_the_authoritative_push(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client, "opening_stream")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.send_json({"type": "game.start", "playerId": room["playerId"], "payload": {}})
        push, chunks = receive_narration_stream(ws)

    assert push["payload"]["messageId"] == "game-opening"
    assert_chunks_reconstruct_push(push, chunks)


def test_replayed_opening_sends_no_chunks(sync_client: TestClient) -> None:
    """历史恢复只发权威消息：重新进房不该再放一遍渐进片段（issue #203）。"""

    token = register_and_login(sync_client, "replay_no_chunk")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        opening = receive_replayed_opening(ws)

    assert opening["payload"]["messageId"] == "game-opening"


def _send_json_failing_on(match, error: Exception):
    """Replace WebSocket.send_json so exactly the matching frame raises."""

    original = WebSocket.send_json

    async def send_json(self, data, mode: str = "text") -> None:
        if match(data):
            raise error
        await original(self, data, mode)

    return send_json


def test_disconnected_socket_does_not_lose_the_turn_narration(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对端掉线不能把内联执行的回合从中间掐断。

    `turn.completed` 是结算链的第一帧，而叙事落库排在这条链的最后
    （`_deliver_turn_narration`）。这一帧抛异常就会把整个回合中止在"规则效果
    已事务提交、叙事还没写进 events 表"的状态上——世界推进了，解释它的那段话
    永远消失，重连也恢复不出来，因为重放依赖的正是那行记录。

    这里模拟的是真实出现过的那种：底层 TCP 已断、application_state 还没被标记，
    send 直接从 uvloop 抛 RuntimeError。
    """

    token = register_and_login(sync_client, "disconnect_midturn")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    monkeypatch.setattr(
        WebSocket,
        "send_json",
        _send_json_failing_on(
            lambda data: data.get("message_type") == "turn.completed",
            RuntimeError("unable to perform operation on <TCPTransport closed=True ...>"),
        ),
    )

    action_id = "disconnect-midturn-b10"
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        receive_replayed_opening(ws)
        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": action_id,
                    "utterance": "先观察房间，然后询问眼前的人",
                },
            }
        )
        settled, seen = receive_until(
            ws,
            lambda message: message.get("type") in {"narration.push", "turn.failed"},
            limit=40,
        )

    assert settled["type"] == "narration.push", seen
    assert settled["payload"]["messageId"] == action_id
    assert all(message.get("type") != "turn.failed" for message in seen)

    # 落库才是这条断言的重点：客户端收没收到都可能，events 表里必须有。
    conversation = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/conversation",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    persisted = [
        event
        for event in conversation
        if event["type"] == "narration.push" and event["payload"]["messageId"] == action_id
    ]
    assert len(persisted) == 1, conversation


def test_a_send_failure_that_is_not_a_disconnect_still_fails_the_turn(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """容断只针对断线，不能变成"所有发送异常一律吞掉"。

    payload 不可序列化之类的问题必须继续以 turn.failed 的形式暴露出来，否则
    一个真实的契约错误会安静地消失在投递层里。
    """

    token = register_and_login(sync_client, "send_failure_not_disconnect")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    monkeypatch.setattr(
        WebSocket,
        "send_json",
        _send_json_failing_on(
            lambda data: (
                data.get("type") == "turn.phase_changed"
                and data["payload"]["phase"] == "understanding_action"
            ),
            RuntimeError("payload 不可序列化"),
        ),
    )

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        receive_replayed_opening(ws)
        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "send-failure-not-disconnect",
                    "utterance": "先观察房间，然后询问眼前的人",
                },
            }
        )
        failed, _ = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
            limit=40,
        )

    assert failed["payload"]["correlationId"] == "send-failure-not-disconnect"


def test_action_plan_submit_emits_safe_progress_and_one_parent_completion(
    sync_client: TestClient,
) -> None:
    token = register_and_login(sync_client, "action_plan_ws")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        receive_replayed_opening(ws)
        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": "parent-plan-ws-225",
                    "utterance": "先观察房间，然后询问眼前的人",
                },
            }
        )
        terminal, seen = receive_until(
            ws,
            lambda message: message.get("type") == "plan.completed",
            limit=40,
        )

    completed = next(message for message in seen if message.get("message_type") == "turn.completed")
    action_echo = next(message for message in seen if message.get("type") == "action.broadcast")
    progress = [message for message in seen if message.get("type", "").startswith("plan.")]
    assert completed["correlation_id"] == "parent-plan-ws-225"
    assert completed["payload"]["narration"]["kind"] == "narration"
    assert action_echo["payload"]["clientActionId"] == "parent-plan-ws-225"
    assert action_echo["payload"]["utterance"] == "先观察房间，然后询问眼前的人"
    assert any(message["type"] == "plan.started" for message in progress)
    phases = [
        message["payload"]["phase"]
        for message in seen
        if message.get("type") == "turn.phase_changed"
    ]
    assert phases == [
        "reading_player_view",
        "understanding_action",
        "executing_action",
        "refreshing_player_view",
        "generating_narration",
    ]
    assert seen.index(action_echo) < next(
        index for index, message in enumerate(seen) if message.get("type") == "plan.started"
    )
    assert terminal["payload"]["correlationId"] == "parent-plan-ws-225"
    assert terminal["payload"]["phase"] == "completed"
    assert sum(message.get("message_type") == "turn.completed" for message in seen) == 1
    assert sum(message.get("type") == "plan.completed" for message in seen) == 1
    assert all("semanticGoal" not in str(message) for message in progress)

    conversation = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/conversation",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    persisted_actions = [
        event
        for event in conversation
        if event["type"] == "action.broadcast"
        and event["payload"]["clientActionId"] == "parent-plan-ws-225"
    ]
    assert len(persisted_actions) == 1
    assert persisted_actions[0]["payload"]["utterance"] == "先观察房间，然后询问眼前的人"


def test_single_action_pending_resumes_without_plan_run(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "single_action_pending_247")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    planner = _WsSingleActionCheckPlanner()
    narration_model = _WsCountingActionPlanNarration()
    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "_planner",
        planner,
    )
    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "_narrator",
        ActionPlanNarrator(narration_model),
    )
    monkeypatch.setattr(
        ws_controller.adjudication_engine_service,
        "_dice",
        DiceRoller(SequenceDiceSource([24])),
    )

    action_id = "single-action-pending-247"
    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()  # session.bound
        ws.receive_json()  # current view.updated
        receive_replayed_opening(ws)

        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": action_id,
                    "utterance": "仔细检查书架上的文件",
                },
            }
        )
        pending, pending_events = receive_until(
            ws,
            lambda message: message.get("type") == "adjudication.pending",
        )
        assert pending["payload"]["planId"] is None
        assert all(message.get("type") != "turn.failed" for message in pending_events)
        assert [
            message["payload"]["phase"]
            for message in pending_events
            if message.get("type") == "turn.phase_changed"
        ] == [
            "reading_player_view",
            "understanding_action",
            "executing_action",
            "waiting_for_check",
        ]

        decision = pending["payload"]["pendingDecision"]
        assert decision["options"]
        select_message = {
            "type": "adjudication.select",
            "playerId": room["playerId"],
            "payload": {
                "clientActionId": action_id,
                "requestId": "single-action-select-247",
                "sourceRevision": pending["payload"]["sourceRevision"],
                "decisionId": decision["decision_id"],
                "decisionVersion": decision["decision_version"],
                "candidateId": decision["options"][0]["candidate_id"],
            },
        }
        ws.send_json(select_message)
        rolled, rolled_events = receive_until(
            ws,
            lambda message: (
                message.get("type") == "adjudication.pending"
                and message.get("payload", {}).get("status") == "awaiting_post_roll_decision"
            ),
            limit=40,
        )
        assert [
            message["payload"]["phase"]
            for message in rolled_events
            if message.get("type") == "turn.phase_changed"
        ] == ["waiting_for_check"]
        check_run = rolled["payload"]["checkRun"]
        luck_option = next(
            option
            for option in check_run["post_roll_options"]
            if option["kind"] == "spend_resource"
        )
        assert luck_option["cost"] == 4
        ws.send_json(
            {
                "type": "adjudication.post_roll",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": action_id,
                    "requestId": "single-action-spend-luck-247",
                    "sourceRevision": rolled["payload"]["sourceRevision"],
                    "checkId": check_run["check_id"],
                    "checkVersion": check_run["version"],
                    "optionId": luck_option["option_id"],
                },
            }
        )
        completed, completion_events = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=40,
        )
        narration, narration_events = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
            limit=40,
        )

        ws.send_json(select_message)
        repeated_completed, repeated_events = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=20,
        )
        repeated_narration, repeated_narration_events = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
            limit=20,
        )

        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": action_id,
                    "utterance": "仔细检查书架上的文件",
                },
            }
        )
        repeated_submit, repeated_submit_events = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=20,
        )
        repeated_submit_narration, repeated_submit_narration_events = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
            limit=20,
        )

    assert completed["correlation_id"] == action_id
    assert narration["payload"]["messageId"] == action_id
    assert completed["payload"]["narration"]["suggested_actions"] == ["继续调查"]
    assert all(message.get("type") != "turn.failed" for message in completion_events)
    assert [
        message["payload"]["phase"]
        for message in completion_events
        if message.get("type") == "turn.phase_changed"
    ] == ["refreshing_player_view", "generating_narration"]
    assert all(message.get("type") != "turn.failed" for message in narration_events)
    assert repeated_completed["payload"]["narration"] == completed["payload"]["narration"]
    assert repeated_narration["payload"] == narration["payload"]
    assert repeated_submit["payload"]["narration"] == completed["payload"]["narration"]
    assert repeated_submit_narration["payload"] == narration["payload"]
    assert planner.calls == 1
    assert narration_model.calls == 1
    assert all(message.get("type") != "turn.failed" for message in repeated_events)
    assert all(message.get("type") != "turn.failed" for message in repeated_narration_events)
    assert all(message.get("type") != "turn.failed" for message in repeated_submit_events)
    assert all(message.get("type") != "turn.failed" for message in repeated_submit_narration_events)

    replay = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/replay",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    action_events = [
        event
        for event in replay
        if event["eventType"] == "action.broadcast"
        and event["payload"].get("clientActionId") == action_id
    ]
    narration_events = [
        event
        for event in replay
        if event["eventType"] == "narration.push" and event["payload"].get("messageId") == action_id
    ]
    assert len(action_events) == 1
    assert len(narration_events) == 1
    assert "_turnCompletion" not in narration_events[0]["payload"]

    # 权威检定结果要留在历史里，刷新重进才恢复得出来（#310）。此前 check.result
    # 的发送侧随 #226 一并没了，掷骰结果只在骰子浮层里出现一次就再也找不到。
    check_events = [
        event
        for event in replay
        if event["eventType"] == "check.result"
        and event["payload"].get("clientActionId") == action_id
    ]
    assert len(check_events) == 1
    check_payload = check_events[0]["payload"]
    assert check_payload["skillName"] == "图书馆使用"
    assert check_payload["targetValue"] == 20
    assert check_payload["rollValue"] == 24
    assert check_payload["passed"] is True
    assert check_payload["resolutionKind"] == "spend_luck"
    assert check_payload["luckSpent"] == 4
    assert check_payload["characterName"] == "陈探员"

    conversation = sync_client.get(
        f"{ROOMS_BASE}/{room['roomId']}/conversation",
        headers={"X-Reconnect-Token": room["reconnectToken"]},
    ).json()["data"]
    conversation_narration = [
        event
        for event in conversation
        if event["type"] == "narration.push" and event["payload"].get("messageId") == action_id
    ]
    assert len(conversation_narration) == 1
    assert "_turnCompletion" not in conversation_narration[0]["payload"]


def test_action_plan_narrator_failure_retries_narration_without_replaying_steps(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "action_plan_narrator_retry")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    application = ws_controller.action_plan_turn_application
    narrator = _FailOnceActionPlanNarrator(application._narrator)
    monkeypatch.setattr(application, "_narrator", narrator)
    action = {
        "type": "action.plan.submit",
        "playerId": room["playerId"],
        "payload": {
            "clientActionId": "plan-narrator-retry-246",
            "utterance": "先观察房间，然后询问眼前的人",
        },
    }

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.receive_json()
        receive_replayed_opening(ws)

        ws.send_json(action)
        failed, first_seen = receive_until(
            ws,
            lambda message: message.get("type") == "turn.failed",
            limit=40,
        )
        assert failed["payload"]["code"] == "PLAN_NARRATOR_FAILED"
        assert all(message.get("type") != "plan.completed" for message in first_seen)

        ws.send_json(action)
        completed, retry_seen = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=40,
        )
        terminal, _ = receive_until(
            ws,
            lambda message: message.get("type") == "plan.completed",
            limit=40,
        )

    assert narrator.calls == 2
    assert completed["correlation_id"] == "plan-narrator-retry-246"
    assert terminal["payload"]["correlationId"] == "plan-narrator-retry-246"
    assert all(message.get("type") != "adjudication.pending" for message in retry_seen)


def test_subject_ownership_failure_retries_before_publishing_narration(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(sync_client, "subject_ownership_retry")
    room = create_room(sync_client, token)
    advance_to_building(sync_client, room)
    complete_character(sync_client, room["roomId"], room["reconnectToken"])
    start_game(sync_client, room, token)
    narration_model = _WsFirstPersonThenSafeNarration()
    monkeypatch.setattr(
        ws_controller.action_plan_turn_application,
        "_narrator",
        ActionPlanNarrator(narration_model),
    )
    action_id = "subject-ownership-retry-308"

    with sync_client.websocket_connect(f"/ws/{room['roomId']}?token={token}") as ws:
        ws.send_json(
            {
                "type": "room.join",
                "playerId": room["playerId"],
                "payload": {"reconnectToken": room["reconnectToken"]},
            }
        )
        ws.receive_json()
        ws.receive_json()
        receive_replayed_opening(ws)
        ws.send_json(
            {
                "type": "action.plan.submit",
                "playerId": room["playerId"],
                "payload": {
                    "clientActionId": action_id,
                    "utterance": "带托马斯去墓地",
                },
            }
        )
        completed, seen = receive_until(
            ws,
            lambda message: message.get("message_type") == "turn.completed",
            limit=40,
        )
        narration, _ = receive_until(
            ws,
            lambda message: message.get("type") == "narration.push",
            limit=20,
        )

    assert narration_model.calls == 2
    assert completed["payload"]["narration"]["text"] == "你带着托马斯进入墓地。"
    assert narration["payload"]["text"] == "你带着托马斯进入墓地。"
    assert all("我带着你们进入墓地" not in str(message) for message in seen)
