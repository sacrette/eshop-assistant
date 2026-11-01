from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import nodes
from app.graph.build import build_graph


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["1002", {"cancelled": True}])
async def test_logistics_selects_order_before_agent(monkeypatch, selection):
    monkeypatch.setattr(nodes.coref, "resolve", AsyncMock(return_value="查询我的订单物流"))
    monkeypatch.setattr(nodes.intent_mod, "classify", AsyncMock(return_value={"intent": "物流", "confidence": .9}))
    orders = [{"order_id": "1002", "product": "自动饮水机", "status": "已发货", "amount": 239}]
    monkeypatch.setattr(nodes.business, "list_user_orders", AsyncMock(return_value=orders))
    monkeypatch.setattr(nodes.business, "owns_order", AsyncMock(side_effect=lambda uid, oid: oid == "1002"))
    monkeypatch.setattr(nodes.business, "order_snapshot", AsyncMock(return_value=orders[0]))
    policy = AsyncMock(side_effect=AssertionError("物流不应检索退款政策"))
    monkeypatch.setattr(nodes, "retrieve_policy", policy)
    seen = []
    async def agent(state, config=None):
        seen.append(state)
        return {"messages": [AIMessage("物流已查询")]}
    monkeypatch.setattr(nodes, "main_agent", agent)
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "logistics"}}
    result = await graph.ainvoke({"user_id": "u1", "messages": [HumanMessage("查询我的订单物流")]}, config)
    assert result["__interrupt__"][0].value == {"type": "select_order", "orders": orders}
    assert not seen
    result = await graph.ainvoke(Command(resume=selection), config)
    if isinstance(selection, str):
        assert seen[0]["order_id"] == "1002"
        assert "1002" in nodes._turn_context(seen[0])
        assert "query_logistics" in nodes._turn_context(seen[0])
    else:
        assert not seen
        assert "物流" in result["answer"]
    policy.assert_not_awaited()
