"""注册、校验并原子发布仓库内置的 ModuleContentV3 模组。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from collaboration_framework.contracts import ModuleContentV3, ModulePresentation
from collaboration_framework.engine import audit_runtime_capabilities
from collaboration_framework.module import validate_module_v3_json
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.game import RulesetRead
from app.models.content import GameSystem, Scenario
from app.models.engine import ModuleVersion

MODULE_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "agent-collaboration-framework"
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
)


@dataclass(frozen=True)
class BuiltinModuleSpec:
    """声明一个内置模组的稳定身份、目录主键和权威内容路径。"""

    scenario_id: str
    module_id: str
    version: str
    world_ref: str
    source_path: Path
    display_name: str
    world_id: str | None = None


PAPER_CHASE_SPEC = BuiltinModuleSpec(
    scenario_id="00000000-0000-0000-0000-000000000003",
    module_id="paper-chase-zh-coc7",
    version="3.0.11",
    world_ref="coc-7e",
    source_path=MODULE_FIXTURE_ROOT / "追书人" / "module-content-v3.json",
    display_name="追书人",
    world_id="00000000-0000-0000-0000-000000000004",
)
SILVER_LOCK_SPEC = BuiltinModuleSpec(
    scenario_id="00000000-0000-0000-0000-000000000005",
    module_id="silver-lock",
    version="3.0.1",
    world_ref="coc-7e",
    source_path=MODULE_FIXTURE_ROOT / "银之锁" / "module-content-v3.json",
    display_name="银之锁",
)
BUILTIN_MODULE_SPECS = (PAPER_CHASE_SPEC, SILVER_LOCK_SPEC)


class BuiltinModuleLoadError(RuntimeError):
    """内置模组不能通过发布门禁或不能安全写入数据库。"""


@dataclass(frozen=True)
class BuiltinModuleLoadResult:
    """记录一次加载的身份、内容规模和幂等结果。"""

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
        """生成命令行加载脚本使用的稳定摘要。"""

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


def read_builtin_presentation(spec: BuiltinModuleSpec) -> ModulePresentation:
    """从权威内容读取玩家安全的目录展示数据。"""

    try:
        content = ModuleContentV3.model_validate_json(spec.source_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise BuiltinModuleLoadError(
            f"{spec.display_name}文件缺少有效的玩家可见 presentation"
        ) from exc
    return content.presentation


async def load_builtin_module(
    db: AsyncSession,
    spec: BuiltinModuleSpec,
    *,
    _before_commit: Callable[[], None] | None = None,
) -> BuiltinModuleLoadResult:
    """校验并原子、幂等地发布一个注册过的内置模组。"""

    try:
        payload = spec.source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuiltinModuleLoadError(
            f"无法读取固定{spec.display_name}文件: {spec.source_path}"
        ) from exc

    async with db.begin():
        system = await db.scalar(select(GameSystem).where(GameSystem.world_ref == spec.world_ref))
        if system is None:
            raise BuiltinModuleLoadError(
                f"找不到 world_ref={spec.world_ref} 的 GameSystem，请先迁移并 Seed"
            )
        if not system.ruleset:
            raise BuiltinModuleLoadError(f"{spec.world_ref} GameSystem 的 Ruleset 为空")
        try:
            RulesetRead.model_validate(system.ruleset)
        except ValidationError as exc:
            raise BuiltinModuleLoadError(
                f"{spec.world_ref} GameSystem 的 Ruleset 无法构造"
            ) from exc

        report = validate_module_v3_json(payload)
        if report.status != "pass":
            issues = "; ".join(f"{issue.code}@{issue.path}" for issue in report.errors)
            raise BuiltinModuleLoadError(
                f"{spec.display_name} Validation 未通过（status={report.status}）"
                + (f": {issues}" if issues else "")
            )
        content = ModuleContentV3.model_validate_json(payload)
        capability_issues = audit_runtime_capabilities(content)
        if capability_issues:
            rendered = "; ".join(
                f"{issue.owner}->{issue.capability}" for issue in capability_issues
            )
            raise BuiltinModuleLoadError(f"{spec.display_name}运行能力审计未通过: {rendered}")

        expected_identity = (spec.module_id, spec.version, spec.world_ref)
        actual_identity = (content.module_id, content.version, content.world_ref)
        if actual_identity != expected_identity:
            raise BuiltinModuleLoadError(
                f"{spec.display_name}身份不匹配，期望 {expected_identity!r}，"
                f"实际 {actual_identity!r}"
            )

        scenario = await db.scalar(select(Scenario).where(Scenario.module_id == spec.module_id))
        if scenario is None:
            raise BuiltinModuleLoadError(
                f"找不到 module_id={spec.module_id} 的 Scenario，请先迁移并 Seed"
            )
        if scenario.game_system_id != system.id:
            raise BuiltinModuleLoadError(
                f"{spec.display_name} Scenario 与 {spec.world_ref} GameSystem 不匹配"
            )

        normalized_content = content.to_json_dict()
        module_version = await db.get(ModuleVersion, (spec.module_id, spec.version))
        if module_version is None:
            module_version = ModuleVersion(
                module_id=spec.module_id,
                version=spec.version,
                world_ref=spec.world_ref,
                content_schema_version=3,
                content_json=normalized_content,
            )
            db.add(module_version)
            outcome = "inserted"
        elif (
            module_version.world_ref == spec.world_ref
            and module_version.content_json == normalized_content
        ):
            outcome = "unchanged"
        else:
            raise BuiltinModuleLoadError(
                "同一 (module_id, version) 已存在不同内容；"
                "请调整版本或重建本地数据库，加载器不会静默覆盖"
            )

        # Scenario 与不可变 ModuleVersion 在同一事务中发布，失败时不能留下半个 ready。
        presentation = content.presentation
        scenario.title = presentation.title
        scenario.name_en = presentation.name_en
        scenario.story_label = presentation.story_label
        scenario.subtitle = presentation.subtitle
        scenario.story_pages = [
            page.model_dump(mode="json") for page in presentation.player_intro_pages
        ]
        scenario.version = spec.version
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

    return BuiltinModuleLoadResult(
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


async def load_builtin_modules(db: AsyncSession) -> tuple[BuiltinModuleLoadResult, ...]:
    """按注册表顺序加载所有内置模组，每个模组保持独立原子事务。"""

    results = []
    for spec in BUILTIN_MODULE_SPECS:
        results.append(await load_builtin_module(db, spec))
    return tuple(results)
