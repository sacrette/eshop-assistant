from datetime import datetime
from types import SimpleNamespace

from app.core.commerce import order_view
from app.tools.mcp_client import _fmt_logistics


def test_order_and_tool_format_logistics_time_without_mutating_source():
    trace = [{"time": "2026-10-15T18:22:08.750513", "city": "杭州", "text": "包裹已揽收"}]
    order = SimpleNamespace(id="ES20261018002", product_id="p", status="已发货",
        amount_cents=23900, created_at=datetime(2026, 10, 15), delivered_at=None,
        tracking_no="SF1", logistics=trace)
    view = order_view(order, SimpleNamespace(id="p", name="饮水机"))
    tool = _fmt_logistics({"trace": trace})
    assert view["logistics"][0]["time"] == "10月15日 18:22"
    assert tool["trace"][0]["time"] == "10月15日 18:22"
    assert trace[0]["time"] == "2026-10-15T18:22:08.750513"


def test_logistics_formatter_accepts_empty_and_unknown_times():
    result = _fmt_logistics({"trace": [{"time": "待更新"}, {"city": "上海"}]})
    assert result["trace"] == [{"time": "待更新"}, {"city": "上海"}]
    assert _fmt_logistics({})["trace"] is None
