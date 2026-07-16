"""全项目统一的响应信封（envelope）。

所有接口，不管成功还是失败，返回的 JSON 顶层结构都长一样：
    { "success": true/false, "data": ..., "error": {"code", "message"} | null }
前端/SDK 只需要写一套解析逻辑（判断 success 再决定读 data 还是 error），
不需要针对每个接口猜它失败时到底返回什么形状。
"""

from typing import Self

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.errors import ErrorCode


def _to_camel(snake: str) -> str:
    return to_camel(snake)


class CamelModel(BaseModel):
    """所有需要 camelCase JSON 层的 DTO 基类：JSON 层使用 camelCase，Python 层
    使用 snake_case。

    原先 dto/room.py、dto/auth.py、dto/character.py 各自都定义了一份一模一样
    的 CamelModel（issue #75 code review 时发现的重复），这里统一成一份供三者
    （以及新增的 dto/ws.py）import，其余各文件里针对个别模型的额外 model_config
    （比如 RoomPlayerRead 的 from_attributes=True）不受影响——pydantic 的
    model_config 在子类里是合并而非整体覆盖父类配置。
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(alias=_to_camel),
        populate_by_name=True,
    )


class ErrorDetail(BaseModel):
    """错误信息的具体内容，只在 success=false 时出现在 error 字段里。"""

    code: ErrorCode
    message: str


class ApiResponse[T](BaseModel):
    """通用响应信封，`T` 是 data 字段的具体类型（用 PEP 695 的类型参数语法）。

    比如 `ApiResponse[RoomPreview]` 表示"data 是一个 RoomPreview"，
    `ApiResponse[list[RoomPreview]]` 表示"data 是一个 RoomPreview 列表"。
    路由函数把这个类型写在 `response_model=` 里，FastAPI 会自动按这个结构
    生成 OpenAPI 文档、并在真正返回前校验数据形状对不对。
    """

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> Self:
        """构造一个成功响应，比如 `ApiResponse.ok(example)`。"""
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, code: ErrorCode, message: str) -> Self:
        """构造一个失败响应。主要给 main.py 里的全局异常处理器调用，
        业务代码通常不需要手动调这个——直接 `raise AppException(...)`，
        异常处理器会自动转成这个格式。
        """
        return cls(success=False, data=None, error=ErrorDetail(code=code, message=message))
