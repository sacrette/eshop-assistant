from types import SimpleNamespace

from app.config import settings
from app.core import observability


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "")
    assert not observability.langsmith_enabled()
    assert observability.get_langsmith() is None


def test_attach_returns_graph_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    graph = object()
    assert observability.attach_observability(graph) is graph
    observability.tag_intent("商品咨询", 0.9)


def test_attach_uses_explicit_langsmith_client(monkeypatch):
    calls = {}
    client = object()
    monkeypatch.setattr(observability, "get_langsmith", lambda: client)
    def tracer(**kwargs):
        calls.update(kwargs)
        return "tracer"
    monkeypatch.setattr("langchain_core.tracers.langchain.LangChainTracer", tracer)
    graph = SimpleNamespace(with_config=lambda cfg: cfg)
    result = observability.attach_observability(graph)
    assert calls == {"client": client, "project_name": settings.langsmith_project}
    assert result["callbacks"] == ["tracer"]


def test_cost_report_counts_root_runs_once():
    from scripts.cost_by_intent import collect
    runs = [SimpleNamespace(outputs={"intent": "订单"}, extra={}, total_tokens=100),
            SimpleNamespace(outputs={"intent": "订单"}, extra={}, total_tokens=50),
            SimpleNamespace(outputs={}, extra={"metadata": {"intent": "商品咨询"}}, total_tokens=200)]
    seen = {}
    def list_runs(**kwargs):
        seen.update(kwargs)
        return iter(runs)
    report = collect(SimpleNamespace(list_runs=list_runs), 7)
    assert seen["is_root"] is True
    assert report["meta"]["source"] == "LangSmith"
    assert report["total_tokens"] == 350
    assert report["total_requests"] == 3
    assert next(r for r in report["rows"] if r["intent"] == "订单")["count"] == 2


def test_tool_descriptions_and_injected_fields():
    from app.tools.registry import builtin_specs
    specs = {s.name: s for s in builtin_specs()}
    assert set(specs) == {"query_order", "query_product", "query_faq", "submit_refund", "create_ticket"}
    assert all(s.description.strip() for s in specs.values())
    assert "user_id" not in specs["query_order"].json_schema.get("properties", {})
    assert "idempotency_key" not in specs["create_ticket"].json_schema.get("properties", {})
