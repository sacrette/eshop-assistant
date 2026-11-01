from app.config import settings
from app.core.llm import _thinking_kwargs, get_chat_model


def test_factory_points_to_chat_upstream():
    m = get_chat_model()
    assert m.model_name == settings.chat_model

    assert str(m.openai_api_base) == settings.chat_base_url


def test_factory_streaming_flag():
    assert get_chat_model(streaming=True).streaming is True


def test_思考链三项留空就一个都不传(monkeypatch):

    for k in ("chat_thinking", "chat_reasoning_effort", "chat_reasoning_split"):
        monkeypatch.setattr(settings, k, "")
    assert _thinking_kwargs() == {}


def test_关思考链走_extra_body(monkeypatch):

    monkeypatch.setattr(settings, "chat_thinking", "disabled")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    monkeypatch.setattr(settings, "chat_reasoning_split", "")
    assert _thinking_kwargs() == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_effort_是标准字段_不进_extra_body(monkeypatch):
    monkeypatch.setattr(settings, "chat_thinking", "adaptive")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "high")
    monkeypatch.setattr(settings, "chat_reasoning_split", "true")
    kw = _thinking_kwargs()
    assert kw["reasoning_effort"] == "high"
    assert kw["extra_body"]["thinking"] == {"type": "adaptive"}
    assert kw["extra_body"]["reasoning_split"] is True


def test_reasoning_split_认常见的几种真值写法(monkeypatch):


    monkeypatch.setattr(settings, "chat_thinking", "")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    for v in ("true", "True", "1", "yes", "on", " TRUE "):
        monkeypatch.setattr(settings, "chat_reasoning_split", v)
        assert _thinking_kwargs()["extra_body"]["reasoning_split"] is True, v
    for v in ("false", "0", "no", "off"):
        monkeypatch.setattr(settings, "chat_reasoning_split", v)
        assert _thinking_kwargs()["extra_body"]["reasoning_split"] is False, v


def test_配置真的落到模型上(monkeypatch):

    monkeypatch.setattr(settings, "chat_thinking", "disabled")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    monkeypatch.setattr(settings, "chat_reasoning_split", "")
    m = get_chat_model()
    assert m.extra_body == {"thinking": {"type": "disabled"}}
