import pathlib

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

_TEST_URL = settings.test_database_url


@pytest.fixture(autouse=True)
def _no_langsmith(monkeypatch):
    monkeypatch.setattr("app.config.settings.langsmith_tracing", False)


@pytest_asyncio.fixture()
async def _test_engine(tmp_path):
    from app.db.base import Base
    from app.db import models, commerce
    from sqlalchemy.engine import make_url

    url = make_url(_TEST_URL)
    if url.drivername.startswith("sqlite"):
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'regression.sqlite'}")
    else:
        if not (url.database or "").endswith("_test"):
            raise RuntimeError("测试数据库名必须以 _test 结尾")
        admin = create_async_engine(url.set(database=None), isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{url.database}` CHARACTER SET utf8mb4"))
        await admin.dispose()
        engine = create_async_engine(_TEST_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session_factory(_test_engine, monkeypatch):
    factory = async_sessionmaker(_test_engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.base.async_session", factory)
    return factory


@pytest_asyncio.fixture()
async def commerce_demo(_test_engine, db_session_factory, monkeypatch):
    from app.db import base as database
    from scripts.init_demo import initialize
    monkeypatch.setattr(database, "engine", _test_engine)
    monkeypatch.setattr(settings, "demo_accounts_enabled", True)
    monkeypatch.setattr(settings, "demo_password", "TestPortfolio2026!")
    await initialize()


@pytest_asyncio.fixture()
async def db_clean():
    yield


@pytest.fixture()
def client():
    from app.api.actions import router as actions_router
    test_app = FastAPI()
    test_app.include_router(actions_router)
    return TestClient(test_app)
