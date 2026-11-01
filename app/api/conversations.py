from fastapi import APIRouter, Depends

from app.core.auth import current_user, own_conversation
from app.db.commerce import Account

from app.db import repository

router = APIRouter()


@router.get("/api/conversations")
async def list_conversations(user: Account = Depends(current_user)):
    items = await repository.list_conversations(user.id)
    return {"items": items}


@router.get("/api/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: int, user: Account = Depends(current_user)):
    await own_conversation(conversation_id, user)
    msgs = await repository.list_dialog_messages(conversation_id)
    from app.db import base as db
    from app.db.models import MessageEvidence
    from sqlalchemy import select
    async with db.async_session() as session:
        rows = (await session.scalars(select(MessageEvidence).where(
            MessageEvidence.message_id.in_([m.id for m in msgs])))).all()
    evidence = {r.message_id: r.citations for r in rows}
    return {"items": [
        {"role": m.role, "content": m.content or "",
         "citations": evidence.get(m.id, []),
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in msgs
    ]}


@router.get("/api/conversations/{conversation_id}/pending")
async def pending(conversation_id: int, user: Account = Depends(current_user)):
    await own_conversation(conversation_id, user)
    from app.graph import runtime

    snapshot = await runtime.get_graph().aget_state({"configurable": {"thread_id": str(conversation_id)}})
    values = snapshot.values or {}
    from app.core.processing import processing_view
    return {"interrupt": await runtime.pending_interrupt(conversation_id),
            "actions": values.get("suggested_actions", []),
            "processing": processing_view(values)}
