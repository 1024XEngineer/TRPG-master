"""角色（调查员）建卡（issue #59）的 pydantic 请求/响应模型。

建卡流程分两段：POST 创建草稿 → PATCH 保存完整数据 → POST complete 标记完成，
跟 trpg-app 原型（character-api.ts）的四步向导一一对应：信息/属性/技能三步
在前端本地完成，第四步"完成"时把整份角色数据一次性 PATCH 上来。属性/衍生值/
技能的具体数值由客户端算好后整体提交，后端只负责校验形状、持久化、以及把
RoomPlayer.has_character 标记为 True——不在服务端重算 COC7 规则数值（本期
职业/技能规则表也仍由前端本地维护，见 issue #59"本期不做"）。
"""

from datetime import datetime

from pydantic import Field

from app.dto.common import CamelModel


class EquipmentItem(CamelModel):
    name: str = Field(..., min_length=1, max_length=200)


class CharacterUpdateBody(CamelModel):
    """PATCH /api/v1/rooms/{roomId}/characters/{characterId} 请求体"""

    name: str = Field(..., min_length=1, max_length=100)
    attributes: dict[str, int]
    derived_stats: dict[str, int]
    skills: dict[str, int]
    equipment: list[EquipmentItem] = Field(default_factory=list)
    occupation: str | None = None
    background: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=4000)


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
    created_at: datetime
    updated_at: datetime
