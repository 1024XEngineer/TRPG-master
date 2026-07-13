"""账号与登录 —— 对应 API 对齐规范 §2.0（ADR-16：登录是玩游戏的硬性前提）。"""

from __future__ import annotations

import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.db import get_sessionmaker
from core.state.db_models import UserRow, UserSessionRow
from server.rest.deps import get_current_user
from server.rest.schema import CamelModel

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(CamelModel):
    account: str
    password: str
    nickname: str


class LoginRequest(CamelModel):
    account: str
    password: str


class AuthResponse(CamelModel):
    user_id: str
    token: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest) -> AuthResponse:
    """账号密码由玩家自己填，注册成功直接可用；account 已占用返回 409。"""
    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user_id = f"user_{uuid.uuid4().hex[:12]}"

    async with get_sessionmaker()() as session:
        session.add(UserRow(id=user_id, account=body.account, password_hash=password_hash, nickname=body.nickname))
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="account 已被注册")

        token = f"tok_{secrets.token_urlsafe(32)}"
        session.add(UserSessionRow(token=token, user_id=user_id))
        await session.commit()
        return AuthResponse(user_id=user_id, token=token)


@router.post("/login")
async def login(body: LoginRequest) -> AuthResponse:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(UserRow).where(UserRow.account == body.account))
        user = result.scalar_one_or_none()
        if user is None or not bcrypt.checkpw(body.password.encode("utf-8"), user.password_hash.encode("utf-8")):
            raise HTTPException(status_code=401, detail="账号或密码错误")

        token = f"tok_{secrets.token_urlsafe(32)}"
        session.add(UserSessionRow(token=token, user_id=user.id))
        await session.commit()
        return AuthResponse(user_id=user.id, token=token)


@router.post("/logout", status_code=204)
async def logout(authorization: str = Header(default="")) -> None:
    """撤销当前 user_sessions 记录（真实服务端 session，非无状态 JWT）。"""
    if not authorization.startswith("Bearer "):
        return
    token = authorization.removeprefix("Bearer ").strip()
    async with get_sessionmaker()() as session:
        row = await session.get(UserSessionRow, token)
        if row is not None:
            await session.delete(row)
            await session.commit()


class MeResponse(CamelModel):
    user_id: str
    account: str
    nickname: str


@router.get("/me")
async def me(user: UserRow = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user_id=user.id, account=user.account, nickname=user.nickname)
