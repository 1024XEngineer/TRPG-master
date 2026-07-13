"""REST 层共用的响应/请求基类 —— 统一用 camelCase 对齐 API接口对齐规范.md 的
JSON 记法（后端内部字段名仍是 snake_case，Pydantic alias 做转换）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
