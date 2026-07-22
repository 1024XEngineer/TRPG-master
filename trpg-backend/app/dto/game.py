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
    """一项基础属性：键名、显示名、COC7 生成公式。

    `point_buy` 表示这一项是否参与点数购买法的分配。COC7 里幸运只能掷
    （`3d6*5`）、不能用属性点买，所以它是 `False`——客户端据此决定哪些属性
    渲染成可加点、哪些只读展示，不需要自己维护一份"哪 8 项能加点"的名单
    （issue #96：这份名单此前在前端硬编码了三处，加幸运时漏改一处导致
    角色卡看不到幸运值）。
    """

    key: str
    label: str
    generation: str
    point_buy: bool = True


class AttributePointBuyRules(CamelModel):
    """点数购买法的约束（issue #96）。

    这些数字此前只存在于前端代码里、后端既不校验也不暴露，导致 ①任何 SDK
    使用者都能提交 UI 永远不允许的角色卡 ②重写前端时必须把规则再实现一遍。
    放进 ruleset 是为了「一份定义、两方消费」：后端拿它裁决，客户端拿它渲染
    「还剩多少点」「这项最多加到多少」。

    只约束 `point_buy=True` 的属性；幸运不在其列。
    """

    budget: int
    min_value: int
    max_value: int
    default_value: int


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


class AgeRangeSpec(CamelModel):
    """调查员年龄的合法区间（issue #96）。

    COC7 的年龄档从 15-19 起、到 80-89 止，所以合法区间是 [15, 89]。此前前端
    的输入框写死成 [10, 100]，两头都不符合规则。

    注意本期只做区间约束，**不做年龄修正**（15-19 岁扣 STR/SIZ/EDU 各若干、
    20-39 岁一次教育增强检定、40 岁起每十年 MOV -1 等）——那是一整套生成期
    规则，要单独做。
    """

    min_value: int
    max_value: int


class RulesetRead(CamelModel):
    """建卡所需的规则数据：属性/技能/职业目录（`GET /systems/{systemId}/ruleset`）。"""

    attributes: list[AttributeSpec]
    # 可空：还没配置规则数据的自定义系统没有点数购买约束可言。这里返回 None
    # 而不是编一组 0/0/0——那种"看起来正常但内容不对"的数据会让客户端渲染出
    # 「0/0 点」这类无意义的界面（同 `get_ruleset` 里空目录兜底的取舍）。
    attribute_point_buy: AttributePointBuyRules | None = None
    age_range: AgeRangeSpec | None = None
    skills: list[SkillSpec]
    occupations: list[OccupationSpec]
