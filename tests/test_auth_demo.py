from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import auth as auth_api
from app.config import settings


def _client() -> AsyncClient:
    app = FastAPI()
    app.include_router(auth_api.router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_demo_accounts_return_password_for_one_click_fill(monkeypatch):
    monkeypatch.setattr(settings, "demo_accounts_enabled", True)
    monkeypatch.setattr(settings, "demo_password", "DemoPass2026!")
    async with _client() as client:
        body = (await client.get("/api/auth/demo-accounts")).json()
    assert [item["email"] for item in body["items"]] == [
        "lin@eshop.demo",
        "zhou@eshop.demo",
        "agent@eshop.demo",
    ]
    assert body["password"] == "DemoPass2026!"


async def test_demo_accounts_hidden_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "demo_accounts_enabled", False)
    async with _client() as client:
        body = (await client.get("/api/auth/demo-accounts")).json()
    assert body == {"items": []}
