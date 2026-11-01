from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph import nodes
from app.graph.state import ConversationState


@pytest.mark.asyncio
async def test_explicit_refund_cannot_be_routed_to_product_qa(monkeypatch):
    monkeypatch.setattr(nodes.intent_mod, "classify", AsyncMock(
        return_value={"intent": "商品咨询", "confidence": 0.95}))
    result = await nodes.classify_intent({
        "messages": [HumanMessage("我要退款 智能猫砂盆")],
        "resolved_query": "智能猫砂盆的退款政策是什么"})
    assert result["route"] == "refund_flow"


@pytest.mark.asyncio
async def test_rewritten_or_stale_order_requires_selection_and_resumes(monkeypatch):
    orders = [{"order_id": "1001", "product": "自动饮水机"},
              {"order_id": "1002", "product": "智能猫砂盆"}]
    monkeypatch.setattr(nodes.business, "owns_order", AsyncMock(return_value=True))
    monkeypatch.setattr(nodes.business, "list_user_orders", AsyncMock(return_value=orders))
    snapshot = AsyncMock(return_value=orders[1])
    monkeypatch.setattr(nodes.business, "order_snapshot", snapshot)
    builder = StateGraph(ConversationState)
    builder.add_node("fetch_order", nodes.fetch_order)
    builder.add_edge(START, "fetch_order")
    builder.add_edge("fetch_order", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "refund-selection"}}
    result = await graph.ainvoke({
        "user_id": "u1", "order_id": "1001",
        "messages": [HumanMessage("我要退款 智能猫砂盆")],
        "resolved_query": "我要退款订单1001"}, config)
    assert result["__interrupt__"][0].value == {"type": "select_order", "orders": orders}
    snapshot.assert_not_awaited()
    result = await graph.ainvoke(Command(resume="1002"), config)
    assert result["order_id"] == "1002"
    assert result["order_data"]["product"] == "智能猫砂盆"


@pytest.mark.asyncio
async def test_order_number_in_original_message_can_be_used(monkeypatch):
    monkeypatch.setattr(nodes.business, "owns_order", AsyncMock(return_value=True))
    monkeypatch.setattr(nodes.business, "order_snapshot", AsyncMock(return_value={"order_id": "1002"}))
    result = await nodes.fetch_order({"user_id": "u1",
        "messages": [HumanMessage("订单1002我要退款")], "resolved_query": "订单1001退款"})
    assert result["order_id"] == "1002"


@pytest.mark.asyncio
async def test_missing_policy_does_not_ask_model_to_invent_eligibility(monkeypatch):
    model = AsyncMock(side_effect=AssertionError("无政策时不应调用模型"))
    monkeypatch.setattr(nodes.registry, "get_all_specs", model)
    result = await nodes.main_agent({"route": "refund_flow", "evidence": "",
        "messages": [HumanMessage("我要退款")], "order_data": {"order_id": "1002"}})
    assert "无法判断" in result["messages"][0].content
    assert result["suggested_actions"] == [{"type": "transfer_human"}]
    assert not result["messages"][0].tool_calls


@pytest.mark.asyncio
async def test_missing_policy_reply_reaches_sse(monkeypatch):
    from app.graph import runtime
    builder = StateGraph(ConversationState)
    builder.add_node("main_agent", nodes.main_agent)
    builder.add_edge(START, "main_agent")
    builder.add_edge("main_agent", END)
    graph = builder.compile()
    monkeypatch.setattr(runtime, "get_graph", lambda: graph)
    events = [event async for event in runtime._stream_events(1, {
        "route": "refund_flow", "evidence": "",
        "messages": [HumanMessage("我要退款")], "order_data": {"order_id": "1002"}})]
    assert "无法判断" in "".join(e["text"] for e in events if e["type"] == "delta")
    assert any(e["type"] == "actions" and e["items"] == [{"type": "transfer_human"}] for e in events)
