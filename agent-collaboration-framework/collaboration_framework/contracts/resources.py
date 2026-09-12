"""Closed quantities and current-actor resource effects (#484)."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel

ResourceId = Literal["hp", "san", "mp", "luck", "mythos"]


class FixedQuantity(ContractModel):
    kind: Literal["fixed"] = "fixed"
    value: int = Field(ge=0, le=100000, strict=True)


class DiceQuantity(ContractModel):
    kind: Literal["dice"] = "dice"
    count: int = Field(ge=1, le=100, strict=True)
    sides: int = Field(ge=2, le=1000, strict=True)
    bonus: int = Field(default=0, ge=-100, le=100000, strict=True)

    @model_validator(mode="after")
    def nonnegative_quantity(self):
        if self.count + self.bonus < 0:
            raise ValueError("quantity must be nonnegative for every roll")
        return self


ResourceQuantity = Annotated[FixedQuantity | DiceQuantity, Field(discriminator="kind")]


class ChangeActorResourceEffect(ContractModel):
    type: Literal["change_actor_resource"] = "change_actor_resource"
    resource_id: ResourceId
    direction: Literal["increase", "decrease"]
    quantity: ResourceQuantity
    reason_code: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
