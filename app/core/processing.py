import re

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _safe(value) -> str:
    text = str(value)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    return text[:500]


def processing_view(values: dict) -> dict:
    trace = values.get("trace") or {}
    calls, results = {}, []
    for message in values.get("messages", []):
        if isinstance(message, HumanMessage):
            calls, results = {}, []
        elif isinstance(message, AIMessage):
            for call in message.tool_calls:
                calls[call["id"]] = {key: _safe(value) for key, value in call.get("args", {}).items()
                                     if key in {"order_id", "product_name", "tracking_no", "query", "question"}}
        elif isinstance(message, ToolMessage):
            results.append({"name": message.name or "工具", "ok": message.status != "error",
                            "arguments": calls.get(message.tool_call_id, {}),
                            "result": _safe(message.content)})
    fallback = values.get("fallback_source")
    if fallback == "self_check":
        decision = "检索结果通过分数门槛，但证据自评未通过；进入拒答兜底并收集知识缺口。"
    elif fallback:
        decision = "检索证据置信度未达到门槛；进入拒答兜底并收集知识缺口。"
    elif values.get("evidence_strong"):
        decision = "证据门控通过，将知识材料交给回答节点；正文标注实际使用的引用。"
    elif values.get("route") == "order":
        decision = "进入订单业务流程，具体结果以工具返回和用户确认状态为准。"
    else:
        decision = "根据识别意图执行相应处理路径，具体执行结果见下方记录。"
    return {
        **{key: values[key] for key in ("intent", "intent_confidence", "resolved_query", "route",
                                       "evidence_confidence", "fallback_source") if key in values},
        "confidence_signals": trace.get("confidence_signals") or {},
        "evidence_passed": bool(values.get("evidence_strong")),
        "self_check_reason": _safe(trace.get("self_check") or ""),
        "retrieved_snapshot": values.get("retrieved_snapshot") or [],
        "tools": results,
        "decision": decision,
    }
