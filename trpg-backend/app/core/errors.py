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

    # ── 以下 9 个是 issue #77 §4 新增的业务语义码（架构文档定过、代码里原来
    # 没有），跟上面 7 个工程通用码取并集，而不是互相替代——判据见 issue
    # 决策 2：业务语义层的错误码以文档为准。
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"  # 房间不存在（比通用 NOT_FOUND 更具体）→ 404
    ROOM_FULL = "ROOM_FULL"  # 房间人数已满，无法加入 → 409
    MODULE_VALIDATION_FAILED = "MODULE_VALIDATION_FAILED"  # 模组导入解析/校验失败 → 422
    NOT_YOUR_TURN = "NOT_YOUR_TURN"  # 回合制约束：还没轮到这名玩家行动 → 409
    ACTION_IN_PROGRESS = "ACTION_IN_PROGRESS"  # 房间内已有人在等 AI 主持人回应，他人提交被拒 → 409
    CHARACTER_INCOMPLETE = "CHARACTER_INCOMPLETE"  # 角色卡未建完，无法进行需要角色的操作 → 409
    MODULE_NOT_SELECTED = "MODULE_NOT_SELECTED"  # 房间还没选定模组 → 409
    RECONNECT_TOKEN_EXPIRED = "RECONNECT_TOKEN_EXPIRED"  # 断线重连凭证失效（room.rejoin）→ 401
    RATE_LIMITED = "RATE_LIMITED"  # 请求频率超限 → 429
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # 协议位置已预留，真实业务逻辑本期未实现 → 501

    # issue #84 S2 新增：建卡数据未通过 COC7 权威校验（职业/兴趣技能点预算、
    # 技能上限、信用评级区间等）→ 422，`AppException.details` 带结构化校验报告。
    CHARACTER_INVALID = "CHARACTER_INVALID"

    # issue #112 新增：规则系统没有可用的规则数据（属性/技能/职业目录为空），
    # 无法据此裁决建卡 → 409。规则计算改参数注入后，"没有规则数据"在裁决路径上
    # 会退化成"零个约束"从而放行空白角色卡，必须显式拒绝而不是当成无约束。
    RULESET_NOT_CONFIGURED = "RULESET_NOT_CONFIGURED"


class AppException(Exception):
    """业务代码显式抛出的异常，携带错误码/状态码/用户可见信息。

    用法示例（见 controller/v1/rooms.py）：
        raise AppException(ErrorCode.NOT_FOUND, "房间不存在", status.HTTP_404_NOT_FOUND)

    main.py 里注册的 `app_exception_handler` 会捕获这个异常，把 code/message
    包进统一响应体 {success: false, data: null, error: {code, message}}，
    并用 status_code 作为 HTTP 状态码返回——业务代码本身不需要关心响应格式。

    status_code 没有默认值：项目里目前所有调用点都是显式传状态码的，如果给
    一个默认值（之前是 400），万一以后哪次调用忘了传，会悄悄退化成 400 而不是
    报错提醒——不如直接让它变成必填参数，强制每次调用都想清楚该返回什么状态码。

    `details` 是 issue #84 S2 新增的可选字段：`CHARACTER_INVALID` 这类错误
    需要把结构化的校验报告（一条条 code/field/message）带给前端，光一个
    message 字符串不够用；不传就是 None，不影响原有只带 code/message 的用法。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def not_implemented(message: str = "该功能本期尚未实现，接口协议已预留") -> AppException:
    """协议位置已预留、真实业务逻辑本期未实现时统一抛出（issue #77 决策 7）。

    用 501（Not Implemented）而不是 500/200+假成功：让客户端能明确区分
    "服务器出 bug 了"和"这个功能确实还没做"，而不是把两者混进同一个
    INTERNAL_ERROR，也不是悄悄返回一个看起来成功的空响应。本期有十来个
    端点/WS 事件走这条路径，抽成一个函数避免每处重复拼 AppException。
    """
    return AppException(ErrorCode.NOT_IMPLEMENTED, message, 501)
