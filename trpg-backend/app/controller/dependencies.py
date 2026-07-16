"""跨 controller 复用的 FastAPI 依赖（issue #77）。

`GET /auth/me` 这类接口要求登录态必须有效（查不到就 401），而房间创建/加入
接口本期不强制登录（见 `models/room.py` 里 `Room.host_user_id` 的注释）——
两种场景都要解析同一个 `Authorization: Bearer <token>` 头，抽成共享依赖，
"要不要强制"留给各自 controller 自己决定要不要检查返回值是不是 None。
"""

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
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
