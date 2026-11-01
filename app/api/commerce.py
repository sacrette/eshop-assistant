from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import commerce
from app.core.auth import current_user, staff_user
from app.db.commerce import Account
from app.db import base as db, repository
from app.db.models import Conversation, Ticket
from sqlalchemy import select, update

router = APIRouter(prefix="/api/commerce", tags=["订单与售后"])


class CaseRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=32)
    reason: Literal["七天无理由", "质量问题", "发错货", "不想要了", "其他"]
    description: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=100)
    conversation_id: int | None = None


class TransitionRequest(BaseModel):
    status: Literal["approved", "rejected", "completed"]
    version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=2000)


@router.get("/orders")
async def orders(user: Account = Depends(current_user)):
    return {"items": await commerce.list_orders(user.id)}


@router.get("/cases")
async def cases(user: Account = Depends(current_user)):
    return {"items": await commerce.list_cases(user)}


@router.post("/cases")
async def submit(body: CaseRequest, user: Account = Depends(current_user)):
    return await commerce.create_case(user, body.order_id, body.reason, body.description,
                                      body.idempotency_key, body.conversation_id)


@router.get("/cases/{case_id}")
async def detail(case_id: str, user: Account = Depends(current_user)):
    return await commerce.case_detail(user, case_id)


@router.post("/cases/{case_id}/transition")
async def change(case_id: str, body: TransitionRequest, user: Account = Depends(staff_user)):
    return await commerce.transition(user, case_id, body.status, body.version, body.note)


class TicketResolution(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.get("/tickets")
async def tickets(user: Account = Depends(current_user)):
    async with db.async_session() as session:
        query = select(Ticket).join(Conversation).order_by(Ticket.created_at.desc())
        if user.role != "agent":
            query = query.where(Conversation.user_id == user.id)
        rows = (await session.scalars(query)).all()
        return {"items": [{"id": t.ticket_no, "description": t.description, "type": t.ticket_type,
                           "status": t.status, "resolution": t.resolution,
                           "conversation_id": t.conversation_id,
                           "created_at": t.created_at.isoformat()} for t in rows]}


@router.get("/tickets/{ticket_id}/messages")
async def ticket_messages(ticket_id: str, user: Account = Depends(staff_user)):
    async with db.async_session() as session:
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None:
            raise HTTPException(404, "人工待办不存在")
        rows = await repository.list_dialog_messages(ticket.conversation_id)
        return {"items": [{"role": m.role, "content": m.content or ""} for m in rows]}


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: str, body: TicketResolution, user: Account = Depends(staff_user)):
    async with db.async_session() as session:
        result = await session.execute(update(Ticket).where(Ticket.ticket_no == ticket_id,
                                       Ticket.status == "待处理").values(status="已处理", resolution=body.note))
        if result.rowcount != 1:
            raise HTTPException(409, "待办已被处理或不存在，请刷新列表")
        await session.commit()
    return {"ok": True}
