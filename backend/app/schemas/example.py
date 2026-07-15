from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExampleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ExampleUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ExampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
