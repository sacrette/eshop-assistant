import logging

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import current_user, own_conversation
from app.db.commerce import Account
from app.config import settings
from app.graph import runtime
from app.graph.nodes import resolve_answer
from app.schemas.agent import AgentRequest, AgentResponse, ToolCallView, ToolResultView

logger = logging.getLogger(__name__)
router = APIRouter()


def _views_from_state(state):
    calls, results = [], []
    for m in state.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                calls.append(ToolCallView(id=tc["id"], name=tc["name"], args=tc["args"]))
        elif isinstance(m, ToolMessage):
            results.append(ToolResultView(
                tool_call_id=m.tool_call_id, name=m.name or "", ok=(m.status != "error"),
                content=m.content))
    return calls, results


@router.post("/api/agent", response_model=AgentResponse)
async def run_agent(req: AgentRequest, user: Account = Depends(current_user)) -> AgentResponse:
    req.user_id = user.id
    if req.conversation_id is not None:
        await own_conversation(req.conversation_id, user)
        if await runtime.pending_interrupt(req.conversation_id):
            raise HTTPException(409, "请先确认或取消当前操作")
    if not (settings.chat_model and settings.chat_base_url and settings.chat_api_key):
        raise HTTPException(503, "聊天模型尚未配置，请填写后端模型设置")
    try:
        out = await runtime.run_turn(req.user_id, req.message, req.conversation_id)
    except runtime.ConversationNotFound:
        raise HTTPException(status_code=404, detail="会话不存在")
    except SQLAlchemyError:
        logger.exception("数据库错误 user_id=%s", req.user_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用,请稍后重试")
    except Exception:
        logger.exception("图编排失败 user_id=%s", req.user_id)
        raise HTTPException(status_code=502, detail="上游模型暂时不可用,请稍后重试")

    state = out["state"]
    calls, results = _views_from_state(state)
    return AgentResponse(
        conversation_id=out["conversation_id"],
        answer=resolve_answer(state),
        tool_calls=calls,
        tool_results=results,
        suggested_actions=runtime.dedup_actions(state.get("suggested_actions", [])),
        interrupt=out.get("interrupt"),
    )
