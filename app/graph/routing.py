from langchain_core.messages import AIMessage

from app.config import settings

INTENT_TO_ROUTE: dict[str, str] = {
    "投诉": "escalate",
    "闲聊": "fallback_script",
    "其他": "fallback_script",
    "商品咨询": "knowledge",
    "退款退货": "refund_flow",
    "售后": "refund_flow",
    "人工": "business",
    "物流": "business",
    "订单": "business",
}


def route_by_intent(state) -> str:
    return INTENT_TO_ROUTE.get(state.get("intent", ""), "business")


def confidence_gate(state) -> str:
    return "strong" if state.get("evidence_strong") else "weak"


def should_continue(state) -> str:
    last = state["messages"][-1]
    has_tool_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
    if not has_tool_calls:
        return "stop"
    if state.get("steps", 0) >= settings.max_agent_steps:
        return "stop"
    return "continue"
