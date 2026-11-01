from langchain_core.messages import HumanMessage

from app.core.prompts import CUSTOMER_SERVICE_PROMPT, AGENT_SYSTEM, AGENT_PROMPT


def test_customer_service_prompt_renders_with_history():
    msgs = CUSTOMER_SERVICE_PROMPT.format_messages(
        history=[HumanMessage("你们卖猫粮吗?")]
    )
    assert msgs[0].type == "system"
    assert msgs[-1].content == "你们卖猫粮吗?"

    for keyword in ("客服", "不", "订单"):
        assert keyword in msgs[0].content


def test_agent_system_covers_tool_principles():
    for kw in ["小喵", "工具", "query_faq", "create_ticket", "不要臆造"]:
        assert kw in AGENT_SYSTEM


def test_agent_prompt_has_history_placeholder():
    assert any(getattr(m, "variable_name", None) == "history"
               for m in AGENT_PROMPT.messages)
