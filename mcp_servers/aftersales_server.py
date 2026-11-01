import asyncio
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("aftersales",
              host="127.0.0.1", port=int(os.environ.get("PORT", "8112")))

_DELAY = float(os.environ.get("MOCK_DELAY_SECONDS", "0"))


@mcp.tool(description='查询某订单商品是否在保修期内(在保状态、到期日)。用于用户问保修/在保时。')
async def query_warranty(
    order_id: Annotated[str, Field(description="订单号,例如 1001")],
) -> dict:
    from app.core.external_services import warranty
    return await warranty(order_id)


@mcp.tool(description='查询某订单的退货进度(审核中/退货中/已退款/无退货记录)。用于用户问退货到哪一步了。')
async def query_return_status(
    order_id: Annotated[str, Field(description="订单号,例如 1001")],
) -> dict:
    from app.core.external_services import return_status
    return await return_status(order_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
