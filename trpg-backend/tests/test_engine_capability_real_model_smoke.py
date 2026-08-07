"""Does the configured model actually use the newly opened effects?

The scripted tests in `test_ws_engine_capabilities.py` prove the plumbing works.
They cannot prove the other half of "end to end": that a real Agent, given the
`KeeperCapabilityView` and the updated instructions, chooses the registered
effects instead of falling back to `narrative_only` for everything.

Skipped unless ``RUN_REAL_MODEL_CAPABILITY_SMOKE=1``; it calls the provider
configured in ``.env`` and never runs in CI. It records only effect type names
and ids, never model output, keeper content or PlayerView contents.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from collaboration_framework.contracts import (
    ActionPlan,
    PlayerInput,
    PlayerViewScope,
    SingleActionDecision,
)
from collaboration_framework.engine import RuleEngineService
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.schemas import HostAgentContext, RecentTurnContext
from httpx import ASGITransport, AsyncClient

from app.adapters import PromptHostTurnDecisionModel, SqlAlchemyEngineStore
from app.controller import ws as ws_controller
from app.core.config import Settings
from app.main import app
from tests.helpers import bearer, reconnect
from tests.test_play_sim_real_model import _structured_client

RUN_SMOKE = os.getenv("RUN_REAL_MODEL_CAPABILITY_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_SMOKE,
    reason="set RUN_REAL_MODEL_CAPABILITY_SMOKE=1 to call the configured provider",
)

ROOMS_BASE = "/api/v1/rooms"

# Utterances chosen so a competent Keeper would reach for a specific registered
# effect. The assertion is deliberately weak — "some registered effect beyond
# narrative_only" — because which one is a judgement call, not a contract.
CASES = [
    ("向委托人打听他知道的事情", "我请托马斯把叔叔失踪当天的经过原原本本说一遍。"),
    ("动身前往另一个地点", "我告辞出门，直接去金博尔宅的书房。"),
    ("明显要花掉时间的行动", "我在书房里待上一整个下午，把每一格书架都翻一遍。"),
    ("需要一个模组没写的普通人", "我到街上找个报童，问他最近有没有见过陌生人在附近转悠。"),
]


async def _in_game_room(client: AsyncClient) -> dict[str, Any]:
    register = await client.post(
        "/api/v1/auth/register",
        json={"account": "cap_smoke", "password": "secret1", "nickname": "房主"},
    )
    token = register.json()["data"]["token"]
    room = (
        await client.post(
            ROOMS_BASE,
            json={"roomName": "能力冒烟", "nickname": "房主", "maxPlayers": 1},
            headers=bearer(token),
        )
    ).json()["data"]

    headers = reconnect(room["reconnectToken"])
    modules = (await client.get("/api/v1/modules")).json()["data"]
    module_id = next(m["id"] for m in modules if m["playersMin"] <= 1 <= m["playersMax"])
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module_id, "attributeGenMethod": "point_buy"},
        headers=headers,
    )
    await client.post(f"{ROOMS_BASE}/{room['roomId']}/start-story", headers=headers)
    draft = await client.post(f"{ROOMS_BASE}/{room['roomId']}/characters", headers=headers)
    character_id = draft.json()["data"]["characterId"]
    await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json={
            "name": "陈探员",
            "attributes": dict.fromkeys(
                ["STR", "CON", "POW", "DEX", "APP", "SIZ", "INT", "EDU", "LUCK"], 50
            ),
            "derivedStats": {"HP": 12},
            "skills": {},
            "equipment": [],
            "occupation": None,
            "background": "",
            "notes": "",
        },
        headers=headers,
    )
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
        headers=headers,
    )
    return room


def _effect_types(decision) -> list[str]:
    if isinstance(decision, SingleActionDecision):
        return [effect.type for effect in decision.adjudication.success_effects]
    if isinstance(decision, ActionPlan):
        # The planner only names semantic goals for a plan; the effects are
        # chosen later, one step at a time, by the step adjudicator.
        return []
    raise AssertionError(f"unexpected decision {type(decision).__name__}")


async def test_configured_model_reaches_for_the_newly_opened_effects() -> None:
    settings = Settings()
    assert settings.host_model_provider != "fake"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        room = await _in_game_room(client)

    # game.start runs over the WebSocket; drive the Engine directly instead so the
    # smoke test stays about the planner rather than the transport.
    from app.service import room as room_service

    async with ws_controller.async_session_factory() as session:
        await room_service.begin_game(session, room["roomId"], room["playerId"])

    store = SqlAlchemyEngineStore(ws_controller.async_session_factory)
    engine = RuleEngineService(store)
    projector = PlayerViewProjector(engine)
    planner = PromptHostTurnDecisionModel(_structured_client(settings))

    scope_actor = "actor_1"
    observed: list[tuple[str, list[str], bool]] = []
    for index, (label, utterance) in enumerate(CASES):
        player_input = PlayerInput(
            room_id=room["roomId"],
            player_id=room["playerId"],
            actor_id=scope_actor,
            client_action_id=f"cap-smoke-{index}",
            utterance=utterance,
        )
        view = await projector.project(player_input)
        capabilities = await engine.read_keeper_capabilities(
            PlayerViewScope(
                room_id=player_input.room_id,
                player_id=player_input.player_id,
                actor_id=scope_actor,
            )
        )
        decision = await planner.generate(
            HostAgentContext(
                player_input=player_input,
                player_view=view,
                recent_history=RecentTurnContext.empty(
                    player_input=player_input,
                    player_view=view,
                ),
                keeper_capabilities=capabilities,
            )
        )
        effects = _effect_types(decision)
        observed.append((label, effects, isinstance(decision, ActionPlan)))

    print(json.dumps(observed, ensure_ascii=False, indent=2))
    single_action_effects = {effect for _, effects, _ in observed for effect in effects}
    assert single_action_effects, "planner produced no single action at all"
    assert single_action_effects - {"narrative_only"}, (
        f"the configured model never used a registered effect beyond narrative_only: {observed}"
    )
