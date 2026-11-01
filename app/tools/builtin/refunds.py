from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from pydantic import Field

from app.tools import registry
from app.tools.builtin.orders import NOT_OWNED
from app.tools.business import owns_order


@tool(description='提供售后申请入口，不创建申请或执行退款；用户确认提交后仍需客服审核。')
async def submit_refund(
    order_id: Annotated[str, Field(description="要退款的订单号")],
    user_id: Annotated[str, InjectedToolArg],
    reason: Annotated[str | None, Field(description="退款原因(可选,最终以前端固定类目下拉为准)")] = None,
) -> dict:

    if not await owns_order(user_id, order_id):
        return dict(NOT_OWNED)
    return {"status": "待用户确认", "order_id": order_id}


registry.register(registry.spec_from_langchain_tool(
    submit_refund, source="builtin", inject_user_id=True))
