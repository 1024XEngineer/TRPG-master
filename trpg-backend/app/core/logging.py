"""structlog 结构化日志配置。

跟标准库 `logging` 直接打印字符串不同，structlog 记的是「事件名 + 一堆
key=value 字段」（比如 logger.warning("app_exception", code=..., path=...)），
这样日志既能在开发时人读，又能在生产环境里被日志系统（ELK/Datadog 等）当结构化
数据解析、按字段过滤检索，不用再写正则去 parse 一行字符串。
"""

import logging
import re
import sys

import structlog

from app.core.config import get_settings

_ROOM_POLL_PATH = re.compile(r"^/api/v1/rooms/[A-Z0-9]{6}(?:\?.*)?$")
_CONVERSATION_PATH = re.compile(
    r"^/api/v1/rooms/[0-9a-fA-F-]{32,36}/conversation(?:\?.*)?$"
)
_HEALTH_PATHS = {"/health", "/api/v1/health"}


class AccessNoiseFilter(logging.Filter):
    """隐藏成功的高频访问噪声，但始终保留错误响应。

    Uvicorn 的访问日志使用固定参数：
    ``(client_addr, method, path, http_version, status_code)``。这里只过滤
    浏览器 CORS 预检、房间状态轮询、对话历史恢复和健康检查的成功响应；
    同一路径一旦返回 4xx/5xx 仍然会原样输出，避免真正的问题被隐藏。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request = _access_request(record)
        if request is None:
            return True
        method, path, status_code = request
        if status_code >= 400:
            return True
        if method == "OPTIONS":
            return False
        path_without_query = path.split("?", 1)[0]
        if method == "GET" and path_without_query in _HEALTH_PATHS:
            return False
        return not (
            method == "GET"
            and (
                _ROOM_POLL_PATH.fullmatch(path)
                or _CONVERSATION_PATH.fullmatch(path)
            )
        )


def _access_request(record: logging.LogRecord) -> tuple[str, str, int] | None:
    args = record.args
    if (
        isinstance(args, tuple)
        and len(args) >= 5
        and isinstance(args[1], str)
        and isinstance(args[2], str)
        and isinstance(args[4], int)
    ):
        return args[1], args[2], args[4]
    return None


def configure_logging() -> None:
    """全局配置一次 structlog，之后各模块用 `structlog.get_logger()` 直接取用。

    只需要在进程启动时调用一次（main.py 顶层导入时就会调用），不需要每个模块
    各自配置一遍。
    """
    settings = get_settings()
    # settings.log_level 是形如 "INFO"/"DEBUG" 的字符串，这里转成 logging 模块
    # 认识的整数级别常量；如果配置写错了（比如手滑打成 "INF"），就退回 INFO，
    # 不会因为一个拼写错误导致进程启动失败。
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 这几个 processor 是开发/生产两种输出格式共用的前置处理步骤：
    # - merge_contextvars：把用 structlog.contextvars 绑定的上下文字段
    #   （如 request_id）自动带进每条日志
    # - add_log_level：给每条日志加上 level 字段（info/warning/...）
    # - TimeStamper：加 ISO 格式时间戳
    # - StackInfoRenderer / format_exc_info：如果日志调用带了异常信息
    #   （比如 logger.exception(...)），格式化成可读的堆栈
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # 生产环境：直接输出单行 JSON，方便日志采集系统解析；
    # 开发环境：用 structlog 自带的彩色可读渲染器，终端里看着舒服。
    # 这一个开关就是本项目"统一走 structlog、按环境切换格式"的落地方式。
    if settings.app_env == "production":
        # ensure_ascii=False：JSONRenderer 底层用 json.dumps，默认会把非 ASCII
        # 字符（中文错误信息等）转义成 \uXXXX 序列——写日志采集系统没问题，但人
        # 直接看 stdout 排障时全是转义字符，不可读。关掉这个默认行为，日志里
        # 直接是原样的中文。
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        # 按配置的 level 过滤日志，低于该级别的日志在最早期就被丢弃，
        # 不走后面的 processor，性能更好。
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        # 直接打印到 stdout，不写文件——容器化部署下日志由平台统一采集 stdout，
        # 应用自己维护日志文件反而是负担。
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        # 缓存每个 logger 实例，避免每次 get_logger() 都重新构建一遍 processor 链。
        cache_logger_on_first_use=True,
    )

    # Uvicorn 访问日志走标准库 logging，不经过上面的 structlog processors。
    # Filter 直接挂在 uvicorn.access logger 上；--reload 的工作进程导入应用时
    # 会再次执行这里，而 isinstance 检查保证同一进程不会重复安装。
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessNoiseFilter) for item in access_logger.filters):
        access_logger.addFilter(AccessNoiseFilter())


__all__ = ["AccessNoiseFilter", "configure_logging"]
