import asyncio
import logging
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.config import settings
from app.core import summarizer
from app.core.observability import attach_observability
from app.db import repository
from app.graph.build import build_graph

logger = logging.getLogger(__name__)


ANSWER_NODES = {"main_agent"}

DETERMINISTIC_ANSWER_NODES = {"script_reply", "complaint_reply", "fallback_reply", "cancel_reply"}

CITATION_NODES = {"retrieve_knowledge", "retrieve_policy"}

_graph = None
_locks: dict[int, asyncio.Lock] = {}
_cm = None


class ConversationNotFound(Exception):
    pass


async def init_graph() -> None:
    global _graph, _cm
    _cm = AsyncSqliteSaver.from_conn_string(settings.checkpointer_db_path)
    checkpointer = await _cm.__aenter__()
    await checkpointer.setup()
    _graph = attach_observability(build_graph(checkpointer=checkpointer))
    logger.info("图已编译,checkpointer=%s", settings.checkpointer_db_path)


async def close_graph() -> None:
    global _graph, _cm
    if _cm is not None:
        await _cm.__aexit__(None, None, None)
        _cm = None
    _graph = None
    _locks.clear()


def get_graph():
    if _graph is None:
        raise RuntimeError("图未初始化,应在 FastAPI lifespan 调 init_graph()")
    return _graph


def conversation_lock(conversation_id: int) -> asyncio.Lock:
    return _locks.setdefault(conversation_id, asyncio.Lock())


async def pending_interrupt(conversation_id: int) -> dict | None:
    snapshot = await get_graph().aget_state({"configurable": {"thread_id": str(conversation_id)}})
    for task in snapshot.tasks:
        for intr in task.interrupts:
            return {**intr.value, "interrupt_id": intr.id}
    return None


async def get_turn_snapshot(conversation_id: int) -> dict:
    config = {"configurable": {"thread_id": str(conversation_id)}}
    st = await get_graph().aget_state(config)
    values = getattr(st, "values", None) or {}
    question = ""
    for m in reversed(values.get("messages", [])):
        if getattr(m, "type", "") == "human":
            question = m.content if isinstance(m.content, str) else ""
            break
    return {"question": question, "snapshot": values.get("retrieved_snapshot") or []}


def dedup_actions(actions: list) -> list:
    seen = set()
    out = []
    for action in actions:
        t = action.get("type")
        if t in seen:
            continue
        seen.add(t)
        out.append(action)
    return out


async def _ensure_conversation(user_id: str, conversation_id: int | None) -> tuple[int, str, int]:
    if conversation_id is None:
        return await repository.create_conversation(user_id), "", 0
    conv = await repository.get_conversation(conversation_id)
    if conv is None or conv.user_id != user_id:
        raise ConversationNotFound(conversation_id)
    return conversation_id, conv.summary or "", conv.summary_upto_msg_id or 0


def _graph_input(user_id: str, message: str, cid: int, msg_id: int,
                 summary: str, summary_upto: int) -> dict:
    return {"messages": [HumanMessage(message, id=f"db-{msg_id}")], "user_id": user_id,
            "conversation_id": cid, "steps": 0, "tokens_used": 0,
            "answer": "", "suggested_actions": [], "evidence": "",
            "evidence_strong": False, "citations": [],
            "evidence_confidence": 0.0, "fallback_source": "", "retrieved_snapshot": [],
            "resolved_query": "", "intent_confidence": 0.0,
            "order_id": "", "order_data": {}, "cancelled": False,
            "summary": summary, "summary_upto_msg_id": summary_upto,
            "trace": None}


def _interrupt_payload(state: dict):
    intr = state.get("__interrupt__")
    if not intr:
        return None
    return intr[0].value


async def run_turn(user_id, message, conversation_id) -> dict:
    cid, summary, upto = await _ensure_conversation(user_id, conversation_id)
    async with conversation_lock(cid):
        if await pending_interrupt(cid):
            raise ValueError("请先确认或取消当前操作")
        msg_id = await repository.append_message(cid, "user", content=message)
        config = {"run_name": "客服咨询", "configurable": {"thread_id": str(cid)},
                  "metadata": {"thread_id": str(cid), "operation": "consultation"}}
        final = await get_graph().ainvoke(_graph_input(user_id, message, cid, msg_id, summary, upto), config)
    await summarizer.maybe_schedule_summary(cid)
    return {"conversation_id": cid, "state": final, "interrupt": _interrupt_payload(final)}


