import hashlib
import json
from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import base as db, models
from app.db.commerce import Account, AfterSalesCase, Order, Product


@pytest.mark.asyncio
async def test_migration_preserves_order_and_case_with_foreign_keys(tmp_path, monkeypatch):
    from scripts.normalize_order_ids import migrate
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'orders.sqlite'}")
    @event.listens_for(engine.sync_engine, "connect")
    def fk(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session", factory)
    async with factory() as session:
        session.add(Account(id="u", email="u@test", name="u", role="customer", password_hash="x"))
        session.add(Product(id="p", name="饮水机", price_cents=23900, stock=1, specification={}))
        await session.flush()
        session.add(Order(id="1001", user_id="u", product_id="p", status="已付款", amount_cents=23900,
            created_at=datetime(2026, 7, 4), tracking_no="SF123", logistics=[{"text": "原始轨迹"}]))
        await session.flush()
        session.add(AfterSalesCase(id="AS1", user_id="u", order_id="1001", active_order="1001",
            reason="质量问题", description="故障", status="pending", idempotency_key="k",
            fingerprint="old", created_at=datetime(2026, 7, 5)))
        await session.commit()
    assert await migrate() == {"1001": "ES20260704001"}
    assert await migrate() == {}
    async with factory() as session:
        assert await session.get(Order, "1001") is None
        order = await session.get(Order, "ES20260704001")
        assert order.tracking_no == "SF123" and order.amount_cents == 23900
        assert order.logistics == [{"text": "原始轨迹"}]
        case = await session.get(AfterSalesCase, "AS1")
        assert case.order_id == case.active_order == order.id
        assert case.fingerprint == hashlib.sha256(json.dumps(
            [order.id, "质量问题", "故障", None], ensure_ascii=False).encode()).hexdigest()
    await engine.dispose()
