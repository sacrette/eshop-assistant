from datetime import timedelta

from sqlalchemy import select

from app.core.auth import now
from app.db import base as db
from app.db.commerce import AfterSalesCase, Order


async def logistics(tracking_no: str) -> dict:
    async with db.async_session() as session:
        order = await session.scalar(select(Order).where(Order.tracking_no == tracking_no))
        if order is None:
            return {"error": "物流记录不存在"}
        latest = order.logistics[-1] if order.logistics else {}
        return {"tracking_no": tracking_no,
                "status_code": "DELIVERED" if order.delivered_at else "IN_TRANSIT",
                "current_city": latest.get("city"), "trace": order.logistics}


async def warranty(order_id: str) -> dict:
    async with db.async_session() as session:
        order = await session.get(Order, order_id)
        if order is None:
            return {"error": "订单不存在"}
        until = (order.delivered_at or order.created_at) + timedelta(days=365)
        return {"order_id": order_id, "warranty_code": "IN_WARRANTY" if now() <= until else "EXPIRED",
                "warranty_until": until.date().isoformat()}


async def return_status(order_id: str) -> dict:
    async with db.async_session() as session:
        case = await session.scalar(select(AfterSalesCase).where(AfterSalesCase.order_id == order_id)
                                    .order_by(AfterSalesCase.created_at.desc()))
        return {"order_id": order_id, "return_code": case.status if case else "NONE",
                "updated_at": case.created_at.isoformat() if case else None}
