from app.core.commerce import list_orders, owned_order
from app.db import base as db
from app.db.commerce import Order, Product


async def order_snapshot(order_id: str) -> dict:
    async with db.async_session() as session:
        order = await session.get(Order, order_id)
        if order is None:
            return {"error": "订单不存在"}
        product = await session.get(Product, order.product_id)
        from app.core.commerce import order_view
        return order_view(order, product)


async def owns_order(user_id: str, order_id: str) -> bool:
    return bool(user_id and order_id and await owned_order(user_id, order_id))


async def list_user_orders(user_id: str) -> list[dict]:
    return await list_orders(user_id)
