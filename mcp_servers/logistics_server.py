import asyncio
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("logistics",
              host="127.0.0.1", port=int(os.environ.get("PORT", "8111")))

_DELAY = float(os.environ.get("MOCK_DELAY_SECONDS", "0"))
_STATUS_CODES = ["PICKED_UP", "IN_TRANSIT", "DELIVERING", "DELIVERED"]
_CITIES = ["深圳", "广州", "杭州", "上海", "成都"]


@mcp.tool(description='用物流单号(tracking_no)查询物流状态、当前位置和轨迹。用于用户询问物流/快递到哪了时。\n物流单号不是订单号,需先用 query_order 查订单拿到 tracking_no,再调用本工具。')
async def query_logistics(
    tracking_no: Annotated[str, Field(description="物流单号(形如 SF 开头),需先用 query_order 查订单拿到该单号")],
) -> dict:
    from app.core.external_services import logistics
    return await logistics(tracking_no)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
