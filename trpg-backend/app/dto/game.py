"""游戏大类 / 规则系统模块的 pydantic 请求/响应模型（issue #77 §2 新增端点，
issue #84 S1 把 `ruleset` 从三个字符串数组加厚成结构化的属性/技能/职业规格）。

`GET /games`、`GET /games/{gameId}/systems`、`GET /systems/{systemId}/ruleset`
三个都是只读目录接口，本期由真实数据库支撑（`Game`/`GameSystem` 表已建好，
建房时选模组间接引用它们），不是固定假数据——`ruleset` 的具体内容（属性生成
公式/技能基础值/职业信用评级与技能点公式）由 `app/core/coc7_content.py` 提供
权威数据，seed 时写入 `GameSystem.ruleset`。
"""

from app.dto.common import CamelModel


class GameRead(CamelModel):
    """游戏大类。"""

    model_config = {"from_attributes": True}
    id: str
    name: str
    description: str | None = None


class GameSystemRead(CamelModel):
    """大类下的规则系统。"""

    model_config = {"from_attributes": True}
    id: str
    game_id: str
    name: str
    version: str | None = None


class AttributeSpec(CamelModel):
    """一项基础属性：键名、显示名、COC7 生成公式。"""

    key: str
    label: str
    generation: str


class SkillSpec(CamelModel):
    """一项技能：基础值可以是固定数字，也可以是依赖属性的公式字符串
    （比如闪避 `DEX/2`、母语 `EDU`）。"""

    id: str
    name: str
    name_en: str | None = None
    base: int | str
    category: str
    related_attr: str | None = None


class OccupationSpec(CamelModel):
    """一个职业：信用评级区间、职业技能点公式、职业技能清单。"""

    id: int
    name: str
    credit_min: int
    credit_max: int
    skill_points_formula: str
    skill_ids: list[str]
    description: str


class RulesetRead(CamelModel):
    """建卡所需的规则数据：属性/技能/职业目录（`GET /systems/{systemId}/ruleset`）。"""

    attributes: list[AttributeSpec]
    skills: list[SkillSpec]
    occupations: list[OccupationSpec]
