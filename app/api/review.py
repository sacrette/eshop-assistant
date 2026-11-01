import logging

from fastapi import APIRouter, HTTPException

from app.db import repository
from app.kb import dualwrite
from app.kb.documents import Chunk, is_key
from app.schemas.review import ApproveRequest

logger = logging.getLogger(__name__)
router = APIRouter()


async def _write_chunks(chunks: list[Chunk]) -> list[int]:
    return await dualwrite.write_pending(chunks)


async def _vectorize() -> int:
    return await dualwrite.vectorize_pending()


def _item_out(r) -> dict:
    return {"id": r.id, "normalized_question": r.normalized_question,
            "ai_suggested_answer": r.ai_suggested_answer,
            "occurrence_count": r.occurrence_count, "review_status": r.review_status,
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/api/review/queue")
async def review_queue(status: str | None = None) -> dict:
    rows = await repository.list_review_queue(status)
    return {"items": [_item_out(r) for r in rows]}


@router.get("/api/review/pool")
async def problem_pool() -> dict:
    rows = await repository.fetch_unmatched_low_conf(200)
    return {"items": [{"id": r.id, "raw_question": r.raw_question,
                       "source": r.source, "reason": r.reason,
                       "conversation_id": r.conversation_id,
                       "created_at": r.created_at.isoformat() if r.created_at else None,
                       "retrieved_chunks": r.retrieved_chunks} for r in rows],
            "limit": 200}


@router.get("/api/review/{review_id}")
async def review_detail(review_id: int) -> dict:
    detail = await repository.get_review_detail(review_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="缺口不存在")
    item, raws = detail
    out = _item_out(item)
    from app.core.publishing import publication_view
    out["publication"] = await publication_view(review_id)
    out["approved_answer"] = item.approved_answer
    out["raws"] = [{"raw_question": r.raw_question, "source": r.source, "reason": r.reason,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "retrieved_chunks": r.retrieved_chunks}
                   for r in raws]
    return out


@router.post("/api/review/{review_id}/approve")
async def approve(review_id: int, req: ApproveRequest) -> dict:
    from app.core.publishing import publish
    answer = req.approved_answer.strip()
    if not answer:
        raise HTTPException(422, "审核答案不能为空")
    return await publish(review_id, answer)


@router.post("/api/review/{review_id}/reject")
async def reject(review_id: int) -> dict:
    from app.db import base as db
    from app.db.commerce import KnowledgePublication
    from app.db.models import ReviewQueue
    from app.core.auth import now
    from sqlalchemy import update

    async with db.async_session() as session:
        guard = await session.execute(update(ReviewQueue).where(
            ReviewQueue.id == review_id, ReviewQueue.review_status == "待审").values(review_status="待审"))
        if guard.rowcount != 1:
            raise HTTPException(409, "仅待审问题可驳回")
        publication = await session.get(KnowledgePublication, review_id)
        if publication is not None:
            raise HTTPException(409, "该问题已有发布记录，请完成发布或处理索引失败后再操作")
        result = await session.execute(update(ReviewQueue).where(
            ReviewQueue.id == review_id, ReviewQueue.review_status == "待审").values(review_status="驳回"))
        if result.rowcount != 1:
            raise HTTPException(409, "仅待审问题可驳回")
        await session.commit()
    return {"ok": True}


@router.post("/api/review/process-pool")
async def process_pool() -> dict:
    from app.config import settings
    from app.core.flywheel import process_pending
    if not (settings.chat_model and settings.chat_api_key and settings.chat_base_url):
        raise HTTPException(503, "问题整理模型尚未配置")
    return await process_pending()
