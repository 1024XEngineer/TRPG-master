"""FastAPI 应用入口：组装 app、注册中间件/路由，并集中处理所有异常。

这个文件是全项目"兜底"逻辑的落脚点——任何路由里没有手动处理的异常，
最终都会走到这里定义的某个 exception_handler，被统一转成
`{success, data, error}` 格式的 JSON 响应，业务代码不需要在每个接口里
重复写 try/except。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.controller.v1.router import api_router
from app.controller.ws import router as ws_router
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.errors import AppException, ErrorCode
from app.core.logging import configure_logging
from app.core.narrator import build_narrator
from app.core.seed import ensure_seed_content
from app.dto.common import ApiResponse

# 模块被导入时就把 structlog 配好（只需要配一次），后面直接用 structlog.get_logger()。
configure_logging()
logger = structlog.get_logger()

# 给 Starlette 原生抛出的 HTTPException（比如请求了一个不存在的路由，
# Starlette 会自己抛 404）分配一个合理的 ErrorCode，这样即使不是我们业务代码
# 主动抛出的错误，也能落进统一的错误码体系里，而不是裸露一个没有 code 字段的响应。
_HTTP_STATUS_ERROR_CODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_ERROR,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI 的应用生命周期钩子：`yield` 之前的代码在启动时跑一次，
    之后的代码在应用关闭时跑一次。

    issue #77 决策 9：建表不再由这里的 `init_db()`（`create_all`）负责——
    `create_all` 只会"没表就建、有表就跳过"，不会处理改名/加字段这类真实
    迁移场景，本期把 `room_players` 改名成 `players`、给 `rooms` 加了一批
    字段，继续用它会让开发者拿到一个"代码以为字段存在、数据库其实没有"的
    坏状态。建表这一步交给 `alembic upgrade head`（见 README 启动步骤），
    这里只负责插入内置模组这类种子数据（`ensure_seed_content` 是幂等的，
    如果表还不存在——也就是忘了跑 alembic——会直接报错而不是静默跳过，
    这是有意的，逼着开发者按新的启动步骤来）。
    """
    async with async_session_factory() as db:
        await ensure_seed_content(db)
    logger.info("app_started")
    yield
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """应用工厂函数：每次调用都会构造一个全新的 FastAPI 实例。

    写成工厂函数（而不是在模块顶层直接 `app = FastAPI(...)`）是常见做法，
    方便以后测试代码需要"用不同配置构造多个 app 实例"时复用；当前测试
    (tests/conftest.py) 走的是另一条路径——直接对 `app` 这个全局单例做
    dependency_overrides，两种方式都合理，这里保留工厂函数是为了扩展性。
    """
    settings = get_settings()

    app = FastAPI(
        title="TRPG-master API",
        # 用同一个配置项统一控制三个文档相关的路由是否注册；生产环境把
        # ENABLE_DOCS 设为 false，这三个 URL 就完全不存在（不是"存在但拒绝访问"）。
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )

    # AI 主持人叙事生成器（issue #107）：按配置在真实 DeepSeek / 占位文案之间
    # 二选一，挂在 app.state 上——ws.py 通过 websocket.app.state.narrator 取用，
    # 测试直接覆盖这个属性注入 fake（不用 monkeypatch 模块内部）。放在这里而
    # 不是 lifespan：构造 narrator 没有任何 IO，而测试用的 TestClient/
    # ASGITransport 不一定会触发 lifespan——挂在 create_app 里保证"有 app
    # 实例就一定有 narrator"。
    app.state.narrator = build_narrator(settings)

    # 允许配置里列出的前端源发起跨域请求（本地开发场景下 Vite 默认跑在
    # 9877 端口，跟后端的 8000 端口不同源，没有这个中间件浏览器会拦截请求）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    app.include_router(ws_router)

    # ---- 以下四个异常处理器，按"从具体到通用"的顺序注册 ----
    # FastAPI/Starlette 在分发异常时，会按抛出异常的实际类型去匹配"最具体"的
    # handler（沿着异常类的 MRO 找），所以即使 AppException/RequestValidationError/
    # StarletteHTTPException 本质上都是 Exception 的子类，也不会被最后那个
    # "捕获所有 Exception"的兜底 handler 抢走——各自的专属 handler 优先命中。

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """业务代码主动抛出的 AppException（比如 404/409），直接按它自带的
        code/message/status_code 包装成统一响应体。"""
        logger.warning("app_exception", code=exc.code, message=exc.message, path=request.url.path)
        body = ApiResponse.fail(exc.code, exc.message, exc.details)
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求体/查询参数没通过 pydantic 校验时，FastAPI 会抛这个异常。
        默认的错误信息是一个结构化的列表（每项包含出错字段路径 loc 和错误信息 msg），
        这里拼成一行人类可读的字符串，塞进统一响应体的 error.message 里。"""
        message = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        body = ApiResponse.fail(ErrorCode.VALIDATION_ERROR, message or "请求参数校验失败")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """兜住框架自己抛出的 HTTPException（比如访问不存在的路由时 Starlette
        自动抛 404），用上面的映射表转成对应的 ErrorCode。"""
        code = _HTTP_STATUS_ERROR_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        body = ApiResponse.fail(code, str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """最后一道防线：任何没被上面三个 handler 接住的异常（比如代码里的
        NPE、数据库连接失败等真正的 bug），一律转成 500 + INTERNAL_ERROR，
        不把内部异常信息泄露给客户端；`logger.exception` 会把完整堆栈记进日志，
        方便排查，但响应体里只给一句通用的"服务器内部错误"。"""
        logger.exception("unhandled_exception", path=request.url.path)
        body = ApiResponse.fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=jsonable_encoder(body)
        )

    return app


# 进程启动时（比如 `uvicorn app.main:app`）实际加载的应用实例。
app = create_app()
