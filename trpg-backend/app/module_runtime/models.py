"""ModulePackage 1.1.0 的运行时 Pydantic 契约。

这里只为运行时真正依赖的字段建立强类型，其余解析产物仍通过 ``extra=allow``
完整保留在 revision JSON 中。这样 Loader 可以严格检查关键边界，又不会在模组
解析协议增加非运行时字段时迫使游戏服务同步发布。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PackageModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SourceRights(PackageModel):
    declaration_status: str
    commercial_use: str
    redistribution: str
    notes: str | None = None

    @property
    def cleared_for_distribution(self) -> bool:
        return self.declaration_status == "cleared" and self.redistribution == "cleared"


class SourceManifest(PackageModel):
    filename: str
    runtime_included: bool = False
    rights: SourceRights


class RulesetRef(PackageModel):
    system_id: str
    version: str
    required_capabilities: list[str] = Field(default_factory=list)
    required_condition_types: list[str] = Field(default_factory=list)
    required_effect_types: list[str] = Field(default_factory=list)


class PlayerCount(PackageModel):
    investigators_min: int = Field(ge=1)
    investigators_max: int = Field(ge=1)
    keeper_count: int = Field(default=1, ge=1)


class CharacterSetup(PackageModel):
    creation_mode: Literal["custom", "pregen", "custom_or_pregen"]
    requirements: list[str] = Field(default_factory=list)
    recommended_skills: list[str] = Field(default_factory=list)
    pregenerated_character_ids: list[str] = Field(default_factory=list)


class ModuleInfo(PackageModel):
    module_id: str
    title: str
    original_title: str | None = None
    ruleset_ref: RulesetRef
    player_count: PlayerCount
    estimated_duration: str | None = None
    character_setup: CharacterSetup
    content_advisories: list[str] = Field(default_factory=list)
    premise: str
    entry_scene_id: str


class KeeperBrief(PackageModel):
    core_truth: str
    experience_goal: str
    tone: list[str] = Field(default_factory=list)
    must_preserve: list[str] = Field(default_factory=list)
    must_not_reveal_before_granted: list[str] = Field(default_factory=list)


class RuntimeDefaults(PackageModel):
    clue_visibility: str = "locked_until_granted"
    missing_checkpoint_outcome: str = "no_effect"
    unknown_action_policy: str = "adjudicate_without_state_change"
    trigger_once: bool = True
    trigger_priority: int = 100


class ModuleContent(PackageModel):
    facts: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    locations: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    clues: list[dict[str, Any]]
    checkpoints: list[dict[str, Any]]
    sanity_events: list[dict[str, Any]]
    timelines: list[dict[str, Any]]
    tracks: list[dict[str, Any]]
    encounters: list[dict[str, Any]]
    puzzles: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    triggers: list[dict[str, Any]]
    endings: list[dict[str, Any]]


class ClockState(PackageModel):
    day: int = 0
    time_of_day: str = "day"


class InitialState(PackageModel):
    current_scene_id: str
    discovered_scene_ids: list[str] = Field(default_factory=list)
    granted_clue_ids: list[str] = Field(default_factory=list)
    completed_checkpoint_ids: list[str] = Field(default_factory=list)
    fired_trigger_ids: list[str] = Field(default_factory=list)
    active_timeline_ids: list[str] = Field(default_factory=list)
    track_states: dict[str, Any] = Field(default_factory=dict)
    inventory_resource_ids: list[str] = Field(default_factory=list)
    active_encounter_id: str | None = None
    active_ending_id: str | None = None
    clock: ClockState = Field(default_factory=ClockState)
    variables: dict[str, Any] = Field(default_factory=dict)


class ValidationBlock(PackageModel):
    status: str
    errors: list[Any] = Field(default_factory=list)


class ModulePackage(PackageModel):
    package_schema_version: Literal["1.1.0"]
    package_id: str
    package_status: Literal["ready"]
    source_manifest: SourceManifest
    module: ModuleInfo
    keeper_brief: KeeperBrief
    runtime_defaults: RuntimeDefaults
    content: ModuleContent
    initial_state: InitialState
    assets: list[dict[str, Any]]
    normalization_decisions: list[dict[str, Any]]
    validation: ValidationBlock
