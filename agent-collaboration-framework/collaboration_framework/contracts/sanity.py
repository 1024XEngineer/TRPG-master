"""Private, persisted CoC7 loss accounting. Public views expose resources only."""

from __future__ import annotations

from typing import Literal
from pydantic import Field
from .common import ContractModel


class SanitySource(ContractModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_.:-]*$")
    habit_cap: int | None = Field(default=None, strict=True, ge=0, le=100000)


class SanityLoss(ContractModel):
    outcome_id: str
    event_id: str
    sequence: int = Field(ge=1)
    source_id: str | None = None
    requested: int = Field(ge=0)
    actual: int = Field(ge=0)
    before: int = Field(ge=0)
    after: int = Field(ge=0)
    absolute_hour: int | None = Field(default=None, ge=0)
    module_id: str
    module_version: str


class SanityLedger(ContractModel):
    version: Literal[1] = 1
    losses: tuple[SanityLoss, ...] = ()
    habituation: dict[str, int] = Field(default_factory=dict)
    development_phases: tuple[str, ...] = ()
    safe_rests: tuple[str, ...] = ()
    coverage: Literal["new_room", "canonical_history", "legacy_gap"] = "new_room"
    coverage_start_sequence: int = Field(default=0, ge=0)
    history_gaps: tuple[str, ...] = ()
    bouts: tuple[MadnessBout, ...] = ()


class SanityPolicy(ContractModel):
    # Summary mode is an authored Keeper choice. Auto only summarizes solo play.
    bout_mode: Literal["auto", "summary", "rounds"] = "auto"


class MadnessBout(ContractModel):
    application_key: str
    source_outcome_id: str
    table_id: Literal["coc7.summary.v1"] = "coc7.summary.v1"
    type_id: Literal[
        "amnesia",
        "robbed",
        "battered",
        "violence",
        "ideology",
        "significant_person",
        "institutionalized",
        "flee",
        "phobia",
        "mania",
    ]
    type_roll: int = Field(ge=1, le=10)
    duration_roll: int = Field(ge=1, le=10)
    duration_hours: int = Field(ge=1, le=10)
    started_absolute_hour: int = Field(ge=0)


SanityLedger.model_rebuild()
