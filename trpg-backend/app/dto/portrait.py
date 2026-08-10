"""Character portrait generation request, snapshot, and response models."""

from typing import Literal

from pydantic import Field, field_validator

from app.dto.common import CamelModel


class PortraitGenerationRequest(CamelModel):
    style: Literal["realistic"] = "realistic"
    size: Literal["1024x1024"] = "1024x1024"


class PortraitSkillSnapshot(CamelModel):
    id: str
    name: str
    value: int
    allocated: int


class CharacterPortraitSnapshot(CamelModel):
    character_id: str
    name: str
    age: int | None = None
    gender: str | None = None
    residence: str = ""
    birthplace: str = ""
    occupation: str | None = None
    occupation_description: str = ""
    occupation_categories: list[str] = Field(default_factory=list)
    attributes: dict[str, int] = Field(default_factory=dict)
    visual_traits: list[str] = Field(default_factory=list)
    prominent_skills: list[PortraitSkillSnapshot] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    background: str = ""
    module_background: str = ""


class PortraitPromptDraft(CamelModel):
    positive_prompt: str = Field(
        ...,
        min_length=1,
        max_length=3000,
        pattern=r"[\u4e00-\u9fff]",
        description="简体中文正向生图提示词",
    )
    negative_prompt: str = Field(
        ...,
        min_length=1,
        max_length=1500,
        pattern=r"[\u4e00-\u9fff]",
        description="简体中文反向生图提示词",
    )
    prompt_summary: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        pattern=r"[\u4e00-\u9fff]",
        description="简体中文生成依据摘要",
    )

    @field_validator("positive_prompt", "negative_prompt", "prompt_summary")
    @classmethod
    def require_primarily_chinese(cls, value: str) -> str:
        chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in value)
        latin_count = sum(char.isascii() and char.isalpha() for char in value)
        if chinese_count <= latin_count:
            raise ValueError("人物生图提示词必须以中文为主")
        return value


class PortraitPrompt(PortraitPromptDraft):
    source: Literal["deepseek", "deterministic", "deterministic_fallback"]


class PortraitGenerationResult(CamelModel):
    generation_id: str
    status: Literal["completed"] = "completed"
    image_url: str
    portrait_version: str
    prompt: str
    negative_prompt: str
    prompt_summary: str
    prompt_source: Literal["deepseek", "deterministic", "deterministic_fallback"]
