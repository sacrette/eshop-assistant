import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s1", message="")


