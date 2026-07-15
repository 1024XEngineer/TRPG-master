from typing import Self

from pydantic import BaseModel

from app.core.errors import ErrorCode


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ApiResponse[T](BaseModel):
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> Self:
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, code: ErrorCode, message: str) -> Self:
        return cls(success=False, data=None, error=ErrorDetail(code=code, message=message))
