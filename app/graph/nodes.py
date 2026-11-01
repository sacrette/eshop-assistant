import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from app.config import settings
from app.core import coref
from app.core import intent as intent_mod
from app.core import memory
from app.core import query_understanding, retrieval, selfcheck
from app.core.confidence import compute_evidence_confidence, snapshot_from_hits
from app.core.llm import get_chat_model
from app.core.observability import tag_intent
from app.core.prompts import (
    AGENT_SYSTEM, COMPLAINT_REPLY_TEXT, FALLBACK_REPLY_TEXT,
    REFUND_JUDGE_HINT, SCRIPT_REPLY_CHITCHAT, SCRIPT_REPLY_OTHER,
)
from app.db import repository
from app.graph.routing import INTENT_TO_ROUTE
from app.tools import business, engine, registry

logger = logging.getLogger(__name__)

COMPLAINT_REPLY = COMPLAINT_REPLY_TEXT
FALLBACK_REPLY = FALLBACK_REPLY_TEXT


def _user_text(state) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return m.content or ""
    return ""


def _history_text(state, max_turns: int = 6) -> str:
    msgs = memory.build_window(state.get("messages", []),
                               state.get("summary_upto_msg_id") or 0,
                               settings.context_window_max_tokens)
    prior = msgs[:-1] if msgs else []
    lines = []
    for m in prior[-max_turns:]:
        role = "用户" if isinstance(m, HumanMessage) else "客服"
        text = m.content if isinstance(m.content, str) else ""
        if text:
            lines.append(f"{role}:{text}")
    body = "\n".join(lines)
    head = memory.summary_line(state.get("summary"))
    return f"{head}\n{body}".strip() if head else body


_ORDER_RE = re.compile(r"(?<![A-Za-z0-9])((?:ES)?\d{4,})(?!\d)")


def _extract_order_id(text: str) -> str | None:
    m = _ORDER_RE.search(text or "")
    return m.group(1) if m else None


async def fetch_order(state) -> dict:
    uid = state.get("user_id", "")
    oid = state.get("order_id") or _extract_order_id(
        state.get("resolved_query") or _user_text(state))
    while not await business.owns_order(uid, str(oid or "")):
        orders = await business.list_user_orders(uid)
        if not orders:
            return {"order_id": "", "order_data": {}, "cancelled": True}
        oid = interrupt({"type": "select_order", "orders": orders})
        if isinstance(oid, dict) and oid.get("cancelled"):
            return {"order_id": "", "order_data": {}, "cancelled": True}
    data = await business.order_snapshot(oid)
    return {"order_id": oid, "order_data": data, "cancelled": False,
            "trace": {"fetch_order": {"order_id": oid}}}


async def retrieve_policy(state) -> dict:
    base = state.get("resolved_query") or _user_text(state)
    od = state.get("order_data") or {}
    seed = f"{base} {od.get('status', '')}".strip()
    queries = await query_understanding.expand_queries(seed)

    merged: dict = {}
    for q in queries:
        for h in await retrieval.search_knowledge(q, strategy="hybrid_rerank", bm25_text=q):
            cur = merged.get(h["id"])
            if cur is None or h["rerank_score"] > cur["rerank_score"]:
                merged[h["id"]] = h
    ranked = sorted(merged.values(), key=lambda h: h["rerank_score"], reverse=True)
    arranged = retrieval.arrange_head_tail(ranked)
    citations = [
        {"n": i + 1, "id": h["id"], "section_path": h["section_path"],
         "question": h["question"], "answer": h["answer"], "content_type": h["content_type"]}
        for i, h in enumerate(arranged)
    ]
    evidence = "\n".join(f"[{c['n']}] {c['question']}: {c['answer']}" for c in citations)
    return {"evidence": evidence, "citations": citations,
            "trace": {"retrieve_policy": {"queries": queries, "hits": len(ranked)}}}


async def script_reply(state) -> dict:
    text = SCRIPT_REPLY_OTHER if state.get("intent") == "其他" else SCRIPT_REPLY_CHITCHAT
    return {"answer": text, "trace": {"route": "fallback_script"}}


async def complaint_reply(state) -> dict:
    actions = [
        {"type": "transfer_human"},
        {"type": "create_ticket",
         "draft": {"description": _user_text(state), "ticket_type": "投诉"}},
    ]
    return {"answer": COMPLAINT_REPLY, "suggested_actions": actions,
            "trace": {"route": "complaint"}}


async def fallback_reply(state) -> dict:
    source = state.get("fallback_source") or "retrieval_low_conf"
    signals = state.get("trace", {}).get("confidence_signals") or {}
    reason = (f"evidence_confidence={state.get('evidence_confidence', 0.0):.3f} "
              f"signals={json.dumps(signals, ensure_ascii=False)}")
    if source == "self_check":
        reason += f" self_check={state.get('trace', {}).get('self_check', '')}"


    walked_retrieval = bool(state.get("fallback_source"))
    snapshot = state.get("retrieved_snapshot") or ([] if walked_retrieval else None)
    await repository.insert_low_confidence(
        state.get("conversation_id"), _user_text(state), source, reason,
        retrieved_chunks=snapshot,
    )
    return {"answer": FALLBACK_REPLY,
            "suggested_actions": [{"type": "transfer_human"}],
            "trace": {"route": "fallback"}}


