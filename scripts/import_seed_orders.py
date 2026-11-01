import asyncio
from datetime import datetime

from app.db import base as db
from app.db.commerce import Account, Order, Product


async def main() -> None:
    fixtures = [
        ("1001", "seed-lp100", "智能猫砂盆", "已付款", 173900,
         "2026-07-04 10:00", "SF213502378238"),
        ("2002", "seed-wd200", "自动饮水机", "待付款", 155700,
         "2026-07-07 10:00", "SF970058539216"),
    ]
    try:
        async with db.async_session() as session:
            if await session.get(Account, "customer-lin") is None:
                raise RuntimeError("请先运行 scripts.init_demo")
            for oid, pid, name, status, cents, created, tracking in fixtures:
                if await session.get(Order, oid) is not None:
                    continue
                if await session.get(Product, pid) is None:
                    session.add(Product(id=pid, name=name, price_cents=cents, stock=0,
                                        specification={"来源": "固定随机种子生成的模拟订单快照"}))
                await session.flush()
                session.add(Order(id=oid, user_id="customer-lin", product_id=pid,
                                  status=status, amount_cents=cents,
                                  created_at=datetime.strptime(created, "%Y-%m-%d %H:%M"),
                                  delivered_at=None, tracking_no=tracking, logistics=[]))
            await session.commit()
        print("1001、2002 已导入林悦演示账号；保留快照中的状态与物流单号，未编造物流事件。")
    finally:
        await db.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
