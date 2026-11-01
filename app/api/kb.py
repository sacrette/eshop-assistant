import datetime as dt
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import retrieval
from app.db import repository
from app.kb import chunking, dedup, documents, dualwrite, milvus_client
from app.kb.sources import CONTENT_TYPE_DESC, CONTENT_TYPES, KB_DIR, SOURCE_TYPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb")

MAX_TEXT_CHARS = 40000
STRATEGIES = ("vector", "bm25", "hybrid", "hybrid_rerank")


def _fingerprint(questions: str, answer: str) -> str:
    return dedup.normalize_question(questions) + "|" + dedup.normalize_question(answer)


def _chunk_view(seq: int, c: documents.Chunk, dup: bool | None) -> dict:
    return {
        "seq": seq,
        "section_path": c.section_path or "(无标题层级)",
        "category": c.category,
        "questions": c.questions,
        "answer": c.answer,
        "chars": len(c.answer),
        "is_key_clause": bool(c.is_key_clause),
        "is_table": chunking.is_table_block(c.answer),
        "duplicate": dup,
    }


def _features(chunks: list[documents.Chunk]) -> dict:
    groups: dict[str, list[documents.Chunk]] = {}
    for c in chunks:
        groups.setdefault(c.section_path, []).append(c)
    table_split = any(len(g) > 1 and chunking.is_table_block(g[0].answer) for g in groups.values())
    overlap = any(len(g) > 1 and not chunking.is_table_block(g[0].answer) for g in groups.values())
    return {
        "sections": len(groups),
        "table_split": table_split,
        "overlap": overlap,
        "multi_piece_sections": [p for p, g in groups.items() if len(g) > 1],
    }


async def _existing_fingerprints() -> set[str] | None:
    try:
        return {_fingerprint(q, a) for q, a in await repository.list_chunk_pairs()}
    except Exception:
        return None


async def milvus_state() -> dict:
    try:
        def work():
            c = milvus_client.get_client()
            milvus_client.ensure_collection(c)
            return milvus_client.count(c)
        return {"online": True, "count": await milvus_client.acall(work),
                "collection": milvus_client.COLLECTION}
    except Exception as e:
        return {"online": False, "count": None, "detail": f"{type(e).__name__}: {e}"}


def _sources() -> list[dict]:
    out = []
    for fname, ctype in SOURCE_TYPES.items():
        path = KB_DIR / fname
        item = {"file": fname, "content_type": ctype, "present": path.exists(),
                "path": f"data/kb/{fname}"}
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            chunks = documents.build_chunks(raw, content_type=ctype)
            st = path.stat()
            item.update({
                "chars": len(raw), "lines": raw.count("\n") + 1,
                "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "chunks": len(chunks),
                "key_clause": sum(c.is_key_clause for c in chunks),
                "features": _features(chunks),
            })
        out.append(item)
    return out


@router.get("/overview")
async def overview() -> dict:
    milvus = await milvus_state()
    try:
        stats = await repository.knowledge_stats()
        recent = [{"id": r.id, "questions": r.questions, "answer": r.answer[:120],
                   "category": r.category, "section_path": r.section_path,
                   "content_type": r.content_type, "is_key_clause": bool(r.is_key_clause),
                   "status": r.vectorize_status,
                   "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None}
                  for r in await repository.list_recent_chunks(12)]
        staging = await repository.staging_stats()
        db_err = None
    except Exception as e:
        stats = {"total": None, "pending": None, "done": None,
                 "by_content_type": {}, "key_clause": None}
        recent, staging, db_err = [], None, f"{type(e).__name__}: {e}"


    consistent = None
    if db_err is None and milvus["online"]:
        consistent = stats["pending"] == 0 and stats["done"] == milvus["count"]

    return {
        "chunks": stats, "recent": recent, "staging": staging, "db_error": db_err,
        "milvus": milvus, "consistent": consistent,
        "sources": _sources(),
        "content_types": [{"key": k, "desc": CONTENT_TYPE_DESC[k]} for k in CONTENT_TYPES],
    }


class PreviewIn(BaseModel):
    text: str | None = None
    file: str | None = None
    content_type: str = "faq"


def _resolve_preview(body: PreviewIn) -> tuple[str, str, str]:
    if body.file:
        if body.file not in SOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"不在建库材料清单里:{body.file}")
        path = KB_DIR / body.file
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"材料文件不存在:data/kb/{body.file}")
        return path.read_text(encoding="utf-8"), SOURCE_TYPES[body.file], f"data/kb/{body.file}"
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="正文是空的,贴一段 Markdown 再预览")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"正文 {len(text)} 字,超过单次上限 {MAX_TEXT_CHARS} 字,拆开录")
    if body.content_type not in CONTENT_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"content_type 只能是 {'/'.join(CONTENT_TYPES)}")
    return text, body.content_type, "手工录入"


@router.post("/preview")
async def preview(body: PreviewIn) -> dict:
    text, ctype, source = _resolve_preview(body)
    chunks = documents.build_chunks(text, content_type=ctype)
    seen = await _existing_fingerprints()
    views, dups, batch = [], 0, set()
    for i, c in enumerate(chunks, 1):
        fp = _fingerprint(c.questions, c.answer)
        dup = None if seen is None else (fp in seen or fp in batch)
        dups += bool(dup)
        batch.add(fp)
        views.append(_chunk_view(i, c, dup))
    return {"source": source, "content_type": ctype, "chars": len(text),
            "total": len(chunks), "duplicates": dups,
            "key_clause": sum(c.is_key_clause for c in chunks),
            "features": _features(chunks), "chunks": views,
            "dedup_known": seen is not None}


