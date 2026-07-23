"""单 KeeperAgent 端口、确定性 Fake 与 OpenAI Agents SDK 适配器。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.runtime.contracts import (
    ActionResult,
    Intent,
    NarrationOutput,
    PlayerInput,
    PlayerView,
)

ExecuteAction = Callable[[Intent], Awaitable[ActionResult]]


def _player_safe_action(action: ActionResult) -> ActionResult:
    """移除只供规则引擎使用的事件和隐藏 Fact 标识后再交给模型/会话存储。"""
    return action.model_copy(
        update={
            "events": [
                event for event in action.events if event.visibility != "keeper"
            ],
            "narration_facts": [],
        }
    )


class KeeperAgentPort(Protocol):
    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        execute_action: ExecuteAction,
    ) -> ActionResult: ...

    async def narrate(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        action: ActionResult,
    ) -> NarrationOutput: ...


class FakeKeeper:
    """CI/离线纵切使用；只从 PlayerView 的可信候选中选择。"""

    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        execute_action: ExecuteAction,
    ) -> ActionResult:
        intent = self._decide(player_input.utterance, view)
        return await execute_action(intent)

    async def narrate(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        action: ActionResult,
    ) -> NarrationOutput:
        del player_input
        for event in reversed(action.events):
            if event.event_type == "game.ended":
                return NarrationOutput(
                    text=str(event.payload.get("summary") or "这场调查已经结束。")
                )
            if event.event_type == "scene.changed":
                description = (
                    event.payload.get("playerDescription")
                    or view.scene.player_description
                )
                return NarrationOutput(
                    text=str(description)
                )
            if event.event_type == "clue.granted":
                clue_text = event.payload.get("description") or event.payload.get("name")
                return NarrationOutput(
                    text=f"你获得了新的线索：{clue_text}。"
                )
            if event.event_type == "check.resolved":
                return NarrationOutput(
                    text=(
                        f"检定掷出了 {event.payload.get('rollValue')}，"
                        f"结果为 {event.payload.get('grade')}。"
                    )
                )
            if event.event_type == "san.resolved":
                return NarrationOutput(
                    text=(
                        f"理智检定掷出了 {event.payload.get('rollValue')}，"
                        f"损失 {event.payload.get('sanLoss')} 点理智。"
                    )
                )
        if action.pending_check:
            return NarrationOutput(
                text=f"这个行动需要进行 {action.pending_check.skill_id or '理智'} 检定。"
            )
        return NarrationOutput(text="守秘人记下了你的行动，局势继续发展。")

    @staticmethod
    def _decide(utterance: str, view: PlayerView) -> Intent:
        text = utterance.strip().lower()
        scene_targets = {
            "邻居": "scene.neighborhood",
            "图书馆": "scene.library",
            "报社": "scene.newspaper",
            "档案": "scene.newspaper",
            "旧宅": "scene.kimball_house",
            "书房": "scene.kimball_house",
            "墓地": "scene.cemetery",
            "监视": "scene.surveillance",
            "地穴": "scene.crypt",
            "石板": "scene.crypt",
        }
        for keyword, scene_id in scene_targets.items():
            if keyword in text and scene_id != view.scene.scene_id:
                return Intent(
                    kind="choice",
                    summary=f"前往{keyword}",
                    choice_id=scene_id,
                )
        if any(word in text for word in ("跟随", "地下")):
            return Intent(
                kind="choice",
                summary="跟随道格拉斯进入地下",
                choice_id="follow_douglas_underground",
            )
        if any(word in text for word in ("攻击食尸鬼", "攻击怪物")):
            return Intent(
                kind="choice", summary="攻击食尸鬼群", choice_id="attack_ghouls"
            )
        if any(word in text for word in ("逃走", "逃离", "离开")):
            return Intent(kind="choice", summary="逃离现场", choice_id="flee")
        if any(word in text for word in ("叫名字", "道格拉斯")) and view.scene.scene_id == (
            "scene.confrontation"
        ):
            return Intent(
                kind="choice", summary="呼喊道格拉斯的名字", choice_id="call_name"
            )
        if any(word in text for word in ("交谈", "对话", "听他说", "礼貌")):
            return Intent(
                kind="dialogue",
                summary="与眼前的人物进行非敌对对话",
                target_id=(
                    view.visible_entities[0].entity_id
                    if view.visible_entities
                    else None
                ),
            )
        if view.checkpoint_options and any(
            word in text
            for word in (
                "调查",
                "寻找",
                "搜索",
                "查看",
                "询问",
                "研究",
                "追踪",
                "打开",
                "移动",
            )
        ):
            option = view.checkpoint_options[0]
            return Intent(
                kind="checkpoint",
                summary=utterance,
                checkpoint_id=option.checkpoint_id,
                skill_id=option.skills[0],
                approach=utterance,
            )
        return Intent(kind="free", summary=utterance, approach=utterance)


class AgentsSDKKeeper:
    """OpenAI-compatible Chat Completions 上的单 Agent 实现。

    导入放在运行期，未配置真实模型的测试/本地开发不会因为可选依赖或密钥缺失
    而影响其它 API。Agent 只能看到 PlayerView，并且必须通过唯一 Function Tool
    ``execute_action`` 进入权威规则引擎。
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        engine,
    ) -> None:
        self.model_name = model
        self.base_url = base_url
        self.api_key = api_key
        self.engine = engine

    def _model(self):
        try:
            from agents import OpenAIChatCompletionsModel
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - exercised only with live provider.
            raise RuntimeError("请安装 openai-agents[sqlalchemy] 后再启用真实 Keeper") from exc
        return OpenAIChatCompletionsModel(
            model=self.model_name,
            openai_client=AsyncOpenAI(base_url=self.base_url, api_key=self.api_key),
        )

    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        execute_action: ExecuteAction,
    ) -> ActionResult:
        try:
            from agents import Agent, Runner, function_tool
            from agents.extensions.memory import SQLAlchemySession
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI Agents SDK 不可用") from exc

        captured: ActionResult | None = None
        execute_action_callback = execute_action

        @function_tool
        async def execute_action_tool(intent: Intent) -> str:
            """提交一个且仅一个玩家行动给权威规则引擎。"""
            nonlocal captured
            if captured is not None:
                raise RuntimeError("一个玩家行动只能调用一次 execute_action")
            captured = await execute_action_callback(intent)
            safe_result = _player_safe_action(captured)
            return json.dumps(safe_result.model_dump(mode="json"), ensure_ascii=False)

        agent = Agent(
            name="KeeperAgent",
            instructions=(
                "你是单人 COC7 跑团守秘人。只能依据给出的 PlayerView 和候选 ID "
                "理解玩家行动；必须且只能调用一次 execute_action，不能自行决定骰值、"
                "授予线索、切换场景或宣告结局。"
            ),
            model=self._model(),
            tools=[execute_action_tool],
            tool_use_behavior="stop_on_first_tool",
        )
        session = SQLAlchemySession(
            player_input.room_session_id,
            engine=self.engine,
            create_tables=False,
        )
        prompt = json.dumps(
            {
                "playerUtterance": player_input.utterance,
                "playerView": view.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        await Runner.run(agent, prompt, session=session)
        if captured is None:
            raise RuntimeError("KeeperAgent 未调用 execute_action")
        return captured

    async def narrate(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        action: ActionResult,
    ) -> NarrationOutput:
        try:
            from agents import Agent, Runner
            from agents.extensions.memory import SQLAlchemySession
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI Agents SDK 不可用") from exc
        agent = Agent(
            name="KeeperAgent",
            instructions=(
                "根据玩家安全的 ActionResult 和 PlayerView，用简洁中文叙述结果。"
                "不得补充输入中没有的真相、线索、骰值或状态变化。"
            ),
            model=self._model(),
            output_type=NarrationOutput,
        )
        session = SQLAlchemySession(
            player_input.room_session_id,
            engine=self.engine,
            create_tables=False,
        )
        result = await Runner.run(
            agent,
            json.dumps(
                {
                    "actionResult": _player_safe_action(action).model_dump(mode="json"),
                    "playerView": view.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
            session=session,
        )
        return NarrationOutput.model_validate(result.final_output)
