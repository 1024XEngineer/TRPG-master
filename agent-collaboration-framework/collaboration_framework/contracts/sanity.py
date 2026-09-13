"""Private, persisted CoC7 loss accounting. Public views expose resources only."""

from __future__ import annotations

from typing import Literal
from datetime import date
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
    window_id: str | None = None


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
    window: SanityWindow | None = None
    previous_windows: tuple[SanityWindow, ...] = ()
    treatment: SanityTreatment | None = None
    treatment_history: tuple[SanityTreatment, ...] = ()


class SanityPolicy(ContractModel):
    # Summary mode is an authored Keeper choice. Auto only summarizes solo play.
    bout_mode: Literal["auto", "summary", "rounds"] = "auto"
    window_boundary: Literal["keeper_rest", "world_day"] = "keeper_rest"
    calendar_anchor: date | None = None


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


class SanityWindow(ContractModel):
    id: str
    day_index: int = Field(ge=0)
    start_absolute_hour: int = Field(ge=0)
    start_sequence: int = Field(ge=0)
    baseline_san: int = Field(ge=0)
    loss_total: int = Field(default=0, ge=0)
    consumed_outcomes: tuple[str, ...] = ()
    triggered_by: str | None = None
    coverage: Literal["period_start", "upgrade_cutover"] = "period_start"


class SanityTreatment(ContractModel):
    treatment_id: str
    kind: Literal["private", "institution"]
    status: Literal["active", "interrupted", "recovered"] = "active"
    started_absolute_hour: int = Field(ge=0)
    next_review_month: int = Field(default=1, ge=1)
    due_absolute_hour: int = Field(ge=0)
    # Read older snapshots; new courses only persist the calendar deadline.
    task_id: str | None = None
    review_due_notified: bool = False
    stage: Literal["treatment", "sanity_recheck"] = "treatment"
    reviews: tuple[str, ...] = ()
    interruption_outcome_id: str | None = None


SanityLedger.model_rebuild()
