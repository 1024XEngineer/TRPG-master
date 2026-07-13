"""RulesEngine —— 对应 master §4.5 `interface RulesEngine`。

确定性，唯一写状态处；入参 state 已经是 GameStateRepo.load() 载入的、
绑定单一房间的对象——本类不直接依赖 GameStateRepo（由 Orchestrator 负责
load/save），只依赖 ContentRepo（读模组规则定义）与 SanJudgePort（依赖倒置，
见 ports.py）。`resolve_action` 是 async——真实实现要 `await content_repo.
load_module`，同步接口做不到。

五路分支（AI编排详细设计 §1.4）：
  1. kind=='unknown'                              → §6.6 脱本导回状态机接管
     ★ 本次简化：不实现真正的三级状态机（连续计数/升级提示），先统一按分支 5
       的"改成 improvised 交给 AI"处理，保证不会让连接崩掉，脱本导回的计数
       逻辑留到后续里程碑
  2. move，目标不在当前 Scene.exits                → 仅叙事拒绝，不改状态
  3. move，目标可达                                → 正常迁移 location
  4. investigate/talk，命中 Entity/Checkpoint      → 走 check 流程或直接授予效果
     ★ 2026-07-13 本次只实现 investigate 分支里 via='auto' 这一种最简子情形
       （Scene.contents 里 kind='clue_access'/'entity_present' 且 via='auto'，
       不需要 Checkpoint 掷骰），对应 walking skeleton 的最小可玩闭环；
       talk 未真正实现命中分支，统一走 improvised（见下）
  5. investigate/talk/skillCheck/ask/unknown，未命中预设内容或类型未覆盖
                                                    → AI 临场判定，不写状态
     ★ 本次除 investigate/move 外，talk/skillCheck/ask/unknown 全部统一走
       improvised（不写状态，交给 Narrator 自由发挥）——不是"正确实现"，是
       为了不让 Gateway 遇到未覆盖分支时直接抛异常断连，后续里程碑按需补齐
       各自的真实裁决逻辑
"""

from __future__ import annotations

from core.content.repo import ContentRepo
from core.rules.check_resolver import CheckResolver
from core.rules.models import ActionResult, Intent, IntentInvestigate, IntentMove
from core.rules.ports import SanJudgePort
from core.state.models import GameState


class RulesEngine:
    def __init__(
        self,
        content_repo: ContentRepo,
        check_resolver: CheckResolver,
        san_judge: SanJudgePort,
    ) -> None:
        self._content_repo = content_repo
        self._check_resolver = check_resolver
        self._san_judge = san_judge  # 依赖倒置注入，见 ports.py

    async def resolve_action(self, state: GameState, player_id: str, intent: Intent) -> ActionResult:
        if isinstance(intent, IntentInvestigate):
            return await self._resolve_investigate(state, player_id, intent)
        if isinstance(intent, IntentMove):
            return await self._resolve_move(state, player_id, intent)

        # talk / skillCheck / ask / unknown：本次统一走 improvised，见本文件顶部说明
        raw_hint = getattr(intent, "utterance", None) or getattr(intent, "question", None) or getattr(
            intent, "raw", None
        ) or getattr(intent, "skill", None) or ""
        return ActionResult(
            ok=True,
            resolution_kind="improvised",
            newly_discovered_entity_ids=[],
            public_event_summary=f"玩家的行动（{intent.kind}）没有对应的预设规则：{raw_hint}",
        )

    async def _resolve_investigate(
        self, state: GameState, player_id: str, intent: IntentInvestigate
    ) -> ActionResult:
        if not intent.target.matched:
            return ActionResult(
                ok=True,
                resolution_kind="improvised",
                newly_discovered_entity_ids=[],
                public_event_summary=f"玩家尝试调查「{intent.target.text}」，没有匹配到预设内容",
            )

        entity_id = intent.target.id

        player_state = self._find_player(state, player_id)
        if player_state is None:
            return ActionResult(
                ok=False,
                resolution_kind="blocked",
                newly_discovered_entity_ids=[],
                public_event_summary="找不到该玩家的角色状态",
            )

        pack = await self._content_repo.load_module(state.module_id)
        scene = next((s for s in pack.scenes if s.id == player_state.location), None)
        if scene is None:
            return ActionResult(
                ok=False,
                resolution_kind="blocked",
                newly_discovered_entity_ids=[],
                public_event_summary="当前场景不存在于模组内容中",
            )

        content_entry = next(
            (
                c
                for c in scene.contents
                if c.entity_id == entity_id and c.kind in ("entity_present", "clue_access")
            ),
            None,
        )
        if content_entry is None:
            return ActionResult(
                ok=False,
                resolution_kind="unrecognized",
                newly_discovered_entity_ids=[],
                public_event_summary=f"「{entity_id}」不在当前场景中",
            )

        # 本次只实现 via='auto'（无需 Checkpoint 掷骰，命中即直接授予效果）
        if content_entry.kind == "clue_access" and content_entry.via not in (None, "auto"):
            return ActionResult(
                ok=True,
                resolution_kind="improvised",
                newly_discovered_entity_ids=[],
                public_event_summary=f"「{entity_id}」需要通过 {content_entry.via} 才能调查，这条路径本次未实现，先交给 AI 即兴处理",
            )

        entity = next((e for e in pack.entities if e.id == entity_id), None)
        if entity is None:
            raise ValueError(f"Scene.contents 引用了不存在的 entity: {entity_id}")

        newly_discovered: list[str] = []
        if entity.kind == "clue":
            entity_state = state.entity_states.setdefault(entity_id, {})
            if not entity_state.get("discovered", False):
                entity_state["discovered"] = True
                newly_discovered.append(entity_id)

        return ActionResult(
            ok=True,
            resolution_kind="direct",
            newly_discovered_entity_ids=newly_discovered,
            public_event_summary=f"玩家调查了「{entity.name}」",
        )

    async def _resolve_move(self, state: GameState, player_id: str, intent: IntentMove) -> ActionResult:
        if not intent.to_scene.matched:
            return ActionResult(
                ok=True,
                resolution_kind="improvised",
                newly_discovered_entity_ids=[],
                public_event_summary=f"玩家尝试前往「{intent.to_scene.text}」，没有匹配到预设地点",
            )

        target_scene_id = intent.to_scene.id

        player_state = self._find_player(state, player_id)
        if player_state is None:
            return ActionResult(
                ok=False,
                resolution_kind="blocked",
                newly_discovered_entity_ids=[],
                public_event_summary="找不到该玩家的角色状态",
            )

        pack = await self._content_repo.load_module(state.module_id)
        current_scene = next((s for s in pack.scenes if s.id == player_state.location), None)
        if current_scene is None or target_scene_id not in current_scene.exits:
            # 分支 2：目标不在当前 Scene.exits，仅叙事拒绝，不改状态
            return ActionResult(
                ok=False,
                resolution_kind="blocked",
                newly_discovered_entity_ids=[],
                public_event_summary=f"从当前位置去不了「{target_scene_id}」",
            )

        # 分支 3：目标可达，正常迁移 location
        player_state.location = target_scene_id
        return ActionResult(
            ok=True,
            resolution_kind="direct",
            newly_discovered_entity_ids=[],
            scene_changed_to=target_scene_id,
            public_event_summary=f"玩家移动到了新的地点",
        )

    def _find_player(self, state: GameState, player_id: str):
        return next((p for p in state.players if p.player_id == player_id), None)
