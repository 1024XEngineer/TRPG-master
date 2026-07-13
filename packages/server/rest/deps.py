"""鉴权依赖 —— 从 Authorization: Bearer <token> 解析出当前登录用户。

真实服务端 session（user_sessions 表），不是无状态 JWT，见 auth.py 顶部说明。
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from core.db import get_sessionmaker
from core.state.db_models import UserRow, UserSessionRow


async def get_current_user(authorization: str = Header(default="")) -> UserRow:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少或格式错误的 Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    async with get_sessionmaker()() as session:
        user_session = await session.get(UserSessionRow, token)
        if user_session is None:
            raise HTTPException(status_code=401, detail="登录状态无效或已过期")
        user = await session.get(UserRow, user_session.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="账号不存在")
        return user
