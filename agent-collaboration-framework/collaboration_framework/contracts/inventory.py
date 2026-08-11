"""Room inventory contracts frozen by ModuleContent v3 issue #212 section 9."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import ContractModel


InventoryImportReason = Literal[
    "anachronistic",
    "profession_mismatch",
    "wealth_exceeded",
    "restricted_by_setting",
    "reserved_canon_identity",
    "invalid_quantity",
    "unsupported_item",
]


class ItemClaim(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    raw_name: str = Field(min_length=1, max_length=200)
    declared_quantity: int = Field(default=1, ge=0, le=999)
    declared_properties: tuple[str, ...] = ()
    source: Literal["character_sheet"] = "character_sheet"


class ItemTargetSelector(ContractModel):
    entity_ids: tuple[str, ...] = ()
    location_ids: tuple[str, ...] = ()


class ItemCapability(ContractModel):
    id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    target_selector: ItemTargetSelector = Field(default_factory=ItemTargetSelector)
    consumes: bool = False


class ItemComponent(ContractModel):
    portable: bool = True
    unique: bool = False
    quantity: int = Field(default=1, ge=1, le=999)
    capabilities: tuple[ItemCapability, ...] = ()


class ItemDisplay(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ItemDefinition(ContractModel):
    definition_id: str = Field(min_length=1, max_length=100)
    display: ItemDisplay
    item_component: ItemComponent


class InventoryImportEntry(ContractModel):
    claim_id: str = Field(min_length=1)
    decision: Literal["accepted", "normalized", "rejected"]
    reason_code: InventoryImportReason | None = None
    normalized_definition: ItemDefinition | None = None
    narrative_policy: Literal["brought", "adjusted", "not_brought"]

    @model_validator(mode="after")
    def validate_decision(self) -> InventoryImportEntry:
        if self.decision == "accepted":
            if self.reason_code is not None or self.normalized_definition is None:
                raise ValueError("accepted 导入项必须有定义且不能有拒绝原因")
        elif self.decision == "normalized":
            if self.reason_code is None or self.normalized_definition is None:
                raise ValueError("normalized 导入项必须有定义和调整原因")
        elif self.reason_code is None or self.normalized_definition is not None:
            raise ValueError("rejected 导入项必须只有安全原因")
        return self


class InventoryImportDraft(ContractModel):
    draft_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    character_revision: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    entries: tuple[InventoryImportEntry, ...]
    confirmed: bool = False


class CreateInventoryImportDraftRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    character_revision: str = Field(min_length=1)
    claims: tuple[ItemClaim, ...]


class ConfirmInventoryImportDraftRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    draft_version: int = Field(ge=1)


class ItemCustody(ContractModel):
    kind: Literal["actor_inventory", "location", "entity", "retired"]
    ref_id: str = Field(min_length=1)
    form: Literal["carried", "loose", "placed", "thrown", "contained"]


class ItemState(ContractModel):
    condition: str = Field(default="intact", min_length=1, max_length=100)
    status: Literal["active", "retired"] = "active"
    values: dict[str, JsonValue] = Field(default_factory=dict)


class ItemAcquisition(ContractModel):
    source_type: Literal["character_import", "location", "entity", "runtime"]
    source_id: str = Field(min_length=1)
    player_safe_label: str = Field(min_length=1, max_length=300)
    event_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class ItemInstance(ContractModel):
    id: str = Field(min_length=1, max_length=100)
    room_id: str = Field(min_length=1)
    kind: Literal["item"] = "item"
    origin: Literal["canon", "runtime"]
    definition_id: str = Field(min_length=1, max_length=100)
    display: ItemDisplay
    item_component: ItemComponent
    custody: ItemCustody
    state: ItemState = Field(default_factory=ItemState)
    acquisition: ItemAcquisition | None = None
    keeper_notes: str = ""
    hidden_information_refs: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)
    created_event_id: str = Field(min_length=1)
    last_event_id: str = Field(min_length=1)
    updated_revision: str = Field(min_length=1)


class ItemKnowledge(ContractModel):
    item_id: str = Field(min_length=1)
    scope: Literal["party", "actor"] = "party"
    identity: Literal["unknown", "recognized", "known"] = "unknown"
    known_capability_ids: tuple[str, ...] = ()
    known_information_ids: tuple[str, ...] = ()


class InventoryItemView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_label: str = ""
    quantity: int = Field(ge=1)
    condition: str = Field(min_length=1)
    version: int = Field(ge=1)


class InventoryView(ContractModel):
    inventory: tuple[InventoryItemView, ...] = ()
    loose_items: tuple[InventoryItemView, ...] = ()


class ChangeItemCustodyRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    reason: Literal["pickup", "drop", "throw", "place", "transfer"]
    to_custody: ItemCustody


class ChangeItemCustodyResult(ContractModel):
    request_id: str = Field(min_length=1)
    item: ItemInstance
    revision: str = Field(min_length=1)
    event_id: str = Field(min_length=1)


class ConfirmInventoryImportResult(ContractModel):
    request_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    created_item_ids: tuple[str, ...]
    revision: str = Field(min_length=1)


__all__ = [
    "ChangeItemCustodyRequest",
    "ChangeItemCustodyResult",
    "ConfirmInventoryImportDraftRequest",
    "ConfirmInventoryImportResult",
    "CreateInventoryImportDraftRequest",
    "InventoryImportDraft",
    "InventoryImportEntry",
    "InventoryImportReason",
    "InventoryItemView",
    "InventoryView",
    "ItemAcquisition",
    "ItemCapability",
    "ItemClaim",
    "ItemComponent",
    "ItemCustody",
    "ItemDefinition",
    "ItemDisplay",
    "ItemInstance",
    "ItemKnowledge",
    "ItemState",
    "ItemTargetSelector",
]
