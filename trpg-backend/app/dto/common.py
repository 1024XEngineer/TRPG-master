"""全项目统一的响应信封（envelope）。

所有接口，不管成功还是失败，返回的 JSON 顶层结构都长一样：
    { "success": true/false, "data": ..., "error": {"code", "message"} | null }
前端/SDK 只需要写一套解析逻辑（判断 success 再决定读 data 还是 error），
不需要针对每个接口猜它失败时到底返回什么形状。
"""

from datetime import UTC, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.errors import ErrorCode


def _to_camel(snake: str) -> str:
    return to_camel(snake)


def _assume_utc(value: datetime) -> datetime:
    """给不带时区的时间补上 UTC。

    数据库里所有时间列都是 `DateTime(timezone=True)`、写入的也都是
    `datetime.now(UTC)`，**但 SQLite 不保存时区信息**，读出来是个 naive
    datetime，pydantic 于是序列化成 `2026-07-21T09:35:13.095627`——没有任何
    后缀。客户端拿到这种字符串，按 ECMAScript 的规则会当作**本地时间**解析，
    于是"4 分钟前"在 UTC+8 的机器上显示成"8 小时前"，偏差正好是时区偏移量。

    这不是客户端该自己猜的事：光看字符串无从判断它是 UTC 还是本地时间。所以
    在契约层补齐——所有对外暴露的时间一律带时区后缀。
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


UtcDatetime = Annotated[datetime, AfterValidator(_assume_utc)]
"""对外暴露时间字段统一用这个类型，别直接用 `datetime`。"""


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
    """错误信息的具体内容，只在 success=false 时出现在 error 字段里。

    `details` 是 issue #84 S2 新增的可选字段：装结构化的校验报告（比如建卡
    校验失败时的一条条 {code, field, message}），大多数错误不需要它，默认
    None，不影响原有只有 code/message 的错误响应形状。
    """

    code: ErrorCode
    message: str
    details: list[dict[str, str]] | None = None


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
    def fail(
        cls, code: ErrorCode, message: str, details: list[dict[str, str]] | None = None
    ) -> Self:
        """构造一个失败响应。主要给 main.py 里的全局异常处理器调用，
        业务代码通常不需要手动调这个——直接 `raise AppException(...)`，
        异常处理器会自动转成这个格式。
        """
        return cls(
            success=False, data=None, error=ErrorDetail(code=code, message=message, details=details)
        )
