"""CoC7 source identities, including a bounded map for immutable old versions."""

from collaboration_framework.contracts import (
    ContractError,
    ModuleContentV3,
    RuleCheckSpec,
)
from collaboration_framework.contracts.sanity import SanitySource

# These rules describe the same creature type, regardless of its display name.
LEGACY_SOURCES = {
    (
        "paper-chase-zh-coc7",
        "3.0.12",
        "first_sight_of_douglas",
        "san_check",
    ): SanitySource(id="coc7.ghoul", habit_cap=6),
    ("paper-chase-zh-coc7", "3.0.12", "ghoul_crowd_sanity", "crowd_san"): SanitySource(
        id="coc7.ghoul", habit_cap=6
    ),
    ("silver-lock", "3.0.4", "rat_thing_sanity", "san"): SanitySource(
        id="coc7.rat_thing", habit_cap=6
    ),
    ("silver-lock", "3.0.4", "door_ghost_sanity", "san"): SanitySource(
        id="silver_lock.door_ghost"
    ),
    (
        "constant-darkness-box-zh-coc7",
        "3.0.1",
        "rear_car_bodies_sanity",
        "san",
    ): SanitySource(id="constant_darkness.rear_bodies"),
    ("constant-darkness-box-zh-coc7", "3.0.1", "rear_maw_sanity", "san"): SanitySource(
        id="constant_darkness.rear_maw"
    ),
}


def resolve_source(
    content: ModuleContentV3, check: RuleCheckSpec, rule_id: str, step_id: str
) -> SanitySource | None:
    source_id = check.parameters.get("sanity_source")
    declared = {source.id: source for source in content.sanity_sources}
    if len(declared) != len(content.sanity_sources):
        raise ContractError("SANITY_SOURCE_DUPLICATE")
    if source_id is not None:
        if not isinstance(source_id, str) or source_id not in declared:
            raise ContractError("SANITY_SOURCE_UNKNOWN")
        source = declared[source_id]
    else:
        source = LEGACY_SOURCES.get(
            (content.module_id, content.version, rule_id, step_id)
        )
    cap = check.parameters.get("habit_cap")
    if cap is not None:
        if type(cap) is not int or not 0 <= cap <= 100000:
            raise ContractError("SANITY_CAP_INVALID")
        if source is None:
            raise ContractError("SANITY_SOURCE_REQUIRED")
        if source.habit_cap != cap:
            raise ContractError("SANITY_CAP_CONFLICT")
    return source
