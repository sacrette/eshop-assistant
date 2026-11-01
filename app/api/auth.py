from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.core.auth import COOKIE, check_password, current_user, digest, issue_session, load_account
from app.db import base as db
from app.db.commerce import Account, LoginSession

router = APIRouter(prefix="/api/auth", tags=["认证"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=1, max_length=200)


def account_view(account: Account) -> dict:
    return {"id": account.id, "email": account.email, "name": account.name, "role": account.role}


@router.post("/login")
async def login(body: Credentials, response: Response):
    account = await load_account(body.email)
    if account is None or not check_password(body.password, account.password_hash):
        raise HTTPException(401, "邮箱或密码不正确")
    token, csrf = await issue_session(account.id)
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.session_hours * 3600, path="/")
    return {"user": account_view(account), "csrf_token": csrf}


@router.get("/me")
async def me(user: Account = Depends(current_user)):
    return account_view(user)


@router.get("/csrf")
async def csrf(request: Request, response: Response, user: Account = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": digest("csrf:" + request.cookies[COOKIE])}


@router.post("/logout")
async def logout(request: Request, response: Response, user: Account = Depends(current_user)):
    async with db.async_session() as session:
        login = await session.get(LoginSession, digest(request.cookies[COOKIE]))
        if login:
            await session.delete(login)
            await session.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/demo-accounts")
async def demo_accounts():
    # 演示入口默认关闭；开启后这里回传的密码就是 .env 里的 DEMO_PASSWORD，
    # 仅用于本地演示时一键填充，不再存储任何明文密码（库里只有哈希）。
    if not settings.demo_accounts_enabled:
        return {"items": []}
    return {
        "items": [
            {"email": "lin@eshop.demo", "name": "林悦", "role": "customer"},
            {"email": "zhou@eshop.demo", "name": "周然", "role": "customer"},
            {"email": "agent@eshop.demo", "name": "陈曦", "role": "agent"},
        ],
        "password": settings.demo_password,
    }
