import pytest

from app.config import settings
from app.core import rerank as rr


async def _noop_sleep(_):
    return None


@pytest.mark.parametrize("base, want", [

    ("https://api.siliconflow.cn/v1", "https://api.siliconflow.cn/v1/rerank"),
    ("https://api.siliconflow.cn/v1/", "https://api.siliconflow.cn/v1/rerank"),


    ("https://api.siliconflow.cn", "https://api.siliconflow.cn/v1/rerank"),
    ("https://api.siliconflow.cn/", "https://api.siliconflow.cn/v1/rerank"),

    ("https://api.cohere.com/v2", "https://api.cohere.com/v2/rerank"),
])
def test_rerank_url_容忍带不带版本段(monkeypatch, base, want):
    monkeypatch.setattr(settings, "rerank_base_url", base)
    assert rr._rerank_url() == want


def test_rerank_url_每次现算_不在导入时冻住(monkeypatch):

    monkeypatch.setattr(settings, "rerank_base_url", "https://a.example.com/v1")
    first = rr._rerank_url()
    monkeypatch.setattr(settings, "rerank_base_url", "https://b.example.com/v1")
    assert first != rr._rerank_url() == "https://b.example.com/v1/rerank"


@pytest.mark.asyncio
async def test_rerank_orders_and_truncates(monkeypatch):
    async def fake_post(url, json, headers, timeout):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"results": [
                    {"index": 0, "relevance_score": 0.1},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.5},
                ]}
        return R()
    monkeypatch.setattr("app.core.rerank._post", fake_post)
    out = await rr.rerank("q", ["a", "b", "c"], top_n=2)
    assert out == [(1, 0.9), (2, 0.5)]


@pytest.mark.asyncio
async def test_rerank_empty_docs():
    assert await rr.rerank("q", []) == []


async def test_断连也退避重试_不是只认状态码(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise rr.httpx.RemoteProtocolError("Server disconnected")
            return _Resp()

    monkeypatch.setattr(rr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setattr(rr.asyncio, "sleep", _noop_sleep)

    resp = await rr._post("http://x/rerank", {}, {}, 5)
    assert resp.status_code == 200
    assert calls["n"] == 2


async def test_断连重试到底仍失败就抛出去(monkeypatch):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise rr.httpx.ConnectError("connection refused")

    monkeypatch.setattr(rr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setattr(rr.asyncio, "sleep", _noop_sleep)

    with pytest.raises(rr.httpx.ConnectError):
        await rr._post("http://x/rerank", {}, {}, 5)