async def resolve_reference(state) -> dict:
    query = _user_text(state)
    history = _history_text(state)
    logger.info("history_ctx conv=%s(摘要行+滑窗,coref/意图共用)\n%s",
                state.get("conversation_id"), history or "(无历史)")
    resolved = await coref.resolve(query, history)
    mode = "rewrite" if resolved != query else "passthrough"
    return {"resolved_query": resolved, "trace": {"coref": mode}}


async def classify_intent(state) -> dict:
    query = state.get("resolved_query") or _user_text(state)
    r = await intent_mod.classify(query, _history_text(state))
    intent, conf = r["intent"], r["confidence"]
    route = INTENT_TO_ROUTE.get(intent, "business")
    tag_intent(intent, conf)
    return {"intent": intent, "intent_confidence": conf, "route": route,
            "trace": {"intent": intent, "intent_confidence": conf, "route": route}}


async def retrieve_knowledge(state) -> dict:
    query_raw = _user_text(state)
    u = await query_understanding.understand(query_raw)
    query = u["standard"]
    bm25_text = query + (" " + " ".join(u["expanded"]) if u["expanded"] else "")

    hits = await retrieval.search_knowledge(
        query, strategy="hybrid_rerank", bm25_text=bm25_text)
    conf = compute_evidence_confidence(hits)
    base = {"evidence_confidence": conf.score,
            "retrieved_snapshot": snapshot_from_hits(hits)}


    if conf.score < settings.evidence_confidence_threshold:
        return {**base, "evidence_strong": False, "fallback_source": "retrieval_low_conf",
                "trace": {"forced_rag": True, "evidence_confidence": conf.score,
                          "confidence_signals": conf.signals}}

    ev_texts = [f"{h['question']} {h['answer']}" for h in hits]
    chk = await selfcheck.check_sufficient(query, ev_texts)
    if not chk["useful"]:
        return {**base, "evidence_strong": False, "fallback_source": "self_check",
                "trace": {"forced_rag": True, "evidence_confidence": conf.score,
                          "confidence_signals": conf.signals, "self_check": chk["reason"]}}

    arranged = retrieval.arrange_head_tail(hits)
    citations = [
        {"n": i + 1, "id": h["id"], "section_path": h["section_path"],
         "question": h["question"], "answer": h["answer"], "content_type": h["content_type"]}
        for i, h in enumerate(arranged)
    ]
    evidence = "\n".join(f"[{c['n']}] {c['question']}: {c['answer']}" for c in citations)
    return {**base, "evidence_strong": True, "evidence": evidence, "citations": citations,
            "trace": {"forced_rag": True, "evidence_confidence": conf.score,
                      "confidence_signals": conf.signals}}


async def confidence_check(state) -> dict:
    decision = "strong" if state.get("evidence_strong") else "weak"
    return {"trace": {"confidence": decision}}


_KNOWLEDGE_EVIDENCE_HINT = (
    "\n\n## 已检索到的知识证据(请据此作答,每个关键结论后标注来源编号如[1];"
    "证据已给,不要再调用 query_faq;仍可按需调用订单/物流等工具)\n"
    "型号编号逐字复制证据里的写法,证据里没有的型号不要写;带条件的结论要连条件一起说。\n"
)


def _turn_context(state) -> str:
    parts = []
    ss = memory.summary_system(state.get("summary"))
    if ss is not None:
        parts.append("\n\n" + ss.content)
    if state.get("evidence"):
        parts.append(_KNOWLEDGE_EVIDENCE_HINT + state["evidence"])
    if state.get("route") == "refund_flow":
        parts.append(REFUND_JUDGE_HINT + json.dumps(state.get("order_data", {}), ensure_ascii=False))
    return "".join(parts)


TURN_CTX_ID = "turn-ctx"


def _with_turn_context(window: list, turn_ctx: str) -> list:
    msg = HumanMessage(turn_ctx, id=TURN_CTX_ID)
    for i in range(len(window) - 1, -1, -1):
        if isinstance(window[i], HumanMessage):
            return [*window[:i + 1], msg, *window[i + 1:]]
    return [*window, msg]


def _agent_messages(state) -> list:
    window = memory.build_window(state.get("messages", []),
                                 state.get("summary_upto_msg_id") or 0,
                                 settings.context_window_max_tokens)
    turn_ctx = _turn_context(state)
    if turn_ctx:
        window = _with_turn_context(window, turn_ctx)
    return [SystemMessage(AGENT_SYSTEM), *window]


