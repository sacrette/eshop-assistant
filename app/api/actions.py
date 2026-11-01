import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.db import repository
from app.core.auth import current_user, own_conversation
from app.core.commerce import create_case
from app.db.commerce import Account
from app.graph import runtime
from app.schemas.actions import (
    CreateRefundRequest,
    CreateRefundResponse,
    CreateTicketRequest,
    CreateTicketResponse,
    ResumeRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/actions/create-ticket", response_model=CreateTicketResponse)
async def create_ticket_action(req: CreateTicketRequest, user: Account = Depends(current_user)) -> CreateTicketResponse:
    await own_conversation(req.conversation_id, user)
    try:
        ticket_no = await repository.create_ticket(
            req.conversation_id, req.description, req.ticket_type, req.idempotency_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError:
        logger.exception("建工单失败 conv=%s", req.conversation_id)
        raise HTTPException(status_code=503, detail="工单系统暂时不可用,请稍后重试")
    return CreateTicketResponse(ticket_no=ticket_no)


@router.post("/api/actions/create-refund", response_model=CreateRefundResponse)
async def create_refund_action(req: CreateRefundRequest, user: Account = Depends(current_user)) -> CreateRefundResponse:
    case = await create_case(user, req.order_id, req.reason, "", req.idempotency_key, req.conversation_id)
    return CreateRefundResponse(ticket_no=case["id"])


@router.post("/api/actions/resume")
async def resume_action(req: ResumeRequest, user: Account = Depends(current_user)):
    await own_conversation(req.conversation_id, user)
    pending = await runtime.pending_interrupt(req.conversation_id)
    if pending is None or pending["interrupt_id"] != req.interrupt_id:
        raise HTTPException(409, "待确认操作已变化，请刷新会话")
    if req.order_id is None and req.confirmed is None and not req.cancelled:
        raise HTTPException(status_code=400, detail="order_id 与 confirmed 至少传一个")
    if pending.get("type") == "select_order":
        if not req.cancelled and req.order_id not in {o["order_id"] for o in pending.get("orders", [])}:
            raise HTTPException(400, "请选择当前列表中的订单")
        resume_value = {"cancelled": True} if req.cancelled else req.order_id
    elif pending.get("type") == "confirm_ticket":
        if req.order_id is not None:
            raise HTTPException(400, "该操作需要确认或取消")
        resume_value = {"confirmed": bool(req.confirmed) and not req.cancelled}
    else:
        raise HTTPException(409, "不支持的待确认操作")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for ev in runtime.stream_resume(req.conversation_id, resume_value, req.interrupt_id):
                if ev["type"] == "step":
                    yield _sse({"event": "step", "name": ev["name"], "detail": ev["detail"]})
                elif ev["type"] == "tool":
                    yield _sse({"event": "tool", "name": ev["name"]})
                elif ev["type"] == "delta":
                    yield _sse({"delta": ev["text"]})
                elif ev["type"] == "citations":
                    yield _sse({"event": "citations", "items": ev["items"]})
                elif ev["type"] == "actions":
                    yield _sse({"event": "actions", "items": ev["items"]})
                elif ev["type"] == "interrupt":
                    yield _sse({"event": "interrupt",
                                **{k: v for k, v in ev.items() if k != "type"}})
                elif ev["type"] == "done":
                    yield _sse({"event": "done", "conversation_id": ev["conversation_id"]})
        except runtime.ConversationNotFound:
            yield "event: error\n"
            yield _sse({"message": "会话不存在"})
            return
        except Exception:
            logger.exception("续跑失败 conv=%s", req.conversation_id)
            yield "event: error\n"
            yield _sse({"message": "上游暂时不可用,请稍后重试"})
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
