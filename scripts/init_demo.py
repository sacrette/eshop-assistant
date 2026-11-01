import asyncio
from datetime import timedelta
from pathlib import Path

from app.config import settings
from app.core.auth import hash_password, now
from app.db import base as db
from app.db import models
from app.db.commerce import Account, Order, Product


async def initialize() -> None:
    if not settings.demo_accounts_enabled or len(settings.demo_password) < 6:
        raise RuntimeError("请设置 DEMO_ACCOUNTS_ENABLED=true 和至少 6 位的 DEMO_PASSWORD")
    Path("data").mkdir(exist_ok=True)
    async with db.engine.begin() as connection:
        await connection.run_sync(db.Base.metadata.create_all)
    stamp = now()
    async with db.async_session() as session:
        accounts = [("customer-lin", "lin@eshop.demo", "林悦", "customer"),
                    ("customer-zhou", "zhou@eshop.demo", "周然", "customer"),
                    ("agent-chen", "agent@eshop.demo", "陈曦", "agent")]
        for uid, email, name, role in accounts:
            if await session.get(Account, uid) is None:
                session.add(Account(id=uid, email=email, name=name, role=role,
                                    password_hash=hash_password(settings.demo_password)))
        products = [("MH-LP100", "智能猫砂盆 Pro", 129900, 46, {"容量": "65L", "保修": "一年"}),
                    ("MH-W20", "自动饮水机", 23900, 128, {"容量": "2L", "保修": "一年"}),
                    ("MH-CT30", "大型猫爬架", 45900, 23, {"高度": "150cm", "材质": "剑麻"})]
        for pid, name, cents, stock, spec in products:
            if await session.get(Product, pid) is None:
                session.add(Product(id=pid, name=name, price_cents=cents, stock=stock, specification=spec))
        await session.flush()
        fixtures = [("ES20261018001", "customer-lin", "MH-LP100", "已签收", 129900, 2),
                    ("ES20261018002", "customer-lin", "MH-W20", "已发货", 23900, None),
                    ("ES20261018003", "customer-lin", "MH-CT30", "已签收", 45900, 20),
                    ("ES20261018004", "customer-lin", "MH-W20", "待付款", 23900, None),
                    ("ES20261018005", "customer-zhou", "MH-LP100", "已签收", 129900, 1),
                    ("ES20261018006", "customer-zhou", "MH-CT30", "已付款", 45900, None)]
        for oid, uid, pid, status, amount, days in fixtures:
            if await session.get(Order, oid) is not None:
                continue
            events = [] if status in {"已付款", "待付款"} else [
                {"time": (stamp - timedelta(days=3)).isoformat(), "city": "杭州", "text": "包裹已揽收"},
                {"time": (stamp - timedelta(days=2)).isoformat(), "city": "上海", "text": "包裹已签收" if days is not None else "包裹运输中"}]
            session.add(Order(id=oid, user_id=uid, product_id=pid, status=status,
                              amount_cents=amount, created_at=stamp - timedelta(days=(days or 0) + 3),
                              delivered_at=stamp - timedelta(days=days) if days is not None else None,
                              tracking_no="SF" + oid[2:] if events else None, logistics=events))
        await session.commit()
    await db.engine.dispose()
    print("演示数据已初始化：3 个账号、3 件商品、6 笔订单。重复运行不会覆盖现有记录。")


if __name__ == "__main__":
    asyncio.run(initialize())
