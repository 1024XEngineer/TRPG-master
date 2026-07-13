"""组合根（composition root）—— 唯一知道"用哪个具体实现"的地方。

这里是依赖倒置真正落地的位置：core/rules.RulesEngine 只依赖 SanJudgePort
这个接口类型（见 core/rules/ports.py），本文件负责把 core/ai.SanJudge 的
具体实例注入进去——RulesEngine 自己的代码完全不 import core.ai。

FastAPI 应用装配：REST 路由 + WS 端点。
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.ai.intent import LLMIntentParser
from core.ai.narrator import LLMNarrator
from core.ai.qa import StubQAResponder
from core.ai.san_judge import SanJudge
from core.content.repo import SqlAlchemyContentRepo
from core.db import get_sessionmaker
from core.orchestrator.orchestrator import Orchestrator
from core.rules.check_resolver import StubCheckResolver
from core.rules.engine import RulesEngine
from core.state.db_models import UserSessionRow
from core.state.repo import SqlAlchemyGameStateRepo
from core.view.projector import RealViewProjector
from server.rest import auth, characters, lobby, modules, replay
from server.ws.gateway import Gateway

app = FastAPI(title="AIDM Backend", version="0.1.0")

# ★ 2026-07-13：前端 demo（Vite dev server）跨源调用，本地开发放开 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, lobby.router, modules.router, characters.router, replay.router):
    app.include_router(router)

# ===== 组合根：装配依赖，SanJudge 依赖倒置在此接线 =====
_content_repo = SqlAlchemyContentRepo()
_game_state_repo = SqlAlchemyGameStateRepo()
_check_resolver = StubCheckResolver()
_san_judge = SanJudge()  # core/ai 实现，结构上满足 core.rules.ports.SanJudgePort

_rules_engine = RulesEngine(
    content_repo=_content_repo,
    check_resolver=_check_resolver,
    san_judge=_san_judge,  # ★ 依赖倒置：RulesEngine 只认 Protocol，不知道这是 core.ai 的实现
)

_intent_parser = LLMIntentParser()
_narrator = LLMNarrator()
_qa_responder = StubQAResponder()
_view_projector = RealViewProjector(content_repo=_content_repo)

_orchestrator = Orchestrator(
    game_state_repo=_game_state_repo,
    intent_parser=_intent_parser,
    rules_engine=_rules_engine,
    view_projector=_view_projector,
    narrator=_narrator,
)

_gateway = Gateway(
    orchestrator=_orchestrator,
    qa_responder=_qa_responder,
    content_repo=_content_repo,
    game_state_repo=_game_state_repo,
    view_projector=_view_projector,
)


@app.websocket("/ws/{room_id}")
async def ws_endpoint(websocket: WebSocket, room_id: str) -> None:
    """🔒 建连即鉴权（2026-07-11）：浏览器原生 WebSocket API 没法带自定义 header，
    token 走 query string（`?token=`）——这是 WS 鉴权的常见变通方式，不影响
    "建连即鉴权"这条设计原则本身，只是把 token 的搬运方式从 header 换成 query。
    """
    token = websocket.query_params.get("token", "")
    async with get_sessionmaker()() as session:
        user_session = await session.get(UserSessionRow, token)
        if user_session is None:
            await websocket.close(code=4401, reason="invalid token")
            return
        user_id = user_session.user_id

    await websocket.accept()
    player_id = ""
    try:
        while True:
            envelope = await websocket.receive_json()
            player_id = envelope.get("playerId", "")
            _gateway.register_connection(room_id, player_id, websocket)
            await _gateway.handle_client_event(
                room_id=room_id,
                player_id=player_id,
                event_type=envelope["type"],
                payload=envelope.get("payload", {}),
                user_id=user_id,
            )
    except WebSocketDisconnect:
        _gateway.unregister_connection(room_id, player_id)
