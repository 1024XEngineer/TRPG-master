"""ViewProjector —— 对应 master §4.5，权限唯一出口（通信铁律一）。

暗骰（Checkpoint.hidden=true）由 ViewProjector 在裁剪时决定是否从 PlayerView
抹去，见 master §4.3.1（本次未实现 Checkpoint 相关逻辑，暗骰待后续里程碑）。

依赖 core/content（★ 2026-07-13 补，见架构演进日志同日条目）：GameState 只存
entity_states 这类 Record<string,Primitive>，场景描述/线索文本要回查内容层
才能拼出人类可读的 PlayerView，跟 RulesEngine 依赖 core/content 是同一个理由。
`project`/`project_action_menu` 是 async——要 `await content_repo.load_module`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.content.repo import ContentRepo
from core.state.models import GameState
from core.view.models import PlayerVisibleClue, PlayerView, SceneActionMenu, SceneActionMenuEntity, SceneActionMenuExit


@runtime_checkable
class ViewProjector(Protocol):
    async def project(self, state: GameState, for_whom: str) -> PlayerView:
        ...

    async def project_action_menu(self, state: GameState, for_whom: str) -> SceneActionMenu:
        ...


class StubViewProjector:
    async def project(self, state: GameState, for_whom: str) -> PlayerView:
        raise NotImplementedError("ViewProjector.project: 待实现权限裁剪逻辑")

    async def project_action_menu(self, state: GameState, for_whom: str) -> SceneActionMenu:
        raise NotImplementedError("ViewProjector.project_action_menu: 待实现")


class RealViewProjector:
    """真实实现。本次范围：场景描述 + 已发现线索 + SAN；暗骰/Checkpoint 相关裁剪留到后续。"""

    def __init__(self, content_repo: ContentRepo) -> None:
        self._content_repo = content_repo

    async def project(self, state: GameState, for_whom: str) -> PlayerView:
        player = self._find_player(state, for_whom)
        pack = await self._content_repo.load_module(state.module_id)
        scene = next((s for s in pack.scenes if s.id == player.location), None)

        visible_clues = [
            PlayerVisibleClue(id=e.id, name=e.name, content=e.content)
            for e in pack.entities
            if e.kind == "clue" and state.entity_states.get(e.id, {}).get("discovered", False)
        ]

        return PlayerView(
            for_whom=for_whom,
            visible_scene_description=scene.description if scene is not None else "",
            visible_clues=visible_clues,
            visible_san=player.san,
        )

    async def project_action_menu(self, state: GameState, for_whom: str) -> SceneActionMenu:
        player = self._find_player(state, for_whom)
        pack = await self._content_repo.load_module(state.module_id)
        scene = next((s for s in pack.scenes if s.id == player.location), None)
        if scene is None:
            return SceneActionMenu()

        entities_by_id = {e.id: e for e in pack.entities}
        scenes_by_id = {s.id: s for s in pack.scenes}

        menu_entities = [
            SceneActionMenuEntity(id=c.entity_id, name=entities_by_id[c.entity_id].name)
            for c in scene.contents
            if c.kind in ("entity_present", "clue_access") and c.entity_id in entities_by_id
        ]
        menu_exits = [
            SceneActionMenuExit(scene_id=exit_id, title=scenes_by_id[exit_id].title)
            for exit_id in scene.exits
            if exit_id in scenes_by_id
        ]
        return SceneActionMenu(entities=menu_entities, exits=menu_exits)

    def _find_player(self, state: GameState, for_whom: str):
        player = next((p for p in state.players if p.player_id == for_whom), None)
        if player is None:
            raise ValueError(f"player not found in state: {for_whom}")
        return player
