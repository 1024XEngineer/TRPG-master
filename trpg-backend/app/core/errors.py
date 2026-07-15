"""统一错误码 + 业务异常基类。

配合 main.py 里的全局异常处理器使用：业务代码只管 `raise AppException(...)`，
不用在每个接口里手写 try/except 拼错误响应，响应格式和状态码统一由异常处理器兜底。
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """统一错误码枚举。

    用 StrEnum（Python 3.11+）而不是普通字符串常量或 int 枚举，好处是：
    - 序列化成 JSON 时直接是字符串值（比如 "NOT_FOUND"），前端/SDK 拿到的就是可读的码；
    - 类型检查器（ty/mypy）能校验到哪些地方在用错误码，重命名/新增时不会漏改；
    - 每个成员名本身就是 UPPER_SNAKE_CASE，跟成员值保持一致，一眼能看出对应关系。

    新增错误码时，在这里加一行即可；用哪个 HTTP 状态码由抛出方（业务代码里的
    AppException(...) 调用）决定，这个枚举本身不绑定状态码。
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"  # 请求体/参数没通过 pydantic 校验 → 422
    BAD_REQUEST = "BAD_REQUEST"  # 请求本身有问题但不属于校验错误 → 400
    UNAUTHORIZED = "UNAUTHORIZED"  # 未登录/凭证无效 → 401（当前骨架还没接鉴权，先占位）
    FORBIDDEN = "FORBIDDEN"  # 已登录但没权限 → 403（同上，先占位）
    NOT_FOUND = "NOT_FOUND"  # 资源不存在 → 404
    CONFLICT = "CONFLICT"  # 资源冲突，比如同名记录已存在 → 409
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 未预期的服务器内部错误 → 500


class AppException(Exception):
    """业务代码显式抛出的异常，携带错误码/状态码/用户可见信息。

    用法示例（见 controller/v1/examples.py）：
        raise AppException(ErrorCode.NOT_FOUND, "示例不存在", status.HTTP_404_NOT_FOUND)

    main.py 里注册的 `app_exception_handler` 会捕获这个异常，把 code/message
    包进统一响应体 {success: false, data: null, error: {code, message}}，
    并用 status_code 作为 HTTP 状态码返回——业务代码本身不需要关心响应格式。

    status_code 没有默认值：项目里目前所有调用点都是显式传状态码的，如果给
    一个默认值（之前是 400），万一以后哪次调用忘了传，会悄悄退化成 400 而不是
    报错提醒——不如直接让它变成必填参数，强制每次调用都想清楚该返回什么状态码。
    """

    def __init__(self, code: ErrorCode, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