async def resume_turn(conversation_id: int, resume_value) -> dict:
    if await repository.get_conversation(conversation_id) is None:
        raise ConversationNotFound(conversation_id)
    config = {"run_name": "客服确认恢复", "configurable": {"thread_id": str(conversation_id)},
              "metadata": {"thread_id": str(conversation_id), "operation": "resume"}}
    final = await get_graph().ainvoke(Command(resume=resume_value), config)
    await summarizer.maybe_schedule_summary(conversation_id)
    return {"conversation_id": conversation_id, "state": final,
            "interrupt": _interrupt_payload(final)}


async def _stream_events(cid: int, stream_source) -> AsyncIterator[dict]:
    resuming = isinstance(stream_source, Command)
    config = {"run_name": "客服确认恢复" if resuming else "客服咨询",
              "configurable": {"thread_id": str(cid)},
              "metadata": {"thread_id": str(cid),
                           "operation": "resume" if resuming else "consultation"}}
    actions: list = []
    async for mode, chunk in get_graph().astream(
        stream_source, config, stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, meta = chunk
            if meta.get("langgraph_node") in ANSWER_NODES:
                text = msg.content if isinstance(msg.content, str) else ""
                if text:
                    yield {"type": "delta", "text": text}
        elif mode == "updates":
            if "__interrupt__" in chunk:
                payload = chunk["__interrupt__"][0].value
                ev = {"type": "interrupt", "kind": payload.get("type", ""), "conversation_id": cid}
                ev["interrupt_id"] = chunk["__interrupt__"][0].id
                for k in ("orders", "preview"):
                    if payload.get(k) is not None:
                        ev[k] = payload[k]
                yield ev
                return
            for node, upd in chunk.items():
                if not isinstance(upd, dict):
                    continue
                detail = {k: upd[k] for k in ("intent", "intent_confidence", "resolved_query", "evidence_confidence", "fallback_source") if k in upd}
                node_trace = upd.get("trace") or {}
                if node_trace.get("self_check"):
                    detail["self_check"] = str(node_trace["self_check"])[:500]
                yield {"type": "step", "name": node, "detail": detail}
                if node in DETERMINISTIC_ANSWER_NODES and upd.get("answer"):
                    yield {"type": "delta", "text": upd["answer"]}
                if node in CITATION_NODES and upd.get("citations"):
                    yield {"type": "citations", "items": upd["citations"]}
                if node == "agent_tools":
                    for m in upd.get("messages", []):
                        name = getattr(m, "name", None)
                        if name and name != "submit_refund":
                            yield {"type": "tool", "name": name}
                if upd.get("suggested_actions"):
                    actions.extend(upd["suggested_actions"])
    if actions:
        yield {"type": "actions", "items": dedup_actions(actions)}
    yield {"type": "done", "conversation_id": cid}


async def stream_turn(user_id, message, conversation_id) -> AsyncIterator[dict]:
    cid, summary, upto = await _ensure_conversation(user_id, conversation_id)
    async with conversation_lock(cid):
        if await pending_interrupt(cid):
            raise ValueError("请先确认或取消当前操作")
        msg_id = await repository.append_message(cid, "user", content=message)
        async for ev in _stream_events(cid, _graph_input(user_id, message, cid, msg_id, summary, upto)):
            yield ev
    await summarizer.maybe_schedule_summary(cid)


async def stream_resume(conversation_id: int, resume_value, interrupt_id: str | None = None) -> AsyncIterator[dict]:
    if await repository.get_conversation(conversation_id) is None:
        raise ConversationNotFound(conversation_id)
    async with conversation_lock(conversation_id):
        pending = await pending_interrupt(conversation_id)
        if not pending or pending["interrupt_id"] != interrupt_id:
            raise ValueError("待确认操作已变化，请刷新会话")
        async for ev in _stream_events(conversation_id, Command(resume=resume_value)):
            yield ev
    await summarizer.maybe_schedule_summary(conversation_id)
