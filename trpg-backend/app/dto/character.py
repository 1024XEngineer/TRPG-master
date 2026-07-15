"""角色（调查员）建卡（issue #59）的 pydantic 请求/响应模型。

建卡流程分两段：POST 创建草稿 → PATCH 保存完整数据 → POST complete 标记完成，
跟 trpg-app 原型（character-api.ts）的四步向导一一对应：信息/属性/技能三步
在前端本地完成，第四步"完成"时把整份角色数据一次性 PATCH 上来。属性/衍生值/
技能的具体数值由客户端算好后整体提交，后端只负责校验形状、持久化、以及把
RoomPlayer.has_character 标记为 True——不在服务端重算 COC7 规则数值（本期
职业/技能规则表也仍由前端本地维护，见 issue #59"本期不做"）。
"""

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _to_camel(snake: str) -> str:
    return to_camel(snake)


class CamelModel(BaseModel):
    """JSON 层 camelCase，Python 层 snake_case，跟 dto/room.py 的约定保持一致。"""

    model_config = ConfigDict(
        alias_generator=AliasGenerator(alias=_to_camel),
        populate_by_name=True,
    )


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


class CharacterDraftResult(CamelModel):
    """POST /api/v1/rooms/{roomId}/characters 返回"""

    character_id: str
    status: str
