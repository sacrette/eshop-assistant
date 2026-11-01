import logging

from pydantic import BaseModel, Field

from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import SELF_CHECK_PROMPT

logger = logging.getLogger(__name__)


class _Check(BaseModel):
    useful: bool = Field(description="证据是否足以回答")
    reason: str = Field(default="", description="判断依据")


def _chain():
    return SELF_CHECK_PROMPT | llm.structured(_Check)


async def check_sufficient(query: str, evidence_texts: list[str]) -> dict:
    evidence = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(evidence_texts)) or "(无证据)"
    try:
        r: _Check = await _chain().ainvoke({"query": query, "evidence": evidence})
    except Exception:
        logger.warning("证据自评失败,按证据不足处理 query=%r", query, exc_info=True)
        return {"useful": False, "reason": "证据自评失败"}
    return {"useful": bool(r.useful), "reason": r.reason or ""}
