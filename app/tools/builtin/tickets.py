import asyncio
from typing import Annotated, Literal

from langchain_core.tools import InjectedToolArg, tool

from app.config import settings
from app.db import repository
from app.tools import registry


@tool(description='创建人工处理待办，必须经过用户预览确认；会话标识与幂等键由服务端注入。')
async def create_ticket(
    description: str,
    ticket_type: Literal["售后", "投诉", "咨询"],
    conversation_id: Annotated[int, InjectedToolArg],
    idempotency_key: Annotated[str, InjectedToolArg],
) -> dict:
    if settings.demo_ticket_delay_seconds > 0:
        await asyncio.sleep(settings.demo_ticket_delay_seconds)
    ticket_no = await repository.create_ticket(conversation_id, description, ticket_type, idempotency_key)
    return {"ticket_no": ticket_no, "status": "已创建人工处理待办"}


registry.register(registry.spec_from_langchain_tool(
    create_ticket, source="builtin", inject_conversation=True, inject_request_id=True))
