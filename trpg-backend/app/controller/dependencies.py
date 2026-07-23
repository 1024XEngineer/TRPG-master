"""跨 controller 复用的 FastAPI 依赖（issue #77）。

解析同一个 `Authorization: Bearer <token>` 头，但分成两个依赖：

- `get_current_user`：**要求登录**，拿不到有效登录态直接 401。
- `get_optional_user`：登录可选，拿不到返回 None。

issue #106 起，创建/加入房间从 `get_optional_user` 换成了 `get_current_user`。
原来"登录可选"的写法是 `Room.host_user_id`/`Player.user_id` 恒为 `null` 的直接
原因——一个"可以不填"的身份字段，在没人强制时就永远是空的，所有依赖它的功能
（跨设备找回、我的游戏、按账号幂等重连）都成了空中楼阁。
"""

from fastapi import Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.models.user import User
from app.service import auth as auth_service


def extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    prefix = "Bearer "
    return authorization[len(prefix) :] if authorization.startswith(prefix) else authorization


async def get_optional_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """解析 Authorization 头，查不到有效登录态时返回 None 而不是报错。"""
    return await auth_service.resolve_user(db, extract_bearer_token(authorization))


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Authorization 头并要求登录态有效，否则 401。

    抛 `AppException` 而不是 `auth_service.AuthenticationError`：这个依赖在路由
    函数体**之前**执行，controller 里的 try/except 根本罩不到它，服务层异常跑出来
    会被全局兜底转成 500。直接抛 `AppException` 才能落到正确的 401。
    """
    user = await auth_service.resolve_user(db, extract_bearer_token(authorization))
    if user is None:
        raise AppException(
            ErrorCode.UNAUTHORIZED,
            "登录凭证无效" if authorization is not None else "缺少登录凭证",
            status.HTTP_401_UNAUTHORIZED,
        )
    return user
