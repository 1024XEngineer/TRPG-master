"""角色（调查员）建卡（issue #59）的 pydantic 请求/响应模型。

建卡流程分两段：POST 创建草稿 → PATCH 保存完整数据 → POST complete 标记完成，
跟 trpg-app 原型（character-api.ts）的四步向导一一对应：信息/属性/技能三步
在前端本地完成，第四步"完成"时把整份角色数据一次性 PATCH 上来。属性/衍生值/
技能的具体数值仍由客户端整体提交、后端负责校验形状、持久化，以及把
RoomPlayer.has_character 标记为 True；但 issue #84 S2 起，`complete_character`
落库前会用 `app/core/coc7_rules.py` 权威重算并校验一遍（职业/兴趣技能点预算、
技能上限、信用评级区间等），不合法直接拒绝——不再只信任客户端算好的数值。
建卡过程中的实时预览走本文件下方的 `CharacterPreviewRequest`/
`CharacterComputeResult`（`POST /systems/{systemId}/character/preview`）。
"""

from pydantic import Field

from app.dto.common import CamelModel, UtcDatetime


class EquipmentItem(CamelModel):
    name: str = Field(..., min_length=1, max_length=200)


class CharacterUpdateBody(CamelModel):
    """PATCH /api/v1/rooms/{roomId}/characters/{characterId} 请求体"""

    name: str = Field(..., min_length=1, max_length=100)
    age: int | None = None
    gender: str | None = Field(default=None, max_length=20)
    residence: str = Field(default="", max_length=100)
    birthplace: str = Field(default="", max_length=100)
    attributes: dict[str, int]
    derived_stats: dict[str, int]
    skills: dict[str, int]
    equipment: list[EquipmentItem] = Field(default_factory=list)
    occupation: str | None = None
    background: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=4000)


class CharacterRead(CamelModel):
    """GET /api/v1/rooms/{roomId}/characters/{characterId} 返回（issue #96）。

    补这个端点是为了让**后端成为角色卡的唯一事实来源**。此前只有
    创建/保存/完成/掷属性四个写操作、没有任何读接口，前端因此只能把角色卡
    存进 localStorage 当权威源——而那份副本的结构会随后端 schema 演进而过期
    （PR #88 加幸运后，旧的 8 键角色卡就再也编辑不了了）。

    `generation_method` 一并返回：客户端要据此知道这张卡该按点数购买法还是
    掷骰法来渲染与校验。
    """

    id: str
    status: str
    generation_method: str
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    residence: str = ""
    birthplace: str = ""
    attributes: dict[str, int] = Field(default_factory=dict)
    derived_stats: dict[str, int | str] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    equipment: list[str] = Field(default_factory=list)
    occupation: str | None = None
    background: str = ""
    notes: str = ""


class CharacterCreateBody(CamelModel):
    """POST /api/v1/rooms/{roomId}/characters 请求体（issue #77 新增第三条建卡路径）。

    整个请求体本身仍然可选（不传等价于从零建卡，路由层用 `Body(default=None)`
    兜底），`based_on_template_id` 指向 `user_character_templates` 表——本期
    只接住这个参数、校验它的形状，真正"复制模板数据进草稿"的读写没有实现
    （issue 决策 5：本期只铺表与接口），带了这个字段会直接收到 NOT_IMPLEMENTED。
    """

    based_on_template_id: str | None = Field(default=None, min_length=1)


class CharacterDraftResult(CamelModel):
    """POST /api/v1/rooms/{roomId}/characters 返回"""

    character_id: str
    status: str


class RollAttributesResult(CamelModel):
    """POST /api/v1/rooms/{roomId}/characters/{characterId}/roll-attributes 返回。

    服务端权威掷骰（COC7 标准法）：STR/CON/DEX/APP/POW = 3d6*5，
    SIZ/INT/EDU = (2d6+6)*5；衍生值按标准公式算出 HP/MP/SAN，写回
    `characters.attributes`/`derived_stats` 后原样返回给客户端展示。
    """

    attributes: dict[str, int]
    derived_stats: dict[str, int]


class CharacterTemplateCreateBody(CamelModel):
    """POST /api/v1/me/character-templates 请求体（issue 决策 5，本期不实现）。"""

    name: str = Field(..., min_length=1, max_length=200)
    system_id: str = Field(..., min_length=1)
    data: dict = Field(default_factory=dict)


class CharacterTemplateRead(CamelModel):
    """`我的常用角色卡` 列表/详情返回项（issue 决策 5，本期不实现）。"""

    template_id: str
    name: str
    system_id: str
    data: dict
    created_at: UtcDatetime
    updated_at: UtcDatetime


# ── 建卡计算/校验预览（issue #84 S2，路线乙的接缝） ────────────────────────
#
# 前端建卡过程中把当前草稿（属性/职业/技能分配）发给
# `POST /api/v1/systems/{systemId}/character/preview`，后端用
# `app/core/coc7_rules.py` 权威算出全部派生量 + 校验报告，前端只负责渲染，
# 不再本地重算 COC7 规则数值——`complete_character` 最终落库前也是复用同一套
# 计算/校验，两处结果不会不一致。


class CharacterPreviewRequest(CamelModel):
    """POST /api/v1/systems/{systemId}/character/preview 请求体。"""

    attributes: dict[str, int]
    occupation_id: int | None = None
    skills: dict[str, int] = Field(default_factory=dict)


class SkillPointsBudgetView(CamelModel):
    """一个技能点池（职业/兴趣）的预算/已用/剩余。"""

    budget: int
    spent: int
    remaining: int


class SkillComputeView(CamelModel):
    """一项技能的计算结果：基础值/已分配点数/当前值/上限。"""

    id: str
    base: int
    allocated: int
    current: int
    cap: int


class ValidationIssueView(CamelModel):
    """一条结构化校验失败信息，空列表代表这张卡合法。"""

    code: str
    field: str
    message: str


class CharacterComputeResult(CamelModel):
    """`compute_preview` 的响应结构：衍生值 + 两个技能点预算 + 全部技能的
    base/cap/当前值 + 校验报告。"""

    derived_stats: dict[str, int | str]
    occupation_skill_points: SkillPointsBudgetView
    interest_skill_points: SkillPointsBudgetView
    skill_view: list[SkillComputeView]
    validation: list[ValidationIssueView]
