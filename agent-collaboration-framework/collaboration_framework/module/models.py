"""Parser-internal intermediate representations.

These models are owned by Member C and must not be imported by Runtime or
shared contract modules. They become shared data only after deterministic
validation constructs ``contracts.ModuleContent``.
"""

from __future__ import annotations

from pydantic import Field

from collaboration_framework.contracts import (
    CheckpointSpec,
    ContractModel,
    EntitySpec,
    SceneSpec,
    WinConditionSpec,
)


class ModuleDraft(ContractModel):
    """Strict Parser IR produced before semantic validation.

    Phase 2 Parser work will produce this type rather than ModuleContent. The
    only supported conversion to ModuleContent is the validation boundary.
    """

    module_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    world_ref: str = Field(min_length=1)
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
