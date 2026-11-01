"""将旧演示订单编号迁移到统一格式；事务内保留订单及售后关联。"""
import asyncio
import hashlib
import json

from sqlalchemy import select

from app.db import base as db
from app.db.commerce import AfterSalesCase, Order

ORDER_ID_MAP = {"1001": "ES20260704001", "2002": "ES20260707001"}


async def migrate() -> dict[str, str]:
    changed = {}
    async with db.async_session() as session, session.begin():
        for old_id, new_id in ORDER_ID_MAP.items():
            old = await session.scalar(select(Order).where(Order.id == old_id).with_for_update())
            if old is None:
                continue
            if await session.get(Order, new_id) is not None:
                raise RuntimeError(f"目标编号 {new_id} 已存在，迁移已回滚")
            values = {column.name: getattr(old, column.name) for column in Order.__table__.columns}
            values["id"] = new_id
            # 先释放物流号唯一约束，再复制订单；不关闭外键检查。
            old.tracking_no = None
            await session.flush()
            session.add(Order(**values))
            await session.flush()
            cases = (await session.scalars(select(AfterSalesCase).where(
                AfterSalesCase.order_id == old_id).with_for_update())).all()
            for case in cases:
                case.order_id = new_id
                if case.active_order == old_id:
                    case.active_order = new_id
                case.fingerprint = hashlib.sha256(json.dumps(
                    [new_id, case.reason, case.description, case.conversation_id],
                    ensure_ascii=False).encode()).hexdigest()
            await session.flush()
            await session.delete(old)
            await session.flush()
            changed[old_id] = new_id
    return changed


async def main():
    try:
        print(json.dumps(await migrate(), ensure_ascii=False))
    finally:
        await db.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
