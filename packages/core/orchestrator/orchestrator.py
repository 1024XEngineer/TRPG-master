"""Orchestrator.handle_turn —— 对应 master §4.5，串联一次「输入→输出」全流程。

通信风格：一次玩家输入 = 一次「回合请求」，模块间是进程内同步接口调用
（Orchestrator 挨个调下游，不做模块间点对点乱调），见 master §2.1。
"""

from __future__ import annotations

from core.ai.intent import IntentParser
from core.ai.narrator import Narrator
from core.rules.engine import RulesEngine
from core.state.repo import GameStateRepo
from core.view.models import PlayerView
from core.view.projector import ViewProjector


class TurnResult:
    def __init__(self, narration: str, view: PlayerView) -> None:
        self.narration = narration
        self.view = view


class Orchestrator:
    def __init__(
        self,
        game_state_repo: GameStateRepo,
        intent_parser: IntentParser,
        rules_engine: RulesEngine,
        view_projector: ViewProjector,
        narrator: Narrator,
    ) -> None:
        self._game_state_repo = game_state_repo
        self._intent_parser = intent_parser
        self._rules_engine = rules_engine
        self._view_projector = view_projector
        self._narrator = narrator

    async def handle_turn(self, room_id: str, player_id: str, utterance: str) -> TurnResult:
        """真实串联链路（内部各被调用者是桩，会抛 NotImplementedError；串联关系本身是真的）：
        1. 通信铁律二：跨房间隔离唯一入口加载状态
        2. 通信铁律一：先裁出受限视角 + 安全菜单，IntentParser 才能解析
        3. RulesEngine 确定性裁决（唯一写状态处）
        4. 落盘（RulesEngine 在原地修改 state，这里统一持久化）
        5. 裁决后重新投影视角（状态已变）
        6. Narrator 依据受限视角 + 裁决结果生成流式叙事
        """
        state = await self._game_state_repo.load(room_id)

        view_before = await self._view_projector.project(state, player_id)
        menu = await self._view_projector.project_action_menu(state, player_id)

        intent = await self._intent_parser.parse_intent(utterance, view_before, menu)

        action_result = await self._rules_engine.resolve_action(state, player_id, intent)

        await self._game_state_repo.save(state)

        view_after = await self._view_projector.project(state, player_id)

        narration_chunks: list[str] = []
        async for chunk in self._narrator.narrate("narrator", view_after, action_result):
            narration_chunks.append(chunk)

        return TurnResult(narration="".join(narration_chunks), view=view_after)
