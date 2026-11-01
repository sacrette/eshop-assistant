import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.core.auth import now
from app.db import base as db
from app.db.commerce import KnowledgePublication
from app.db.models import KnowledgeChunk, ReviewQueue
from app.kb import dualwrite
from app.kb.documents import is_key

logger = logging.getLogger(__name__)


async def publication_view(review_id: int) -> dict | None:
    async with db.async_session() as session:
        row = await session.get(KnowledgePublication, review_id)
        return {"status": row.status, "answer": row.answer, "error": row.error} if row else None


async def publish(review_id: int, answer: str) -> dict:
    token = uuid4().hex
    async with db.async_session() as session:
        review = await session.get(ReviewQueue, review_id, with_for_update=True)
        if review is None:
            raise HTTPException(404, "问题不存在")
        if review.review_status == "待审":
            guard = await session.execute(update(ReviewQueue).where(
                ReviewQueue.id == review_id, ReviewQueue.review_status == "待审"
            ).values(review_status="待审"))
            if guard.rowcount != 1:
                raise HTTPException(409, "审核状态已变化，请刷新状态")
        row = await session.get(KnowledgePublication, review_id)
        if row and row.status == "published":
            if row.answer != answer:
                raise HTTPException(409, "该问题已经发布，不能通过重试修改答案")
            return {"ok": True, "chunk_ids": [row.chunk_id]}
        if review.review_status != "待审":
            raise HTTPException(409, "仅待审问题可以发布")
        if row is None:
            chunk = KnowledgeChunk(category="审核补全", questions=review.normalized_question,
                                   answer=answer, section_path=f"审核补全 / {review.normalized_question}",
                                   content_type="faq", is_key_clause=int(is_key(review.normalized_question, answer)),
                                   vectorize_status="pending")
            session.add(chunk)
            await session.flush()
            session.add(KnowledgePublication(review_id=review_id, chunk_id=chunk.id,
                                             answer=answer, status="pending"))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise HTTPException(409, "该问题正在被另一位审核者处理，请刷新")
            row = await session.get(KnowledgePublication, review_id)
        if row.answer != answer:
            raise HTTPException(409, "已有未完成的发布，请使用原审核答案重试")
        claim = await session.execute(update(KnowledgePublication).where(
            KnowledgePublication.review_id == review_id,
            KnowledgePublication.status != "published",
            or_(KnowledgePublication.lease_until.is_(None), KnowledgePublication.lease_until < now())
        ).values(status="indexing", lease_token=token, lease_until=now() + timedelta(minutes=5), error=None))
        if claim.rowcount != 1:
            raise HTTPException(409, "知识正在索引，请稍后刷新")
        chunk_id = row.chunk_id
        await session.commit()
    try:
        await dualwrite.vectorize_pending(chunk_ids=[chunk_id])
        async with db.async_session() as session:
            chunk = await session.get(KnowledgeChunk, chunk_id)
            if chunk is None or chunk.vectorize_status != "done":
                raise RuntimeError("知识索引未完成")
            done = await session.execute(update(KnowledgePublication).where(
                KnowledgePublication.review_id == review_id, KnowledgePublication.lease_token == token
            ).values(status="published", lease_token=None, lease_until=None))
            if done.rowcount != 1:
                raise HTTPException(409, "发布租约已变化，请刷新状态")
            updated = await session.execute(update(ReviewQueue).where(
                ReviewQueue.id == review_id, ReviewQueue.review_status == "待审"
            ).values(review_status="通过", approved_answer=answer))
            if updated.rowcount != 1:
                raise HTTPException(409, "审核状态已变化，请刷新状态")
            await session.commit()
        return {"ok": True, "chunk_ids": [chunk_id]}
    except Exception as exc:
        logger.warning("知识发布索引失败 review=%s", review_id, exc_info=True)
        async with db.async_session() as session:
            owned = await session.execute(update(KnowledgePublication).where(
                KnowledgePublication.review_id == review_id, KnowledgePublication.lease_token == token
            ).values(status="failed", error=type(exc).__name__, lease_token=None, lease_until=None))
            if owned.rowcount:
                await session.execute(update(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
                                      .values(vectorize_status="pending"))
            await session.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, "索引失败，审核状态未变；请检查嵌入与检索服务后使用相同答案重试") from exc
