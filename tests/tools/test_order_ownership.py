import pytest

from app.tools import business
from app.tools.builtin.orders import query_order
from app.tools.builtin.refunds import submit_refund

USER = "customer-lin"
OTHER = "customer-zhou"
MINE = "ES20261018001"
HIS = "ES20261018005"


async def test_owns_order_only_accepts_current_owner(commerce_demo):
    assert await business.owns_order(USER, MINE)
    assert not await business.owns_order(OTHER, MINE)


async def test_empty_identity_is_denied(commerce_demo):
    assert not await business.owns_order("", MINE)


async def test_query_owned_order(commerce_demo):
    result = await query_order.ainvoke({"order_id": MINE, "user_id": USER})
    assert result["order_id"] == MINE and result["tracking_no"]


async def test_foreign_order_does_not_leak_fields(commerce_demo):
    result = await query_order.ainvoke({"order_id": HIS, "user_id": USER})
    assert result["code"] == "order_not_owned"
    assert not {"amount", "product", "tracking_no", "status", "created_at"}.intersection(result)


async def test_missing_and_foreign_orders_have_same_response(commerce_demo):
    foreign = await query_order.ainvoke({"order_id": HIS, "user_id": USER})
    missing = await query_order.ainvoke({"order_id": "missing", "user_id": USER})
    assert foreign == missing


async def test_refund_uses_same_ownership_gate(commerce_demo):
    result = await submit_refund.ainvoke({"order_id": HIS, "reason": "不想要了", "user_id": USER})
    assert result["code"] == "order_not_owned"


@pytest.mark.parametrize("bad", ["", None])
async def test_missing_identity_denies_tool(commerce_demo, bad):
    result = await query_order.ainvoke({"order_id": MINE, "user_id": bad or ""})
    assert result["code"] == "order_not_owned"


async def test_demo_accounts_do_not_share_orders(commerce_demo):
    mine = {o["order_id"] for o in await business.list_user_orders(USER)}
    theirs = {o["order_id"] for o in await business.list_user_orders(OTHER)}
    assert mine and theirs and not mine.intersection(theirs)
