import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db import base as db, repository
from app.db.commerce import Account, LoginSession

COOKIE = "eshop_session"


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
    return salt + ":" + value


def check_password(password: str, encoded: str) -> bool:
    salt, value = encoded.split(":", 1)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
    return hmac.compare_digest(value, actual)


async def issue_session(account_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = digest("csrf:" + token)
    async with db.async_session() as session:
        session.add(LoginSession(token_hash=digest(token), user_id=account_id,
                                 csrf_hash=digest(csrf),
                                 expires_at=now() + timedelta(hours=settings.session_hours)))
        await session.commit()
    return token, csrf


async def current_user(request: Request) -> Account:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "请先登录")
    async with db.async_session() as session:
        login = await session.get(LoginSession, digest(token))
        if login is None or login.expires_at <= now():
            raise HTTPException(401, "登录已过期，请重新登录")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(login.csrf_hash, digest(csrf)):
                raise HTTPException(403, "请求校验失败，请重新登录")
        account = await session.get(Account, login.user_id)
        if account is None:
            raise HTTPException(401, "账号不存在")
        return account


async def staff_user(user: Account = Depends(current_user)) -> Account:
    if user.role != "agent":
        raise HTTPException(403, "需要客服权限")
    return user


async def own_conversation(conversation_id: int, user: Account) -> None:
    conversation = await repository.get_conversation(conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(404, "会话不存在")


async def load_account(email: str) -> Account | None:
    async with db.async_session() as session:
        return await session.scalar(select(Account).where(Account.email == email.lower().strip()))
