from types import SimpleNamespace

import agents
from agents.extensions import memory

from app.ai.keeper import AgentsSDKKeeper
from app.runtime.contracts import (
    ActionResult,
    ActorView,
    Intent,
    PlayerInput,
    PlayerView,
    SceneView,
)


def _player_view() -> PlayerView:
    return PlayerView(
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
            occupation="记者",
            current_hp=10,
            current_mp=10,
            current_san=50,
        ),
    )


async def test_deepseek_opening_uses_player_safe_plain_text(monkeypatch):
    captured: dict[str, object] = {}

    class StubAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class StubRunner:
        @staticmethod
        async def run(agent, prompt, *, session):
            captured["prompt"] = prompt
            captured["session"] = session
            return SimpleNamespace(
                final_output="  你来到托马斯的书房。可以询问委托，也可以观察环境。你准备怎么做？  "
            )

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

    narration = await keeper.opening(_player_view(), "调查叔叔失踪与旧书失窃的真相")

    assert narration.text.endswith("你准备怎么做？")
    assert "output_type" not in captured
    assert "调查叔叔失踪与旧书失窃的真相" in str(captured["prompt"])
    assert "scene-1" not in str(captured["prompt"])
    assert "actor-1" not in str(captured["prompt"])


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
    view = _player_view()
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


async def test_keeper_private_decision_context_is_not_written_to_player_session(monkeypatch):
    captured: dict[str, object] = {}

    class StubAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.tools = kwargs["tools"]

    class StubRunner:
        @staticmethod
        async def run(agent, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["runner_kwargs"] = kwargs
            await agent.tools[0](
                Intent(
                    kind="free",
                    summary="隐藏真相：道格拉斯是食尸鬼",
                    approach="根据隐藏真相行动",
                )
            )
            return SimpleNamespace(final_output="")

    monkeypatch.setattr(agents, "Agent", StubAgent)
    monkeypatch.setattr(agents, "Runner", StubRunner)
    monkeypatch.setattr(agents, "function_tool", lambda function: function)

    keeper = AgentsSDKKeeper(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        engine=object(),
    )
    monkeypatch.setattr(keeper, "_model", lambda: object())
    player_input = PlayerInput(
        request_id="request-private",
        room_id="room-1",
        room_session_id="session-1",
        player_id="player-1",
        actor_id="actor-1",
        source_revision=1,
        utterance="我环顾四周",
    )
    executed: list[Intent] = []

    async def execute_action(intent: Intent) -> ActionResult:
        executed.append(intent)
        return ActionResult(
            request_id="request-private",
            resolution="resolved",
            outcome="action_resolved",
            state_revision=2,
            state_changed=False,
        )

    await keeper.run_action(
        player_input,
        _player_view(),
        {"keeperBrief": {"coreTruth": "道格拉斯是食尸鬼"}},
        execute_action,
    )

    assert "道格拉斯是食尸鬼" in str(captured["prompt"])
    runner_kwargs = captured["runner_kwargs"]
    assert isinstance(runner_kwargs, dict)
    assert "session" not in runner_kwargs
    assert getattr(runner_kwargs.get("run_config"), "tracing_disabled", False) is True
    assert executed[0].summary == "我环顾四周"
    assert executed[0].approach == "我环顾四周"
