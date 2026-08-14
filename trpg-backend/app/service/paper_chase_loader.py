"""将仓库内固定的追书人 ModuleContent 加载到本地数据库。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from collaboration_framework.contracts import ModuleContentV3, ModulePresentation
from collaboration_framework.module import validate_module_v3_json
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.game import RulesetRead
from app.models.content import GameSystem, Scenario
from app.models.engine import ModuleVersion

PAPER_CHASE_MODULE_ID = "paper-chase-zh-coc7"
PAPER_CHASE_VERSION = "3.0.6"
PAPER_CHASE_CONTENT_SCHEMA_VERSION = 3
PAPER_CHASE_WORLD_REF = "coc-7e"
PAPER_CHASE_SOURCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "agent-collaboration-framework"
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)


def read_paper_chase_presentation() -> ModulePresentation:
    """Read the player-safe presentation from the same source as the loader."""

    try:
        payload = json.loads(PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8"))
        return ModulePresentation.model_validate(payload["presentation"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PaperChaseLoadError("追书人文件缺少有效的玩家可见 presentation") from exc


class PaperChaseLoadError(RuntimeError):
    """追书人不能通过校验或不能安全写入数据库。"""


@dataclass(frozen=True)
class PaperChaseLoadResult:
    module_id: str
    version: str
    world_ref: str
    location_count: int
    entity_count: int
    information_count: int
    rule_count: int
    ending_anchor_count: int
    outcome: str

    def summary_lines(self) -> tuple[str, ...]:
        return (
            f"module_id: {self.module_id}",
            f"version: {self.version}",
            f"world_ref: {self.world_ref}",
            f"locations: {self.location_count}",
            f"entities: {self.entity_count}",
            f"information: {self.information_count}",
            f"rules: {self.rule_count}",
            f"ending_anchors: {self.ending_anchor_count}",
            f"result: {self.outcome}",
        )


async def load_paper_chase(
    db: AsyncSession,
    *,
    _before_commit: Callable[[], None] | None = None,
) -> PaperChaseLoadResult:
    """校验并原子、幂等地加载固定的追书人 JSON。"""

    try:
        payload = PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise PaperChaseLoadError(f"无法读取固定追书人文件: {PAPER_CHASE_SOURCE_PATH}") from exc

    async with db.begin():
        system = await db.scalar(
            select(GameSystem).where(GameSystem.world_ref == PAPER_CHASE_WORLD_REF)
        )
        if system is None:
            raise PaperChaseLoadError("找不到 world_ref=coc-7e 的 GameSystem，请先迁移并 Seed")
        if not system.ruleset:
            raise PaperChaseLoadError("coc-7e GameSystem 的 Ruleset 为空")
        try:
            RulesetRead.model_validate(system.ruleset)
        except ValidationError as exc:
            raise PaperChaseLoadError("coc-7e GameSystem 的 Ruleset 无法构造") from exc

        # v3 no longer needs a skill catalogue at load time: skills live inside
        # a Rule's Check Profile parameters, and the Engine validates them
        # against the Actor's own Ruleset snapshot at submit time.
        report = validate_module_v3_json(payload)
        if report.status != "pass":
            issues = "; ".join(f"{issue.code}@{issue.path}" for issue in report.errors)
            raise PaperChaseLoadError(
                f"追书人 Validation 未通过（status={report.status}）"
                + (f": {issues}" if issues else "")
            )
        content = ModuleContentV3.model_validate_json(payload)
        actual_identity = (content.module_id, content.version, content.world_ref)
        expected_identity = (
            PAPER_CHASE_MODULE_ID,
            PAPER_CHASE_VERSION,
            PAPER_CHASE_WORLD_REF,
        )
        if actual_identity != expected_identity:
            raise PaperChaseLoadError(
                f"追书人身份不匹配，期望 {expected_identity!r}，实际 {actual_identity!r}"
            )

        scenario = await db.scalar(
            select(Scenario).where(Scenario.module_id == PAPER_CHASE_MODULE_ID)
        )
        if scenario is None:
            raise PaperChaseLoadError(
                "找不到 module_id=paper-chase-zh-coc7 的 Scenario，请先迁移并 Seed"
            )
        if scenario.game_system_id != system.id:
            raise PaperChaseLoadError("追书人 Scenario 与 coc-7e GameSystem 不匹配")
        if content.presentation is None:
            raise PaperChaseLoadError("追书人发布内容缺少玩家可见 presentation")

        normalized_content = content.to_json_dict()
        module_version = await db.get(
            ModuleVersion,
            (PAPER_CHASE_MODULE_ID, PAPER_CHASE_VERSION),
        )
        if module_version is None:
            module_version = ModuleVersion(
                module_id=PAPER_CHASE_MODULE_ID,
                version=PAPER_CHASE_VERSION,
                world_ref=PAPER_CHASE_WORLD_REF,
                content_schema_version=PAPER_CHASE_CONTENT_SCHEMA_VERSION,
                content_json=normalized_content,
            )
            db.add(module_version)
            outcome = "inserted"
        elif (
            module_version.world_ref == PAPER_CHASE_WORLD_REF
            and module_version.content_schema_version == PAPER_CHASE_CONTENT_SCHEMA_VERSION
            and module_version.content_json == normalized_content
        ):
            outcome = "unchanged"
        else:
            raise PaperChaseLoadError(
                "同一 (module_id, version) 已存在不同内容；"
                "请调整版本或重建本地数据库，加载器不会静默覆盖"
            )

        presentation = content.presentation
        scenario.title = presentation.title
        scenario.name_en = presentation.name_en
        scenario.story_label = presentation.story_label
        scenario.subtitle = presentation.subtitle
        scenario.story_pages = [
            page.model_dump(mode="json") for page in presentation.player_intro_pages
        ]
        scenario.version = PAPER_CHASE_VERSION
        scenario.authors = list(presentation.authors)
        scenario.players_min = presentation.players_min
        scenario.players_max = presentation.players_max
        scenario.difficulty = presentation.difficulty
        scenario.estimated_duration = presentation.estimated_duration
        scenario.synopsis = presentation.synopsis
        scenario.status = "ready"
        await db.flush()
        if _before_commit is not None:
            _before_commit()

    return PaperChaseLoadResult(
        module_id=content.module_id,
        version=content.version,
        world_ref=content.world_ref,
        location_count=len(content.locations),
        entity_count=len(content.entities),
        information_count=len(content.information),
        rule_count=len(content.rules),
        ending_anchor_count=len(content.ending_anchors),
        outcome=outcome,
    )
