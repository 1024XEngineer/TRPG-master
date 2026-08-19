"""Published content used only by backend and SDK E2E test databases."""

from collaboration_framework.contracts import ModuleContentV3
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import BUILTIN_SYSTEM_ID
from app.models.content import GameSystem, Scenario
from app.models.engine import ModuleVersion
from app.service.paper_chase_loader import (
    PAPER_CHASE_CONTENT_SCHEMA_VERSION,
    PAPER_CHASE_SOURCE_PATH,
)

MULTIPLAYER_MODULE_ID = "e2e-multiplayer-coc7"
MULTIPLAYER_VERSION = "1.0.0"
MULTIPLAYER_SCENARIO_ID = "00000000-0000-0000-0000-000000000154"


async def publish_multiplayer_module(db: AsyncSession) -> None:
    """Clone playable content with a 1-2 player presentation for multiplayer tests."""

    source = ModuleContentV3.model_validate_json(
        PAPER_CHASE_SOURCE_PATH.read_text(encoding="utf-8")
    )
    payload = source.to_json_dict()
    payload["module_id"] = MULTIPLAYER_MODULE_ID
    payload["version"] = MULTIPLAYER_VERSION
    presentation = payload["presentation"]
    presentation["title"] = "追书人（E2E 双人夹具）"
    presentation["name_en"] = "E2E Multiplayer Fixture"
    presentation["players_max"] = 3
    content = ModuleContentV3.model_validate(payload)
    assert content.presentation is not None

    system = await db.get(GameSystem, BUILTIN_SYSTEM_ID)
    if system is None:
        raise RuntimeError("E2E 多人模组缺少 COC7 规则系统")

    scenario = Scenario(
        id=MULTIPLAYER_SCENARIO_ID,
        module_id=MULTIPLAYER_MODULE_ID,
        game_system_id=system.id,
        title=content.presentation.title,
        status="ready",
        name_en=content.presentation.name_en,
        story_label=content.presentation.story_label,
        subtitle=content.presentation.subtitle,
        story_pages=[
            page.model_dump(mode="json") for page in content.presentation.player_intro_pages
        ],
        version=MULTIPLAYER_VERSION,
        authors=list(content.presentation.authors),
        players_min=content.presentation.players_min,
        players_max=content.presentation.players_max,
        difficulty=content.presentation.difficulty,
        estimated_duration=content.presentation.estimated_duration,
        synopsis=content.presentation.synopsis,
    )
    db.add(scenario)
    await db.flush()
    db.add(
        ModuleVersion(
            module_id=MULTIPLAYER_MODULE_ID,
            version=MULTIPLAYER_VERSION,
            world_ref=content.world_ref,
            content_schema_version=PAPER_CHASE_CONTENT_SCHEMA_VERSION,
            content_json=content.to_json_dict(),
        )
    )
    await db.commit()
