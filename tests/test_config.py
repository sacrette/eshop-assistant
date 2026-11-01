import pytest
from pydantic import ValidationError

from app.config import Settings


_REQUIRED = {
    "CHAT_MODEL": "deepseek-ai/DeepSeek-V4-Flash",
    "CHAT_BASE_URL": "https://api.siliconflow.cn/v1",
    "CHAT_API_KEY": "sk-test",
    "EMBED_API_KEY": "sk-test",
    "RERANK_API_KEY": "sk-test",
}


def _fill(monkeypatch, skip=None):
    for k, v in _REQUIRED.items():
        if k == skip:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


@pytest.mark.parametrize("missing", sorted(_REQUIRED))
def test_账号相关的配置都必填(monkeypatch, missing):
    _fill(monkeypatch, skip=missing)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_嵌入与重排的地址有默认值_只要填_key(monkeypatch):
    _fill(monkeypatch)
    s = Settings(_env_file=None)
    assert s.embed_base_url == "https://api.siliconflow.cn/v1"
    assert s.rerank_base_url == "https://api.siliconflow.cn/v1"


def test_settings_defaults(monkeypatch):

    _fill(monkeypatch)
    s = Settings(_env_file=None)
    assert s.token_budget == 2000
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"


def test_settings_env_override(monkeypatch):
    _fill(monkeypatch)
    monkeypatch.setenv("TOKEN_BUDGET", "500")
    assert Settings(_env_file=None).token_budget == 500
