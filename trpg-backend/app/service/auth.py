"""Service 层：账号 + 会话（issue #58，issue #77 切换为真实 ORM 读写）。

密码用 bcrypt 加盐哈希存储，不落明文；会话是随机 token，登录/注册时签发，
存进 `user_sessions` 表换取用户，不做过期/续期（MS1 范围不包含"多设备会话
管理"）。原来的内存字典（`_users`/`_accounts`/`_tokens`）已替换为对
`users`/`user_sessions` 两张表的真实读写——进程重启后账号数据不再丢失。
"""

import asyncio
import hashlib
import uuid

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.auth import AuthResult, MeRead
from app.models.user import User, UserSession


class AccountExistsError(ValueError):
    """账号已被注册。"""


class InvalidCredentialsError(PermissionError):
    """账号或密码不正确。"""


class AuthenticationError(PermissionError):
    """未提供有效的登录凭证。"""


def _prehash(password: str) -> bytes:
    """bcrypt 只认密码的前 72 字节，超出部分会被静默截断——密码开到 100 字符
    时，两个仅在 72 字节之后不同的密码会算出同一个哈希，等于变相碰撞（code
    review 用真实 bcrypt 4.3.0 复现过）。这里先用 sha256 摘要成固定 32 字节
    再喂给 bcrypt，从根源上避开这个截断限制，而不是缩短密码长度上限。
    """
    return hashlib.sha256(password.encode()).digest()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_prehash(password), password_hash.encode())


async def register(db: AsyncSession, account: str, password: str, nickname: str) -> AuthResult:
    """注册新账号，成功即视为登录，直接签发 token。"""
    existing = await db.scalar(select(User).where(User.account == account))
    if existing is not None:
        raise AccountExistsError("账号已被注册")

    # bcrypt 是同步、CPU 密集的调用，直接在协程里跑会阻塞事件循环处理其它
    # 并发请求，丢进线程池执行。
    password_hash = await asyncio.to_thread(_hash_password, password)
    user = User(account=account, password_hash=password_hash, nickname=nickname)
    db.add(user)
    await db.flush()  # 拿到 user.id，还不提交事务

    token = str(uuid.uuid4())
    db.add(UserSession(user_id=user.id, token=token))
    await db.commit()

    return AuthResult(token=token, user_id=user.id, nickname=user.nickname)


async def login(db: AsyncSession, account: str, password: str) -> AuthResult:
    """账号密码登录。"""
    user = await db.scalar(select(User).where(User.account == account))
    if user is None:
        raise InvalidCredentialsError("账号或密码不正确")
    verified = await asyncio.to_thread(_verify_password, password, user.password_hash)
    if not verified:
        raise InvalidCredentialsError("账号或密码不正确")

    token = str(uuid.uuid4())
    db.add(UserSession(user_id=user.id, token=token))
    await db.commit()
    return AuthResult(token=token, user_id=user.id, nickname=user.nickname)


async def logout(db: AsyncSession, token: str | None) -> None:
    """退出登录，使当前 token 失效。"""
    if token is None:
        return
    session = await db.scalar(select(UserSession).where(UserSession.token == token))
    if session is not None:
        await db.delete(session)
        await db.commit()


async def resolve_user(db: AsyncSession, token: str | None) -> User | None:
    """按 token 查用户，查不到（token 缺失/无效）返回 None 而不是抛异常。

    给"登录可选"的场景用——比如创建/加入房间接口本期不强制要求登录（见
    Room.host_user_id 的注释），带了 Authorization 就关联账号，没带也能
    正常创建/加入。
    """
    if token is None:
        return None
    session = await db.scalar(select(UserSession).where(UserSession.token == token))
    if session is None:
        return None
    return await db.get(User, session.user_id)


async def _get_user_by_token(db: AsyncSession, token: str | None) -> User:
    user = await resolve_user(db, token)
    if user is None:
        raise AuthenticationError("登录凭证无效" if token is not None else "缺少登录凭证")
    return user


async def get_me(db: AsyncSession, token: str | None) -> MeRead:
    """获取当前登录用户。"""
    user = await _get_user_by_token(db, token)
    return MeRead(user_id=user.id, account=user.account, nickname=user.nickname)


async def update_nickname(db: AsyncSession, token: str | None, nickname: str) -> MeRead:
    """修改当前登录用户的昵称（账号只读，本期不允许修改）。"""
    user = await _get_user_by_token(db, token)
    user.nickname = nickname
    await db.commit()
    return MeRead(user_id=user.id, account=user.account, nickname=user.nickname)
