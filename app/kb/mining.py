import logging
from datetime import datetime

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.core.llm import get_chat_model
from app.core.prompts import MINING_PROMPT
from app.db import repository
from app.kb import dedup


class QaPair(BaseModel):
    question: str
    answer: str


class QaExtraction(BaseModel):

    questions: list[str] = Field(
        default_factory=list, description="问法列表,与 answers 一一对应;无可复用问答则为空"
    )
    answers: list[str] = Field(
        default_factory=list, description="答案列表,与 questions 一一对应"
    )


async def extract_qa(conversation_texts: list[str], model=None) -> list[QaPair]:
    model = model or get_chat_model()
    chain = MINING_PROMPT | model.with_structured_output(QaExtraction)
    result: QaExtraction = await chain.ainvoke(
        {"conversations": "\n---\n".join(conversation_texts)}
    )
    qs, ans = result.questions, result.answers
    if len(qs) != len(ans):

        logger.warning("挖知识并列数组长度不一致 questions=%d answers=%d,按较短对齐", len(qs), len(ans))
    n = min(len(qs), len(ans))
    return [QaPair(question=qs[i], answer=ans[i]) for i in range(n)]


async def _load_conversation_texts() -> list[tuple[str, str]]:
    convs = await repository.list_conversations_with_messages()
    out: list[tuple[str, str]] = []
    for conv_id, msgs in convs:
        lines = [f"{m.role}: {m.content}" for m in msgs if m.content]
        if lines:
            out.append((f"conv:{conv_id}", "\n".join(lines)))
    return out


async def mine(batch_size: int = 20, model=None) -> dict:
    sources = await _load_conversation_texts()
    batch_no = datetime.now().strftime("mine-%Y%m%d%H%M%S")

    for start in range(0, len(sources), batch_size):
        batch = sources[start:start + batch_size]
        pairs = await extract_qa([t for _, t in batch], model=model)
        for p in pairs:
            await repository.insert_staging(batch_no, batch[0][0], p.question, p.answer)

    staged = [s for s in await repository.list_staging_by_status("extracted") if s.batch_no == batch_no]
    existing = await repository.list_all_questions()
    kept, discarded = dedup.dedupe(staged, existing)
    await repository.set_staging_status([s.id for s in kept], "kept")
    await repository.set_staging_status([s.id for s in discarded], "discarded")

    return {"sources": len(sources), "extracted": len(staged),
            "kept": len(kept), "discarded": len(discarded)}
