"""Player knowledge and deterministic travel contracts for ModuleContent v3."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from .common import ContractModel


class LocationKnowledge(ContractModel):
    """What one audience knows about a location, independently of graph reachability."""

    location_id: str = Field(min_length=1)
    scope: Literal["party", "actor"] = "party"
    existence: Literal["unknown", "rumored", "known"] = "unknown"
    localization: Literal["unknown", "approximate", "located"] = "unknown"
    access: Literal["unknown", "reachable", "blocked"] = "unknown"
    visited: bool = False
    known_connection_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_connections(self) -> LocationKnowledge:
        if len(self.known_connection_ids) != len(set(self.known_connection_ids)):
            raise ValueError("known_connection_ids 必须唯一")
        if self.existence == "unknown" and (
            self.localization != "unknown" or self.access != "unknown"
        ):
            raise ValueError("未知地点不能声明位置或可达性")
        return self


class AccessBoundary(ContractModel):
    """The first interaction boundary reached by a travel attempt."""

    kind: Literal["access_point"] = "access_point"
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    state: Literal["locked", "blocked", "interaction_required"]


TargetResolutionStatus: TypeAlias = Literal[
    "known_reachable",
    "known_blocked",
    "known_unlocated",
    "hidden_canon_collision",
    "ambient_creatable",
    "unsupported",
]


class TargetResolution(ContractModel):
    """Safe location-target classification returned before travel is committed."""

    status: TargetResolutionStatus
    target_id: str | None = Field(default=None, min_length=1)
    path: tuple[str, ...] = ()
    reached_location_id: str | None = Field(default=None, min_length=1)
    boundary: AccessBoundary | None = None
    safe_reason: str = ""

    @model_validator(mode="after")
    def validate_resolution(self) -> TargetResolution:
        if self.status == "known_reachable" and not self.path:
            raise ValueError("known_reachable 必须提供路线")
        if self.status == "known_blocked" and (
            self.boundary is None or self.reached_location_id is None
        ):
            raise ValueError("known_blocked 必须提供阻挡边界和抵达前沿")
        return self


class TravelResolved(ContractModel):
    type: Literal["TravelResolved"] = "TravelResolved"
    destination_id: str = Field(min_length=1)
    path: tuple[str, ...] = Field(min_length=1)


class TravelInterrupted(ContractModel):
    type: Literal["TravelInterrupted"] = "TravelInterrupted"
    destination_id: str = Field(min_length=1)
    current_location_id: str = Field(min_length=1)
    path: tuple[str, ...] = Field(min_length=1)
    reached_boundary: AccessBoundary


TravelResult: TypeAlias = TravelResolved | TravelInterrupted


__all__ = [
    "AccessBoundary",
    "LocationKnowledge",
    "TargetResolution",
    "TargetResolutionStatus",
    "TravelInterrupted",
    "TravelResolved",
    "TravelResult",
]
