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

import json
from typing import Literal

from pydantic import Field, field_validator

from app.dto.common import CamelModel, UtcDatetime


class QuickGenerateRequest(CamelModel):
    """可选的玩家身份信息；旧客户端不传时仍使用确定性默认资料。"""

    name: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=15, le=89)
    gender: str | None = Field(default=None, max_length=20)
    residence: str = Field(default="", max_length=100)
    birthplace: str = Field(default="", max_length=100)


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
    occupation_choice_skill_ids: list[str] | None = None
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
    occupation_choice_skill_ids: list[str] | None = None
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


# 卡库卡的 `data` 是 JSON 列，写入方是客户端。不设上限的话一次 PATCH 就能往
# 单行里塞进任意大小的内容（实测 2MB 直接 201）。建卡态数据满打满算也就几 KB。
CHARACTER_TEMPLATE_DATA_MAX_BYTES = 64 * 1024


def _validate_template_data(value: dict) -> dict:
    encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(encoded) > CHARACTER_TEMPLATE_DATA_MAX_BYTES:
        raise ValueError(f"角色卡数据过大（上限 {CHARACTER_TEMPLATE_DATA_MAX_BYTES} 字节）")
    return value


class CharacterTemplateCreateBody(CamelModel):
    """POST /api/v1/me/character-templates 请求体。

    `data.generation_method` 由服务端决定，这里传什么都会被覆盖成点数购买法：
    「属性是掷出来的」是一条**服务端背书**，只有服务端自己掷的那一次才能给出
    （见 `POST /me/character-templates/{id}/roll-attributes`）。让客户端自己声明
    的话，它只要写上 roll 就能跳过 `complete` 的点数预算校验，8 项全 90 也能过。
    """

    name: str = Field(..., min_length=1, max_length=200)
    system_id: str = Field(..., min_length=1)
    data: dict = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def check_data_size(cls, value: dict) -> dict:
        return _validate_template_data(value)


class CharacterTemplateUpdateBody(CamelModel):
    """PATCH /api/v1/me/character-templates/{templateId} 请求体（#337）。

    卡库现在也是建卡的宿主，建卡向导的每一次保存都落到这里，所以要能只改名、
    只改数据、或两个都改——两个字段都可选，`None` 表示这一次不动它。

    `data` 命中时是**整体覆盖**而不是合并：合并语义下前端删掉一项技能永远删不掉。

    `data.generation_method` 同样不由客户端决定：只有「这次 PATCH 没有改动属性」
    时服务端背书的 roll 才会保留，其余一律退回点数购买法。这跟房间版
    `update_character` 对 `roll` 的处理是同一道闸。
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    data: dict | None = None

    @field_validator("data")
    @classmethod
    def check_data_size(cls, value: dict | None) -> dict | None:
        return None if value is None else _validate_template_data(value)


class CharacterTemplateRead(CamelModel):
    """`我的常用角色卡` 列表/详情返回项。"""

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
    occupation_choice_skill_ids: list[str] | None = None
    generation_method: Literal["pointbuy", "roll"] = "pointbuy"


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
    resolved_occupation_choice_skill_ids: list[str] = Field(default_factory=list)
    validation: list[ValidationIssueView]


class QuickGenerateResult(CamelModel):
    """一键生成后返回的房间角色草稿和权威计算结果。"""

    character: CharacterRead
    occupation_id: int
    compute: CharacterComputeResult


class SystemQuickGenerateResult(CamelModel):
    """POST /api/v1/systems/{systemId}/character/quick-generate 返回（#337）。

    不依赖房间的一键生成。跟房间版 `QuickGenerateResult` 的区别是它**不落库**：
    没有 `characterId`，也没有 `status`，只把生成结果交回客户端，由客户端决定
    存进哪张卡库卡（`PATCH /me/character-templates/{id}`）。

    `data` 与 `CharacterTemplateRead.data` 同形，可以原样 PATCH 回去，中间不用
    再拼一次字段。
    """

    data: dict
    occupation_id: int | None = None
    compute: CharacterComputeResult | None = None
