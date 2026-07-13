"""Gateway —— 对应 master §2.1 模块清单（submitAction/subscribe）+ §5.2 事件目录。

WS 会话、房间生命周期、公共广播 + 私密定向下发。🔒 建连即鉴权（2026-07-11）：
WS 连接建立时必须先带账号 token 校验通过，才允许发 room.join。

`action.submit` 走 Orchestrator.handle_turn（一次输入=一次回合请求，见
core/orchestrator）；`qa.ask` 走 QAResponder，天然不占回合、不经 Orchestrator。

★ 2026-07-13：room.join/player.ready/game.start 补了最小真实实现（/goal 任务
要求前端能真正走完整链路）。room.join/player.ready/game.start 是"会话管理"
性质的事件（master §4.5 EventLog 注释里明确排除在 EventPayload 之外），直接
操作 PlayerRow/RoomRow，不经过 GameStateRepo 这层——那层是给"游戏内发生的事"
用的，见 core/state/repo.py 的职责边界。
"""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from sqlalchemy import select

from core.ai.qa import QAResponder
from core.content.repo import ContentRepo
from core.db import get_sessionmaker
from core.orchestrator.orchestrator import Orchestrator
from core.state.db_models import PlayerRow, RoomRow
from core.state.repo import GameStateRepo
from core.view.projector import ViewProjector


