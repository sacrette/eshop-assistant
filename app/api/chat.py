"""流式会话接口。

一轮对话用一个 SSE 流推给前端：步骤、工具调用、增量文本、引用、待确认操作、结束标记分别成帧。
流里的异常不会抛出成 500，而是转成 error 帧，让页面能显示具体原因；连接一旦开始就无法改状态码。
"""

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import current_user, own_conversation
from app.db.commerce import Account
from app.config import settings
from app.graph import runtime
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error(message: str) -> AsyncIterator[str]:
    yield "event: error\n"
    yield _sse({"message": message})


@router.post("/api/chat")
async def chat(req: ChatRequest, user: Account = Depends(current_user)):
    req.user_id = user.id
    if req.conversation_id is not None:
        await own_conversation(req.conversation_id, user)
        # 上一轮还停在确认态时不许插话，否则图里会出现两条并行的待确认分支。
        if await runtime.pending_interrupt(req.conversation_id):
            raise HTTPException(409, "请先确认或取消当前操作")
    if not (settings.chat_model and settings.chat_base_url and settings.chat_api_key):
        raise HTTPException(503, "聊天模型尚未配置，请填写后端模型设置")
    async def event_stream() -> AsyncIterator[str]:
        try:
            async for ev in runtime.stream_turn(req.user_id, req.message, req.conversation_id):
                if ev["type"] == "step":
                    yield _sse({"event": "step", "name": ev["name"], "detail": ev["detail"]})
                elif ev["type"] == "tool":
                    yield _sse({"event": "tool", "name": ev["name"]})
                elif ev["type"] == "delta":
                    yield _sse({"delta": ev["text"]})
                elif ev["type"] == "citations":
                    yield _sse({"event": "citations", "items": ev["items"]})
                elif ev["type"] == "interrupt":
                    yield _sse({"event": "interrupt",
                                **{k: v for k, v in ev.items() if k != "type"}})
                elif ev["type"] == "actions":
                    yield _sse({"event": "actions", "items": ev["items"]})
                elif ev["type"] == "done":
                    yield _sse({"event": "done", "conversation_id": ev["conversation_id"]})
        except runtime.ConversationNotFound:
            for f in _sse_error("会话不存在"):
                yield f
            return
        except SQLAlchemyError:
            logger.exception("数据库错误 user_id=%s", req.user_id)
            for f in _sse_error("数据库暂时不可用,请稍后重试"):
                yield f
            return
        except Exception:
            logger.exception("图编排失败 user_id=%s", req.user_id)
            for f in _sse_error("上游模型暂时不可用,请稍后重试"):
                yield f
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
