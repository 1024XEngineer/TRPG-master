"""从唯一的《追书人》ModulePackage 同步开发/测试内容目录。

Scenario 只保存可查询的目录投影；不可变 ``ScenarioRevision.package_json`` 才是
运行时事实源。所有标题、人数、简介、时长和预制角色都从 JSON 派生，前后端不再
维护展示用模组副本。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_content import build_coc7_ruleset
from app.core.config import get_settings
from app.models.content import Game, GameSystem, ModulePregen, Scenario, ScenarioRevision
from app.module_runtime import ModuleLoader

BUILTIN_GAME_ID = "00000000-0000-0000-0000-000000000001"
BUILTIN_SYSTEM_ID = "00000000-0000-0000-0000-000000000002"
BUILTIN_SCENARIO_ID = "00000000-0000-0000-0000-000000000003"


async def ensure_seed_content(db: AsyncSession) -> None:
    """幂等同步 COC7 规则目录和《追书人》当前 revision。"""
    settings = get_settings()
    coc7_ruleset = build_coc7_ruleset().model_dump(mode="json")

    game = await db.get(Game, BUILTIN_GAME_ID)
    if game is None:
        game = Game(
            id=BUILTIN_GAME_ID,
            name="克苏鲁的呼唤",
            description="COC 内置游戏大类（种子数据）",
        )
        db.add(game)

    system = await db.get(GameSystem, BUILTIN_SYSTEM_ID)
    if system is None:
        system = GameSystem(
            id=BUILTIN_SYSTEM_ID,
            game_id=BUILTIN_GAME_ID,
            name="COC7",
            version="7th",
            ruleset=coc7_ruleset,
        )
        db.add(system)
    elif system.ruleset != coc7_ruleset:
        system.ruleset = coc7_ruleset

    if settings.app_env == "production" and not settings.allow_uncleared_modules:
        # 生产环境可以正常启动并提供规则系统，但不会暴露权利未确认的样例模组。
        # 已经由开发环境写入同一数据库的 revision 也要从可选目录撤下；进行中的
        # RoomSession 仍固定自己的快照，可继续回放。
        scenario = await db.get(Scenario, BUILTIN_SCENARIO_ID)
        if scenario is not None and scenario.current_revision_id is not None:
            revision = await db.get(
                ScenarioRevision, scenario.current_revision_id
            )
            if revision is not None and revision.rights_status != "cleared":
                revision.status = "rights_blocked"
        await db.commit()
        return

    runtime_module = ModuleLoader().load_default(allow_uncleared=True)
    package = runtime_module.package
    module = package.module
    scenario = await db.get(Scenario, BUILTIN_SCENARIO_ID)
    if scenario is None:
        scenario = Scenario(
            id=BUILTIN_SCENARIO_ID,
            game_system_id=BUILTIN_SYSTEM_ID,
            title=module.title,
            version=package.package_id.rsplit(".", maxsplit=1)[-1],
            authors=[],
            players_min=module.player_count.investigators_min,
            players_max=module.player_count.investigators_max,
            difficulty=1,
            estimated_duration=module.estimated_duration,
            synopsis=module.premise,
        )
        db.add(scenario)
        await db.flush()
    else:
        scenario.title = module.title
        scenario.version = package.package_id.rsplit(".", maxsplit=1)[-1]
        scenario.players_min = module.player_count.investigators_min
        scenario.players_max = module.player_count.investigators_max
        scenario.estimated_duration = module.estimated_duration
        scenario.synopsis = module.premise

    revision = await db.scalar(
        select(ScenarioRevision).where(
            ScenarioRevision.scenario_id == scenario.id,
            ScenarioRevision.checksum == runtime_module.checksum,
        )
    )
    if revision is None:
        rights = package.source_manifest.rights
        rights_status = "cleared" if rights.cleared_for_distribution else "not_cleared"
        revision = ScenarioRevision(
            scenario_id=scenario.id,
            package_id=package.package_id,
            schema_version=package.package_schema_version,
            checksum=runtime_module.checksum,
            status=package.package_status,
            rights_status=rights_status,
            package_json=runtime_module.package_json,
        )
        db.add(revision)
        await db.flush()
    else:
        revision.status = package.package_status
    scenario.current_revision_id = revision.id

    existing_pregens = {
        pregen.source_character_id: pregen
        for pregen in (
            await db.scalars(
                select(ModulePregen).where(
                    ModulePregen.scenario_id == scenario.id,
                    ModulePregen.revision_id == revision.id,
                )
            )
        ).all()
    }
    for character_id in module.character_setup.pregenerated_character_ids:
        if character_id in existing_pregens:
            continue
        character = runtime_module.get("characters", character_id)
        if character is None:  # Loader 已验证引用；保留防御式检查。
            continue
        db.add(
            ModulePregen(
                scenario_id=scenario.id,
                revision_id=revision.id,
                source_character_id=character_id,
                name=str(character["name"]),
                data=character,
            )
        )

    await db.commit()
