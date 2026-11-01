from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from pydantic import Field

from app.tools import registry
from app.tools.business import order_snapshot, owns_order


NOT_OWNED = {"error": "没有找到您的这笔订单", "code": "order_not_owned"}


@tool(description='按当前用户的订单号查询订单状态、金额、商品与物流单号；身份由系统注入。')
async def query_order(
    order_id: Annotated[str, Field(description="订单号,例如 1001")],
    user_id: Annotated[str, InjectedToolArg],
) -> dict:
    if not await owns_order(user_id, order_id):
        return dict(NOT_OWNED)
    return await order_snapshot(order_id)


@tool(description='按名称关键词查询商品库，返回候选商品的价格、库存与规格；items 为空时不得编造商品。')
async def query_product(
    product_name: Annotated[str, Field(description="商品名称或关键词,例如 猫粮")],
) -> dict:
    from sqlalchemy import select
    from app.db import base as db
    from app.db.commerce import Product

    async with db.async_session() as session:
        rows = (await session.scalars(select(Product).where(
            Product.name.contains(product_name, autoescape=True)).limit(5))).all()
        return {"items": [{"product_name": p.name, "price": p.price_cents / 100,
                           "stock": p.stock, "spec": p.specification} for p in rows]}


registry.register(registry.spec_from_langchain_tool(
    query_order, source="builtin", inject_user_id=True))
registry.register(registry.spec_from_langchain_tool(query_product, source="builtin"))
