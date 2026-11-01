from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_dict(a: dict | None, b: dict | None) -> dict:
    if b is None:
        return {}
    return {**(a or {}), **b}


class ConversationState(TypedDict, total=False):
    cancelled: bool
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str
    summary_upto_msg_id: int
    user_id: str
    conversation_id: int
    intent: str
    resolved_query: str
    intent_confidence: float
    order_id: str
    order_data: dict
    route: str
    evidence: str
    citations: list
    evidence_strong: bool
    evidence_confidence: float
    fallback_source: str
    retrieved_snapshot: list
    answer: str
    steps: int
    tokens_used: int
    suggested_actions: list
    trace: Annotated[dict, merge_dict]
