import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import base as db, repository
from app.db.commerce import AfterSalesCase, CaseEvent, KnowledgePublication
from app.db.models import KnowledgeChunk, ReviewQueue, Ticket
from app.main import app


@pytest_asyncio.fixture
async def store(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'business.sqlite'}")
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "demo_accounts_enabled", True)
    monkeypatch.setattr(settings, "demo_password", "TestPortfolio2026!")
    from scripts.init_demo import initialize
    await initialize()
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(store):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def login(client, email="lin@eshop.demo"):
    response = await client.post("/api/auth/login", json={"email": email, "password": "TestPortfolio2026!"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["user"]


def request_body(**overrides):
    return {"order_id": "ES20261018001", "reason": "七天无理由", "description": "尺寸不合适",
            "idempotency_key": "request-unique-00001", **overrides}


@pytest.mark.asyncio
async def test_authentication_csrf_and_server_identity(client):
    assert (await client.get("/api/commerce/orders")).status_code == 401
    await login(client)
    response = await client.get("/api/commerce/orders?user_id=customer-zhou")
    assert len(response.json()["items"]) == 4
    assert "ES20261018005" not in {o["order_id"] for o in response.json()["items"]}
    csrf = client.headers.pop("X-CSRF-Token")
    assert (await client.post("/api/commerce/cases", json=request_body())).status_code == 403
    recovered = await client.get("/api/auth/csrf")
    assert recovered.json()["csrf_token"] == csrf
    client.headers["X-CSRF-Token"] = csrf
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/commerce/orders")).status_code == 401


@pytest.mark.asyncio
async def test_idempotency_conflict_and_active_order_constraint(client):
    await login(client)
    first = await client.post("/api/commerce/cases", json=request_body())
    assert first.status_code == 200, first.text
    repeat = await client.post("/api/commerce/cases", json=request_body())
    assert repeat.json()["id"] == first.json()["id"]
    assert (await client.post("/api/commerce/cases", json=request_body(reason="其他"))).status_code == 409
    assert (await client.post("/api/commerce/cases", json=request_body(idempotency_key="different-request-00002"))).status_code == 409
    async with db.async_session() as session:
        assert await session.scalar(select(func.count()).select_from(AfterSalesCase)) == 1
        assert await session.scalar(select(func.count()).select_from(CaseEvent)) == 1


@pytest.mark.asyncio
async def test_concurrent_retry_creates_one_case(client):
    await login(client)
    first, second = await asyncio.gather(
        client.post("/api/commerce/cases", json=request_body()),
        client.post("/api/commerce/cases", json=request_body()))
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_orders_cases_conversations_and_staff_are_isolated(client):
    await login(client)
    cid = await repository.create_conversation("customer-lin")
    item = (await client.post("/api/commerce/cases", json=request_body())).json()
    assert (await client.post(f'/api/commerce/cases/{item["id"]}/transition',
                             json={"status": "approved", "version": 1, "note": "无权限"})).status_code == 403
    assert (await client.get("/api/review/queue")).status_code == 403
    await login(client, "zhou@eshop.demo")
    assert (await client.get(f'/api/commerce/cases/{item["id"]}')).status_code == 404
    assert (await client.post("/api/commerce/cases", json=request_body())).status_code == 404
    assert (await client.get(f"/api/conversations/{cid}/messages")).status_code == 404
    assert (await client.get(f"/api/conversations/{cid}/pending")).status_code == 404
    assert (await client.post("/api/actions/resume", json={"conversation_id": cid, "interrupt_id": "foreign", "confirmed": True})).status_code == 404


@pytest.mark.asyncio
async def test_case_transitions_versions_and_no_false_payment_claim(client):
    await login(client)
    item = (await client.post("/api/commerce/cases", json=request_body())).json()
    await login(client, "agent@eshop.demo")
    url = f'/api/commerce/cases/{item["id"]}/transition'
    assert (await client.post(url, json={"status": "completed", "version": 1, "note": "跳过审核"})).status_code == 409
    approved = await client.post(url, json={"status": "approved", "version": 1, "note": "已核对订单"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["version"] == 2
    assert (await client.post(url, json={"status": "completed", "version": 1, "note": "过期版本"})).status_code == 409
    completed = await client.post(url, json={"status": "completed", "version": 2, "note": "已联系用户并完成处理"})
    assert completed.status_code == 200
    assert [e["action"] for e in completed.json()["events"]] == ["submitted", "approved", "completed"]
    assert completed.json()["order"]["status"] == "已签收"
    assert "payment" not in completed.json()


@pytest.mark.asyncio
async def test_expired_and_unpaid_orders_are_checked_at_submission(client):
    await login(client)
    assert (await client.post("/api/commerce/cases", json=request_body(order_id="ES20261018003"))).status_code == 409
    assert (await client.post("/api/commerce/cases", json=request_body(order_id="ES20261018004"))).status_code == 409


@pytest.mark.asyncio
async def test_mcp_ownership_gate_prevents_invocation(client):
    from app.tools.engine import execute_tool_call
    from app.tools.registry import ToolSpec
    call = AsyncMock(return_value={"ok": True})
    spec = ToolSpec(name="query_warranty", description="查询保修", source="mcp", permission="read",
                    json_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
                    tool=SimpleNamespace(ainvoke=call))
    cid = await repository.create_conversation("customer-lin")
    result = await execute_tool_call({"id": "call-1", "name": "query_warranty", "args": {"order_id": "ES20261018005"}},
                                     cid, {spec.name: spec}, user_id="customer-lin")
    assert not result.ok and result.status == "权限拒绝"
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_mixed_identifiers_cannot_bypass_gate(client):
    from app.tools.engine import execute_tool_call
    from app.tools.registry import ToolSpec
    call = AsyncMock(return_value={"ok": True})
    spec = ToolSpec(name="query_logistics", description="查询物流", source="mcp", permission="read",
                    json_schema={"type": "object"}, tool=SimpleNamespace(ainvoke=call))
    cid = await repository.create_conversation("customer-lin")
    result = await execute_tool_call({"id": "mixed-1", "name": "query_logistics", "args": {
        "order_id": "ES20261018001", "tracking_no": "SF20261018005"}},
        cid, {spec.name: spec}, user_id="customer-lin")
    assert not result.ok and result.status == "权限拒绝"
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_ticket_confirmation_replay_is_idempotent(client):
    cid = await repository.create_conversation("customer-lin")
    first = await repository.create_ticket(cid, "需要人工协助", "咨询", "call-confirmed-1")
    second = await repository.create_ticket(cid, "需要人工协助", "咨询", "call-confirmed-1")
    assert first == second
    async with db.async_session() as session:
        assert await session.scalar(select(func.count()).select_from(Ticket)) == 1


@pytest.mark.asyncio
async def test_publish_failure_retry_reuses_chunk_and_publishes_after_index(client, monkeypatch):
    from app.core.publishing import publish
    from app.kb import dualwrite
    async with db.async_session() as session:
        review = ReviewQueue(normalized_question="如何申请退货", occurrence_count=1, review_status="待审")
        session.add(review)
        await session.commit()
        rid = review.id
    monkeypatch.setattr(dualwrite, "vectorize_pending", AsyncMock(side_effect=RuntimeError("index down")))
    with pytest.raises(Exception) as exc:
        await publish(rid, "请在订单中提交售后申请")
    assert exc.value.status_code == 502
    async with db.async_session() as session:
        publication = await session.get(KnowledgePublication, rid)
        chunk_id = publication.chunk_id
        assert publication.status == "failed"
        assert (await session.get(ReviewQueue, rid)).review_status == "待审"
    async def index(**kwargs):
        assert kwargs["chunk_ids"] == [chunk_id]
        async with db.async_session() as session:
            await session.execute(update(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id).values(vectorize_status="done"))
            await session.commit()
        return 1
    monkeypatch.setattr(dualwrite, "vectorize_pending", index)
    first = await publish(rid, "请在订单中提交售后申请")
    repeated = await publish(rid, "请在订单中提交售后申请")
    assert first == repeated == {"ok": True, "chunk_ids": [chunk_id]}
    async with db.async_session() as session:
        assert await session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 1
        assert (await session.get(ReviewQueue, rid)).review_status == "通过"


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_checkpoint_survives_reopen_and_duplicate_resume_is_rejected(client, tmp_path, monkeypatch, confirmed):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt
    from app.graph import runtime

    async def confirmation(state):
        result = interrupt({"type": "confirm_ticket", "preview": {"description": "人工协助"}})
        if result.get("confirmed"):
            await repository.create_ticket(state["cid"], "人工协助", "咨询", "checkpoint-replay")
        return state
    def graph(saver):
        builder = StateGraph(dict)
        builder.add_node("confirm", confirmation)
        builder.add_edge(START, "confirm")
        builder.add_edge("confirm", END)
        return builder.compile(checkpointer=saver)
    cid = await repository.create_conversation("customer-lin")
    config = {"configurable": {"thread_id": str(cid)}}
    path = str(tmp_path / "graph.sqlite")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        first = graph(saver)
        result = await first.ainvoke({"cid": cid}, config)
        interrupt_id = result["__interrupt__"][0].id
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        monkeypatch.setattr(runtime, "_graph", graph(saver))
        await login(client)
        waiting = await client.get(f"/api/conversations/{cid}/pending")
        assert waiting.json()["interrupt"]["interrupt_id"] == interrupt_id
        body = {"conversation_id": cid, "interrupt_id": interrupt_id,
                **({"confirmed": True} if confirmed else {"cancelled": True})}
        response = await client.post("/api/actions/resume", json=body)
        assert response.status_code == 200 and "error" not in response.text, response.text
        assert (await client.post("/api/actions/resume", json=body)).status_code == 409
    async with db.async_session() as session:
        assert await session.scalar(select(func.count()).select_from(Ticket)) == (1 if confirmed else 0)


@pytest.mark.asyncio
async def test_reject_cannot_race_an_in_progress_publication(client, monkeypatch):
    from app.core.publishing import publish
    from app.kb import dualwrite
    async with db.async_session() as session:
        review = ReviewQueue(normalized_question="运费如何承担", occurrence_count=1, review_status="待审")
        session.add(review)
        await session.commit()
        rid = review.id
    indexed = asyncio.Event()
    proceed = asyncio.Event()
    async def index(**kwargs):
        indexed.set()
        await proceed.wait()
        async with db.async_session() as session:
            await session.execute(update(KnowledgeChunk).where(
                KnowledgeChunk.id.in_(kwargs["chunk_ids"])).values(vectorize_status="done"))
            await session.commit()
        return 1
    monkeypatch.setattr(dualwrite, "vectorize_pending", index)
    task = asyncio.create_task(publish(rid, "以审核后的售后政策为准"))
    try:
        await asyncio.wait_for(indexed.wait(), 3)
        await login(client, "agent@eshop.demo")
        response = await client.post(f"/api/review/{rid}/reject")
        assert response.status_code == 409
    finally:
        proceed.set()
        await task
    async with db.async_session() as session:
        assert (await session.get(ReviewQueue, rid)).review_status == "通过"
