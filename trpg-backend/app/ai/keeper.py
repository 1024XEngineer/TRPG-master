"""单 KeeperAgent 端口、确定性 Fake 与 OpenAI Agents SDK 适配器。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

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
            "events": [event for event in action.events if event.visibility != "keeper"],
            "narration_facts": [],
        }
    )


class KeeperAgentPort(Protocol):
    async def opening(self, view: PlayerView, premise: str) -> NarrationOutput: ...

    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        decision_context: dict[str, Any],
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

    async def opening(self, view: PlayerView, premise: str) -> NarrationOutput:
        identity = view.actor.name
        if view.actor.occupation:
            identity += f"（{view.actor.occupation}）"
        directions: list[str] = []
        if view.visible_entities:
            directions.append(f"与{view.visible_entities[0].name}交谈")
        if view.checkpoint_options:
            directions.append("观察并调查当前环境")
        directions.append("提出其他合理行动")
        return NarrationOutput(
            text=(
                f"{view.scene.player_description}\n\n"
                f"你将以{identity}的身份展开调查。当前任务是：{premise} "
                f"你可以先{'、'.join(directions)}。你准备怎么做？"
            )
        )

    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        decision_context: dict[str, Any],
        execute_action: ExecuteAction,
    ) -> ActionResult:
        del decision_context
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
                    event.payload.get("playerDescription") or view.scene.player_description
                )
                return NarrationOutput(text=str(description))
            if event.event_type == "clue.granted":
                clue_text = event.payload.get("description") or event.payload.get("name")
                return NarrationOutput(text=f"你获得了新的线索：{clue_text}。")
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
        if any(word in text for word in ("地图", "路线", "有哪些地点", "能去哪里")):
            return Intent(kind="free", summary=utterance, approach=utterance)
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
            return Intent(kind="choice", summary="攻击食尸鬼群", choice_id="attack_ghouls")
        if any(word in text for word in ("逃走", "逃离", "离开")):
            return Intent(kind="choice", summary="逃离现场", choice_id="flee")
        if any(word in text for word in ("叫名字", "道格拉斯")) and view.scene.scene_id == (
            "scene.confrontation"
        ):
            return Intent(kind="choice", summary="呼喊道格拉斯的名字", choice_id="call_name")
        if any(word in text for word in ("交谈", "对话", "听他说", "礼貌")):
            return Intent(
                kind="dialogue",
                summary="与眼前的人物进行非敌对对话",
                target_id=(view.visible_entities[0].entity_id if view.visible_entities else None),
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
                skill_id=None if option.bypass_reason else option.skills[0],
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

    async def opening(self, view: PlayerView, premise: str) -> NarrationOutput:
        try:
            from agents import Agent, Runner
            from agents.extensions.memory import SQLAlchemySession
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI Agents SDK 不可用") from exc
        agent = Agent(
            name="KeeperAgent",
            instructions=(
                "你是单人 COC7 跑团守秘人。输入中的 safeOpeningFacts 是完整且唯一的"
                "事实来源，不得推断或新增任何具体物件、人物关系、对话、动作、外貌、"
                "地点陈设或线索；尤其不得把公开任务中 NPC 的亲属关系套到调查员身上。"
                "严格按以下顺序输出：第一段逐字复制 sceneDescription，不得改写或扩写；"
                "第二段只用 investigatorName、investigatorOccupation 说明调查员身份；"
                "第三段以“当前公开任务是：”开头并逐字复制 publicPremise；"
                "第四段只连接 suggestedActions 中已有的行动方向，不得添加新名词；"
                "最后以“你准备怎么做？”收尾。"
                "不得泄露隐藏真相或未获得线索，不得输出内部 ID、JSON、字段名、"
                "Markdown 列表或代码块。"
            ),
            model=self._model(),
        )
        session = SQLAlchemySession(
            view.room_session_id,
            engine=self.engine,
            create_tables=False,
        )
        suggested_actions: list[str] = []
        if view.visible_entities:
            names = "、".join(entity.name for entity in view.visible_entities)
            suggested_actions.append(f"与当前可见人物交谈或提问：{names}")
        if view.checkpoint_options:
            suggested_actions.append("观察或调查当前环境，并说明想检查的目标")
        suggested_actions.append("提出符合当前情境的其他行动")
        safe_opening_facts = {
            "investigatorName": view.actor.name,
            "investigatorOccupation": view.actor.occupation,
            "publicPremise": premise,
            "sceneName": view.scene.name,
            "sceneDescription": view.scene.player_description,
            "visibleEntities": [
                {
                    "name": entity.name,
                    "publicDescription": entity.public_description,
                }
                for entity in view.visible_entities
            ],
            "suggestedActions": suggested_actions,
        }
        result = await Runner.run(
            agent,
            json.dumps(
                {"safeOpeningFacts": safe_opening_facts},
                ensure_ascii=False,
            ),
            session=session,
        )
        text = str(result.final_output or "").strip()
        if not text:
            raise RuntimeError("KeeperAgent 返回了空开场叙事")
        return NarrationOutput(text=text)

    async def run_action(
        self,
        player_input: PlayerInput,
        view: PlayerView,
        decision_context: dict[str, Any],
        execute_action: ExecuteAction,
    ) -> ActionResult:
        try:
            from agents import Agent, RunConfig, Runner, function_tool
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
            # Keeper 私有上下文只允许影响结构化候选 ID，任何可能被玩家看到的
            # 自然语言都强制取自玩家原话，避免隐藏事实借 intent.summary 泄露。
            safe_intent = intent.model_copy(
                update={
                    "summary": player_input.utterance,
                    "approach": player_input.utterance if intent.approach else None,
                }
            )
            captured = await execute_action_callback(safe_intent)
            safe_result = _player_safe_action(captured)
            return json.dumps(safe_result.model_dump(mode="json"), ensure_ascii=False)

        agent = Agent(
            name="KeeperAgent",
            instructions=(
                "你是单人 COC7 跑团守秘人的私有裁决阶段。结合 PlayerView 与"
                "KeeperDecisionContext 理解玩家行动，并从上下文提供的真实候选 ID "
                "中选择 Intent；玩家行动若与 availableCheckpoints 的 action_label "
                "相符，必须选择 checkpoint（即使该职业符合免检条件，也由规则引擎"
                "完成免检结算）；明确前往 reachableScenes 时选择对应 scene ID 的 choice。"
                "必须且只能调用一次 execute_action。不得自行决定骰值、"
                "授予线索、切换场景或宣告结局，不得在 Intent 自然语言字段中写入"
                "玩家原话没有包含的隐藏事实。"
            ),
            model=self._model(),
            tools=[execute_action_tool],
            tool_use_behavior="stop_on_first_tool",
        )
        prompt = json.dumps(
            {
                "playerUtterance": player_input.utterance,
                "playerView": view.model_dump(mode="json"),
                "keeperDecisionContext": decision_context,
            },
            ensure_ascii=False,
        )
        # 私有 Keeper 上下文不能写进只允许保存玩家可见历史的 SQLAlchemySession。
        await Runner.run(
            agent,
            prompt,
            run_config=RunConfig(tracing_disabled=True),
        )
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
                "只输出直接展示给玩家的叙事正文，不要输出 JSON、字段名或代码块。"
            ),
            model=self._model(),
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
                    "playerUtterance": player_input.utterance,
                    "actionResult": _player_safe_action(action).model_dump(mode="json"),
                    "playerView": view.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
            session=session,
        )
        # DeepSeek 的 OpenAI-compatible Chat Completions 当前不支持 Agents SDK
        # 为 ``output_type`` 生成的 response_format。这里让模型返回普通文本，
        # 再在服务端包装为稳定 DTO；玩家安全边界仍由上面的输入投影保证。
        text = str(result.final_output or "").strip()
        if not text:
            raise RuntimeError("KeeperAgent 返回了空叙事")
        return NarrationOutput(text=text)
