from __future__ import annotations

import os

import pytest
from collaboration_framework.bootstrap.host_agent import build_deepseek_host_agent
from collaboration_framework.contracts import (
    AvailableExitView,
    ExitDestinationView,
    MatchedTarget,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
)
from collaboration_framework.host.application import HostAgentIntentResolver
from collaboration_framework.host.schemas import (
    HostAgentContext,
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
)

from app.core.config import Settings

RUN_DEEPSEEK_HISTORY_SMOKE = os.getenv("RUN_DEEPSEEK_HISTORY_SMOKE") == "1"


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HISTORY_SMOKE,
    reason=("set RUN_DEEPSEEK_HISTORY_SMOKE=1 to run the real DeepSeek recent-history smoke test"),
)
@pytest.mark.asyncio
async def test_deepseek_resolves_reference_from_recent_history() -> None:
    settings = Settings()
    assert settings.host_model_provider == "deepseek"
    assert settings.deepseek_api_key is not None

    player_input = PlayerInput(
        room_id="history_smoke_room",
        player_id="history_smoke_player",
        actor_id="history_smoke_actor",
        client_action_id="history_smoke_current",
        utterance="继续去我刚才说的那个地方。",
    )
    player_view = PlayerView(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        actor_id=player_input.actor_id,
        background="现代都市调查故事。玩家正在街口选择下一处地点。",
        scene_id="history_smoke_street",
        phase="playing",
        revision="2",
        self_actor=SelfActorView(id=player_input.actor_id, name="调查员"),
        scene=SceneView(
            id="history_smoke_street",
            name="街口",
            description="街口有两条方向不同的道路。",
            available_exits=(
                AvailableExitView(
                    id="exit_to_police_station",
                    name="通往警察局的路",
                    destination=ExitDestinationView(
                        scene_id="history_smoke_police_station",
                        name="警察局",
                    ),
                ),
                AvailableExitView(
                    id="exit_to_library",
                    name="通往图书馆的路",
                    destination=ExitDestinationView(
                        scene_id="history_smoke_library",
                        name="图书馆",
                    ),
                ),
            ),
        ),
    )
    recent_history = RecentTurnContext(
        room_id=player_input.room_id,
        viewer_player_id=player_input.player_id,
        as_of_revision=player_view.revision,
        turns=(
            RecentTurn(
                correlation_id="history_smoke_previous",
                source_player_id=player_input.player_id,
                source_actor_id=player_input.actor_id,
                scene_id=player_view.scene_id,
                source_view_revision="1",
                committed_view_revision="2",
                player_utterance=VisibleHistoryText(
                    text="我要去图书馆。",
                    visibility="public",
                ),
                accepted_intent_summary="前往图书馆",
                published_narration=VisibleHistoryText(
                    text="你在街口停下，确认了图书馆的方向。",
                    visibility="public",
                ),
            ),
        ),
    )
    host_agent = build_deepseek_host_agent(
        {
            "HOST_AGENT_API_KEY": settings.deepseek_api_key.get_secret_value(),
            "HOST_AGENT_BASE_URL": settings.deepseek_base_url,
            "HOST_AGENT_MODEL": settings.deepseek_model,
            "HOST_AGENT_MAX_TURNS": str(settings.host_agent_max_turns),
            "HOST_AGENT_MAX_TOOL_CALLS": str(settings.host_agent_max_tool_calls),
            "HOST_AGENT_TOOL_TIMEOUT_SECONDS": str(settings.host_agent_tool_timeout_seconds),
            "HOST_AGENT_TIMEOUT_SECONDS": str(settings.host_agent_timeout_seconds),
        }
    )

    intent = await HostAgentIntentResolver(host_agent).resolve(
        HostAgentContext(
            player_input=player_input,
            player_view=player_view,
            recent_history=recent_history,
        )
    )

    assert intent.kind == "action"
    assert isinstance(intent.target, MatchedTarget)
    assert intent.target.id == "exit_to_library"
