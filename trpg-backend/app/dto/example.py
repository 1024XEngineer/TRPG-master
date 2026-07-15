"""Example 的 pydantic 请求/响应模型。

跟 models/example.py 的 SQLAlchemy ORM 模型是两回事：ORM 模型描述"数据库里
这张表长什么样"，这里的 pydantic 模型描述"HTTP 接口的请求体/响应体长什么样"——
两者字段大部分重叠，但职责不同（比如 id/created_at/updated_at 是服务端生成的，
不应该出现在"新建"请求体里；ORM 模型上有的字段也不一定都要暴露给外部）。
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# strip_whitespace=True：校验前先去掉首尾空白，再判断 min_length——单纯
# Field(min_length=1) 挡得住空字符串，挡不住一个或多个空格拼成的"看起来是空"
# 的名称（前端有 .trim() 判断，但那只是客户端行为，直接绕过前端调接口就能
# 建一条名称全是空格的记录）。这里在 DTO 层统一兜底，而不是依赖调用方守规矩。
NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ExampleCreate(BaseModel):
    """POST /api/v1/examples 的请求体。

    Field(...)/StringConstraints(...) 这些约束由 pydantic 在进入路由函数之前
    自动校验，校验不过会被 FastAPI 转成 422，再经 main.py 里的
    RequestValidationError 处理器包装成统一响应体——业务代码里完全不用手写
    "名称不能为空"这种判断。
    """

    name: NameStr
    description: str | None = Field(default=None, max_length=2000)


class ExampleUpdate(BaseModel):
    """PUT /api/v1/examples/{id} 的请求体，字段跟 Create 一样（全量更新）。"""

    name: NameStr
    description: str | None = Field(default=None, max_length=2000)


class ExampleRead(BaseModel):
    """对外返回时的形状，会被包在 ApiResponse[ExampleRead] 里。"""

    # from_attributes=True：允许直接从 ORM 对象（models.Example 实例）构造，
    # 也就是 controller/v1/examples.py 里那句 `ExampleRead.model_validate(example)`——
    # 不用手动把 ORM 对象的每个字段一个个搬到 dict 里再构造。
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
