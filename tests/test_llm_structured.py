import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from app.core import llm


class _Check(BaseModel):
    useful: bool = Field(description="证据是否足够")
    reason: str = Field(description="一句话理由")


FC_OK = "ok"
FC_NONE = None
FC_PARSE_ERR = ValueError("Invalid JSON: arguments 被拼坏")
FC_TRANSIENT_ERR = TimeoutError("上游超时")


class _FakeModel:

    def __init__(self, fc, calls: dict):
        self.fc, self.calls = fc, calls

    def with_structured_output(self, schema, method=None):
        self.calls["methods"].append(method)

        def fc(_x):
            self.calls["function_calling"] += 1
            if isinstance(self.fc, BaseException):
                raise self.fc
            if self.fc is FC_NONE:
                return None
            return schema(useful=True, reason="function_calling")
        return RunnableLambda(fc)


@pytest.fixture
def fake(monkeypatch):
    def make(fc=FC_OK):
        calls = {"function_calling": 0, "kwargs": [], "methods": []}
        def factory(**kw):
            calls["kwargs"].append(kw)
            return _FakeModel(fc, calls)
        monkeypatch.setattr(llm, "get_chat_model", factory)
        return calls
    return make


async def test_能拿到_tool_calls_的模型一次就成(fake):
    calls = fake(FC_OK)
    r = await llm.structured(_Check, model="gpt-5.5").ainvoke("证据够不够")
    assert r.reason == "function_calling"
    assert calls["function_calling"] == 1


async def test_arguments_被拼坏时重试一次再抛给调用点(fake):


    calls = fake(FC_PARSE_ERR)
    with pytest.raises(ValueError):
        await llm.structured(_Check, model="claude-sonnet-5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2
    assert "json_mode" not in calls["methods"]


async def test_通道吃掉_tool_calls_要转成异常_不能把_None_放出去(fake):


    calls = fake(FC_NONE)
    with pytest.raises(OutputParserException):
        await llm.structured(_Check, model="claude-sonnet-5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2


def test_通道吃掉_tool_calls_同步路径也一样(fake):
    calls = fake(FC_NONE)
    with pytest.raises(OutputParserException):
        llm.structured(_Check, model="claude-sonnet-5").invoke("证据够不够")
    assert calls["function_calling"] == 2


async def test_瞬时故障也重试一次_不影响下一次调用(fake):
    calls = fake(FC_TRANSIENT_ERR)
    with pytest.raises(TimeoutError):
        await llm.structured(_Check, model="gpt-5.5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2
    with pytest.raises(TimeoutError):
        await llm.structured(_Check, model="gpt-5.5").ainvoke("再来一次")
    assert calls["function_calling"] == 4


def test_机制必须写死_function_calling_且只有这一条通路(fake):


    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5")
    assert calls["methods"] == ["function_calling"]


def test_默认开流式(fake):

    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5")
    assert calls["kwargs"][-1]["streaming"] is True
    llm.structured(_Check, model="gpt-5.5", streaming=False)
    assert calls["kwargs"][-1]["streaming"] is False


def test_裁判要的_temperature_透传到底层模型(fake):


    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5", temperature=0)
    assert calls["kwargs"][-1]["temperature"] == 0
    llm.structured(_Check, model="gpt-5.5")
    assert calls["kwargs"][-1]["temperature"] is None


def test_默认温度不变_显式传0才是0():

    assert llm.get_chat_model().temperature == 0.3
    assert llm.get_chat_model(temperature=0).temperature == 0


def test_minimax_structured_forces_non_streaming(monkeypatch):
    seen = {}

    def fake_get_chat_model(streaming=False, model=None, temperature=None):
        seen["streaming"] = streaming
        raise RuntimeError("stop-here")

    monkeypatch.setattr(llm, "get_chat_model", fake_get_chat_model)
    for name, expect in (("MiniMax-M3", False), ("deepseek-ai/DeepSeek-V4-Flash", True)):
        seen.clear()
        with pytest.raises(RuntimeError):
            llm.structured(_Check, model=name)
        assert seen["streaming"] is expect, f"{name} 的 streaming 应为 {expect}"


class _FlakyModel(_FakeModel):

    def __init__(self, misses: int, calls: dict):
        super().__init__(FC_OK, calls)
        self.misses = misses

    def with_structured_output(self, schema, method=None):
        self.calls["methods"].append(method)

        def fc(_x):
            self.calls["function_calling"] += 1
            if self.calls["function_calling"] <= self.misses:
                return None
            return schema(useful=True, reason="function_calling")
        return RunnableLambda(fc)


@pytest.fixture
def flaky(monkeypatch):
    def make(misses: int):
        calls = {"function_calling": 0, "kwargs": [], "methods": []}
        monkeypatch.setattr(llm, "get_chat_model", lambda **kw: _FlakyModel(misses, calls))
        return calls
    return make


async def test_偶发拿不到_tool_calls_重试一次就该成(flaky):
    calls = flaky(misses=1)
    r = await llm.structured(_Check, model="flaky-model").ainvoke("证据够不够")
    assert r.reason == "function_calling"
    assert calls["function_calling"] == 2


async def test_失败不留跨调用状态_下一次照样从头试(flaky):
    calls = flaky(misses=2)
    with pytest.raises(OutputParserException):
        await llm.structured(_Check, model="dead-model").ainvoke("x")
    assert calls["function_calling"] == 2

    r = await llm.structured(_Check, model="dead-model").ainvoke("x")
    assert r.reason == "function_calling"
