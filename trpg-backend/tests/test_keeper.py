from types import SimpleNamespace

import agents
from agents.extensions import memory

from app.ai.keeper import AgentsSDKKeeper
from app.runtime.contracts import (
    ActionResult,
    ActorView,
    PlayerInput,
    PlayerView,
    SceneView,
)


async def test_deepseek_narration_uses_plain_text_output(monkeypatch):
    captured: dict[str, object] = {}

    class StubAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class StubRunner:
        @staticmethod
        async def run(agent, prompt, *, session):
            captured["prompt"] = prompt
            captured["session"] = session
            return SimpleNamespace(final_output="  门外传来轻轻的敲门声。  ")

    monkeypatch.setattr(agents, "Agent", StubAgent)
    monkeypatch.setattr(agents, "Runner", StubRunner)
    monkeypatch.setattr(memory, "SQLAlchemySession", lambda *args, **kwargs: object())

    keeper = AgentsSDKKeeper(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        engine=object(),
    )
    monkeypatch.setattr(keeper, "_model", lambda: object())

    player_input = PlayerInput(
        request_id="request-1",
        room_id="room-1",
        room_session_id="session-1",
        player_id="player-1",
        actor_id="actor-1",
        source_revision=1,
        utterance="我听听门外有什么声音",
    )
    view = PlayerView(
        room_id="room-1",
        room_session_id="session-1",
        state_revision=1,
        event_sequence=1,
        scene=SceneView(
            scene_id="scene-1",
            name="书房",
            player_description="你站在安静的书房里。",
        ),
        actor=ActorView(
            actor_id="actor-1",
            name="调查员",
            current_hp=10,
            current_mp=10,
            current_san=50,
        ),
    )
    action = ActionResult(
        request_id="request-1",
        resolution="resolved",
        outcome="玩家侧耳倾听",
        state_revision=1,
        state_changed=False,
    )

    narration = await keeper.narrate(player_input, view, action)

    assert narration.text == "门外传来轻轻的敲门声。"
    assert "output_type" not in captured
