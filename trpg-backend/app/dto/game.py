"""游戏大类 / 规则系统模块的 pydantic 请求/响应模型（issue #77 §2 新增端点）。

`GET /games`、`GET /games/{gameId}/systems`、`GET /systems/{systemId}/ruleset`
三个都是只读目录接口，本期由真实数据库支撑（`Game`/`GameSystem` 表已建好，
建房时选模组间接引用它们），不是固定假数据——但 `ruleset` 的具体内容（属性/
技能/职业目录）本期没有真实的规则数据管理界面，写死一份 COC7 的最小示例。
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


class RulesetRead(CamelModel):
    """建卡所需的规则数据：属性/技能/职业目录（`GET /systems/{systemId}/ruleset`）。"""

    attributes: list[str]
    skills: list[str]
    occupations: list[str]
