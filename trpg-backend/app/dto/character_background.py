"""一键建卡时用于生成 COC7 调查员背景的结构化模型。"""

from pydantic import Field, field_validator

from app.dto.common import CamelModel


class CharacterBackgroundSkill(CamelModel):
    id: str
    name: str
    value: int


class CharacterBackgroundContext(CamelModel):
    """仅包含生成背景所需的玩家可见人物信息。"""

    name: str = Field(..., min_length=1, max_length=100)
    age: int | None = None
    gender: str | None = Field(default=None, max_length=20)
    residence: str = Field(default="", max_length=100)
    birthplace: str = Field(default="", max_length=100)
    occupation: str = Field(..., min_length=1, max_length=100)
    occupation_description: str = Field(default="", max_length=1000)
    occupation_categories: list[str] = Field(default_factory=list, max_length=20)
    attributes: dict[str, int] = Field(default_factory=dict)
    prominent_skills: list[CharacterBackgroundSkill] = Field(default_factory=list, max_length=5)
    credit_rating: int = Field(..., ge=0, le=99)
    equipment: list[str] = Field(default_factory=list, max_length=20)


class CharacterBackgroundDraft(CamelModel):
    """与前端装备栏和背景表单对应的模型输出；各项背景允许留空。"""

    equipment: list[str] = Field(default_factory=list, max_length=12)
    personal_description: str = Field(default="", max_length=400)
    ideology_beliefs: str = Field(default="", max_length=400)
    significant_people: str = Field(default="", max_length=400)
    meaningful_locations: str = Field(default="", max_length=400)
    treasured_possessions: str = Field(default="", max_length=400)
    traits: str = Field(default="", max_length=400)
    injuries_scars: str = Field(default="", max_length=400)
    phobias_manias: str = Field(default="", max_length=400)
    other: str = Field(default="", max_length=400)

    @field_validator("equipment")
    @classmethod
    def clean_equipment(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if item and item not in seen:
                cleaned.append(item)
                seen.add(item)
        return cleaned

    def to_character_background(self) -> str:
        sections = (
            ("形象描述", self.personal_description),
            ("思想与信念", self.ideology_beliefs),
            ("重要之人", self.significant_people),
            ("意义非凡之地", self.meaningful_locations),
            ("宝贵之物", self.treasured_possessions),
            ("特质", self.traits),
            ("伤口和疤痕", self.injuries_scars),
            ("恐惧症和躁狂症", self.phobias_manias),
            ("其他", self.other),
        )
        return "\n".join(f"{label}：{value.strip()}" for label, value in sections if value.strip())


__all__ = [
    "CharacterBackgroundContext",
    "CharacterBackgroundDraft",
    "CharacterBackgroundSkill",
]