def _log_model_context(state, msgs) -> None:
    from langchain_core.messages.utils import count_tokens_approximately
    ctx_block = next((m for m in msgs if getattr(m, "id", None) == TURN_CTX_ID), None)
    window = [m for m in msgs
              if not isinstance(m, SystemMessage) and getattr(m, "id", None) != TURN_CTX_ID]
    lines = []
    for m in window:
        text = m.content if isinstance(m.content, str) else ""
        lines.append(f"  [{m.type}] {text[:40]!r}")
    logger.info(
        "model_ctx conv=%s step=%s summary=%r window=%s条 本轮材料=%s tokens≈%s\n%s",
        state.get("conversation_id"), state.get("steps", 0),
        state.get("summary") or "(无)", len(window),
        f"{len(ctx_block.content)}字" if ctx_block else "无",
        count_tokens_approximately(msgs), "\n".join(lines),
    )


async def main_agent(state, config=None) -> dict:
    specs = await registry.get_all_specs()
    model = get_chat_model(streaming=True).bind_tools([s.tool for s in specs])
    msgs = _agent_messages(state)
    _log_model_context(state, msgs)
    ai: AIMessage = await model.ainvoke(msgs, config)
    usage = ai.usage_metadata or {}
    used = usage.get("total_tokens", 0)


    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    logger.info("agent_step conv=%s step=%s input=%s cache_read=%s total=%s",
                state.get("conversation_id"), state.get("steps", 0) + 1,
                usage.get("input_tokens", 0), cached, used)
    return {"messages": [ai],
            "steps": state.get("steps", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + used}


async def agent_tools(state) -> dict:
    last = state["messages"][-1]
    cid = state.get("conversation_id", 0)
    uid = state.get("user_id", "")
    specs = {s.name: s for s in await registry.get_all_specs()}


    ticket_calls = [tc for tc in last.tool_calls if tc["name"] == "create_ticket"]
    tspec = specs.get("create_ticket")
    decision = None
    if ticket_calls and tspec is not None \
            and engine.validate_args(tspec, dict(ticket_calls[0].get("args") or {})) is None:
        first_args = ticket_calls[0]["args"]
        decision = interrupt({"type": "confirm_ticket",
                              "preview": {"ticket_type": first_args.get("ticket_type", "咨询"),
                                          "description": first_args.get("description", "")}})

    tool_msgs = []
    actions = list(state.get("suggested_actions", []))
    not_owned = False
    for tc in last.tool_calls:
        if tc["name"] == "submit_refund":


            if not await business.owns_order(uid, str(tc["args"].get("order_id") or "")):
                not_owned = True
                tool_msgs.append(ToolMessage(
                    content="没有找到这位用户的这笔订单,本次不发起退款。请如实告知没查到,"
                            "并让用户从下面列出的订单里选一笔,不要再调用任何工具。",
                    tool_call_id=tc["id"], name="submit_refund", status="error"))
                continue
            actions.append({"type": "refund_form",
                            "draft": {"order_id": tc["args"].get("order_id", ""),
                                      "reason": tc["args"].get("reason")}})
            tool_msgs.append(ToolMessage(
                content="已提供售后申请入口。请说明申请仍需用户确认和人工审核，不承诺可以退款或已经退款，然后停止调用工具。",
                tool_call_id=tc["id"], name="submit_refund"))
        elif tc["name"] == "create_ticket" and decision is not None:
            if tc is ticket_calls[0]:


                if isinstance(decision, dict) and decision.get("confirmed"):
                    run = await engine.execute_tool_call(tc, cid, specs, confirmed=True,
                                                        user_id=uid)
                else:
                    run = await engine.execute_tool_call(
                        tc, cid, specs, confirmed=False, user_id=uid,
                        deny_note="用户在工单预览卡片上点了取消,本次不建单。请勿再发起,除非用户再次明确要求。")
                tool_msgs.append(run.tool_message)
            else:
                tool_msgs.append(ToolMessage(content="一次只处理一个建工单请求,本次调用已忽略。",
                                             tool_call_id=tc["id"], name="create_ticket",
                                             status="error"))
        else:

            run = await engine.execute_tool_call(tc, cid, specs, user_id=uid)
            if tc["name"] == "query_order" and not await business.owns_order(
                    uid, str((tc.get("args") or {}).get("order_id") or "")):
                not_owned = True
            tool_msgs.append(run.tool_message)

    if not_owned:
        actions.append({"type": "select_order", "orders": await business.list_user_orders(uid)})
    out = {"messages": tool_msgs}
    if actions:
        out["suggested_actions"] = actions
    return out


def resolve_answer(state) -> str:
    if state.get("answer"):
        return state["answer"]
    for m in reversed(state.get("messages", [])):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


async def log_node(state) -> dict:
    logger.info(
        "turn conv=%s intent=%s route=%s resolved=%r trace=%s",
        state.get("conversation_id"), state.get("intent"), state.get("route"),
        state.get("resolved_query"), state.get("trace", {}),
    )
    answer = resolve_answer(state)
    if state.get("conversation_id"):
        await repository.append_message(state["conversation_id"], "assistant",
                                        content=answer or None, citations=state.get("citations"))
    return {}


async def cancel_reply(state) -> dict:
    return {"answer": "已结束本次订单选择，未提交售后申请。", "suggested_actions": []}