class IngestIn(BaseModel):
    text: str
    content_type: str = "faq"
    vectorize: bool = True


@router.post("/ingest")
async def ingest(body: IngestIn) -> dict:
    text, ctype, _ = _resolve_preview(PreviewIn(text=body.text, content_type=body.content_type))
    chunks = documents.build_chunks(text, content_type=ctype)
    if not chunks:
        raise HTTPException(status_code=400, detail="这段正文切不出块,检查是不是只有标题没有正文")
    seen = await _existing_fingerprints()
    if seen is None:
        raise HTTPException(status_code=503, detail="连不上 MySQL,录入这条路走不通(查重与落库都要它)")

    kept, skipped = [], []
    for c in chunks:
        fp = _fingerprint(c.questions, c.answer)
        if fp in seen:
            skipped.append({"questions": c.questions, "answer": c.answer[:80]})
            continue
        seen.add(fp)
        kept.append(c)

    ids = await dualwrite.write_pending(kept) if kept else []
    vectorized = None
    if body.vectorize and ids:
        try:
            vectorized = await dualwrite.vectorize_pending()
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=(f"已入库 {len(ids)} 块(pending),向量化失败:{type(e).__name__}: {e}。"
                        "修好嵌入服务后按「向量化待补块」补齐,不必重录")) from e
    return {"content_type": ctype, "chunks": len(chunks), "inserted": len(ids),
            "skipped": len(skipped), "skipped_samples": skipped[:5], "ids": ids,
            "vectorized": vectorized, "milvus": await milvus_state(),
            "chunk_stats": await repository.knowledge_stats()}


@router.post("/vectorize")
async def vectorize() -> dict:
    try:
        n = await dualwrite.vectorize_pending()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"向量化失败:{type(e).__name__}: {e}") from e
    return {"vectorized": n, "chunk_stats": await repository.knowledge_stats(),
            "milvus": await milvus_state()}


class SearchIn(BaseModel):
    q: str
    strategy: str = "vector"
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/search")
async def search(body: SearchIn) -> dict:
    q = body.q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="问一句话再检索")
    if body.strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail=f"strategy 只能是 {'/'.join(STRATEGIES)}")
    try:
        hits = await retrieval.search_knowledge(q, strategy=body.strategy, top_k=body.top_k)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"检索失败({type(e).__name__}: {e});嵌入上游与 Milvus 都要在") from e
    return {"q": q, "strategy": body.strategy, "top_k": body.top_k,
            "hits": [{"id": h.get("id"), "question": h.get("question"),
                      "answer": h.get("answer"), "score": h.get("score"),
                      "rerank_score": h.get("rerank_score"),
                      "section_path": h.get("section_path"),
                      "content_type": h.get("content_type"),
                      "category": h.get("category")} for h in hits]}


@router.get("/staging")
async def staging(limit: int = 30) -> dict:
    stats = await repository.staging_stats()
    rows = {}
    for st in ("extracted", "kept", "discarded", "approved", "rejected"):
        rows[st] = [{"id": r.id, "batch_no": r.batch_no, "source_ref": r.source_ref,
                     "question": r.question, "answer": r.answer[:160]}
                    for r in (await repository.list_staging_by_status(st))[:limit]]
    return {"stats": stats, "rows": rows}


class StagingReviewIn(BaseModel):
    ids: list[int] = Field(min_length=1, description="要处理的暂存行 id")


@router.post("/staging/approve")
async def staging_approve(body: StagingReviewIn) -> dict:
    rows = await repository.list_staging_by_ids(body.ids, status="kept")
    if not rows:
        raise HTTPException(status_code=409, detail="这些行不在待审状态(可能已被处理过)")

    chunks = [documents.Chunk(category="历史对话", questions=r.question, answer=r.answer,
                              section_path="mined", content_type="mined",
                              is_key_clause=documents.is_key(r.question, r.answer))
              for r in rows]
    ids: list[int] = []
    try:
        ids = await dualwrite.write_pending(chunks)
        await dualwrite.vectorize_pending()
    except Exception as e:
        logger.exception("采纳写回知识库失败 staging=%s(状态不变,可重试)", [r.id for r in rows])
        if ids:
            try:
                await repository.delete_knowledge_chunks(ids)
            except Exception:
                logger.exception("回滚 pending chunk 失败 ids=%s(需人工清理)", ids)
        raise HTTPException(
            status_code=502,
            detail=f"写回知识库失败({type(e).__name__}),这几条仍是待审,修好嵌入/Milvus 再点一次") from e

    await repository.set_staging_status([r.id for r in rows], "approved")
    logger.info("挖知识人工采纳 staging=%s → knowledge_chunks %s", [r.id for r in rows], ids)
    return {"approved": len(rows), "chunk_ids": ids}


@router.post("/staging/reject")
async def staging_reject(body: StagingReviewIn) -> dict:
    rows = await repository.list_staging_by_ids(body.ids, status="kept")
    if not rows:
        raise HTTPException(status_code=409, detail="这些行不在待审状态(可能已被处理过)")
    await repository.set_staging_status([r.id for r in rows], "rejected")
    return {"rejected": len(rows)}