class Gateway:
    def __init__(
        self,
        orchestrator: Orchestrator,
        qa_responder: QAResponder,
        content_repo: ContentRepo,
        game_state_repo: GameStateRepo,
        view_projector: ViewProjector,
    ) -> None:
        self._orchestrator = orchestrator
        self._qa_responder = qa_responder
        self._content_repo = content_repo
        self._game_state_repo = game_state_repo
        self._view_projector = view_projector
        # 连接注册表：room_id -> player_id -> WebSocket。
        # ★ 2026-07-13 最小实现：按连接广播打通链路，还不是最终形态——
        # 真正的 §5.2.2 "narration.push 按 location 现算听众"（visibility:'scene'
        # 精确过滤）留到分头行动那一步再做，这里先广播给房间内全部已注册连接。
        self._connections: dict[str, dict[str, WebSocket]] = {}

    def register_connection(self, room_id: str, player_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(room_id, {})[player_id] = websocket

    def unregister_connection(self, room_id: str, player_id: str) -> None:
        self._connections.get(room_id, {}).pop(player_id, None)

    async def handle_client_event(
        self, room_id: str, player_id: str, event_type: str, payload: dict, user_id: str
    ) -> None:
        """C→S 事件分发。"""
        if event_type == "action.submit":
            await self._on_action_submit(room_id, player_id, payload)
        elif event_type == "qa.ask":
            await self._on_qa_ask(room_id, player_id, payload)
        elif event_type == "room.join":
            await self._on_room_join(room_id, payload, user_id)
        elif event_type == "player.ready":
            await self._on_player_ready(room_id, player_id, payload)
        elif event_type == "game.start":
            await self._on_game_start(room_id, player_id)
        elif event_type in {
            "room.rejoin",
            "room.leave",
            "character.select",
            "check.manual",
            "check.roll",
            "san.check.roll",
            "luck.spend",
            "luck.skip",
            "voice.chunk",
            "note.save",
        }:
            raise NotImplementedError(f"Gateway.handle_client_event: {event_type} 待实现")
        else:
            raise ValueError(f"未知事件类型: {event_type}")

    async def _on_room_join(self, room_id: str, payload: dict, user_id: str) -> None:
        """找到这个已登录用户在这个房间里的 PlayerRow，回一条 session.bound——
        连接本身在 main.py 里已经用 envelope 自带的 playerId 注册过了，这里只
        做校验+回执。房主的 PlayerRow 在 POST /rooms 时建好；访客的 PlayerRow
        在 POST /rooms/{room_code}/join 时建好（见 server/rest/lobby.py 的
        join_room）——两条路径殊途同归，到这里都已经有一条现成的 PlayerRow，
        这个方法不需要关心"是房主还是访客"。
        """
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(PlayerRow).where(PlayerRow.room_id == room_id, PlayerRow.user_id == user_id)
            )
            player = result.scalar_one_or_none()
            if player is None:
                raise ValueError(f"用户 {user_id} 不是房间 {room_id} 的玩家，请先调用 REST 加入接口")

            player.connected = True
            await session.commit()
            player_id = player.id
            reconnect_token = player.reconnect_token

        await self._send_to(room_id, player_id, {
            "type": "session.bound",
            "payload": {"playerId": player_id, "reconnectToken": reconnect_token},
        })

    async def _on_player_ready(self, room_id: str, player_id: str, payload: dict) -> None:
        async with get_sessionmaker()() as session:
            player = await session.get(PlayerRow, player_id)
            if player is None:
                raise ValueError(f"player not found: {player_id}")
            player.ready = bool(payload.get("ready", True))
            await session.commit()

    async def _on_game_start(self, room_id: str, player_id: str) -> None:
        """🔒 仅房主可发，需全员 ready。★ 本次范围：只校验"发起者是房主"，
        不做"全员 ready"这条硬校验（单人demo场景下就是房主自己）。
        """
        async with get_sessionmaker()() as session:
            room = await session.get(RoomRow, room_id)
            if room is None:
                raise ValueError(f"room not found: {room_id}")
            if room.host_player_id != player_id:
                raise ValueError("仅房主可以开始游戏")
            room.phase = "InGame"
            await session.commit()

        # 开场：直接投影当前视角，把起始场景描述当作第一条旁白推给玩家，
        # 不经过 RulesEngine/Narrator（还没有玩家输入可供裁决），纯展示。
        state = await self._game_state_repo.load(room_id)
        view = await self._view_projector.project(state, player_id)
        await self._broadcast_narration(room_id, view.visible_scene_description)
        await self._send_private_view(room_id, player_id, view)

    async def _on_action_submit(self, room_id: str, player_id: str, payload: dict) -> None:
        """一次玩家输入 = 一次回合请求（§2.1 通信风格），真实调用 Orchestrator。"""
        utterance = payload["utterance"]
        result = await self._orchestrator.handle_turn(room_id, player_id, utterance)
        await self._broadcast_narration(room_id, result.narration)
        await self._send_private_view(room_id, player_id, result.view)

    async def _on_qa_ask(self, room_id: str, player_id: str, payload: dict) -> None:
        """qa.ask 独立入口，不占回合、不经 Orchestrator，直接调 QAResponder。"""
        question = payload["question"]
        state = await self._game_state_repo.load(room_id)
        view = await self._view_projector.project(state, player_id)
        chunks: list[str] = []
        async for chunk in self._qa_responder.answer(question, view):
            chunks.append(chunk)
        await self._send_to(room_id, player_id, {"type": "qa.answer", "payload": {"text": "".join(chunks)}})

    async def _broadcast_narration(self, room_id: str, text: str) -> None:
        """S→C narration.push。★ 本次先广播给房间内全部连接，未按 location 精确
        过滤听众——那是分头行动里 visibility:'scene' 的职责，见 master §5.2.2，
        本次范围只是把"发消息→收到真实 AI 叙述"这条链路先打通。
        """
        envelope = {"type": "narration.push", "payload": {"text": text}}
        for ws in self._connections.get(room_id, {}).values():
            await ws.send_json(envelope)

    async def _send_private_view(self, room_id: str, player_id: str, view: Any) -> None:
        """S→C view.private（私密定向）。"""
        await self._send_to(room_id, player_id, {"type": "view.private", "payload": {"view": view.model_dump(by_alias=True)}})

    async def _send_to(self, room_id: str, player_id: str, envelope: dict) -> None:
        ws = self._connections.get(room_id, {}).get(player_id)
        if ws is not None:
            await ws.send_json(envelope)
