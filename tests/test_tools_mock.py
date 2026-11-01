from app.tools.builtin.orders import query_order, query_product


async def test_query_order_deterministic_and_shaped(commerce_demo):
    first = await query_order.ainvoke({"order_id": "ES20261018001", "user_id": "customer-lin"})
    second = await query_order.ainvoke({"order_id": "ES20261018001", "user_id": "customer-lin"})
    assert first == second
    assert first["order_id"] == "ES20261018001"
    assert first["status"] == "已签收"
    assert first["tracking_no"].startswith("SF")


async def test_query_product_names_and_determinism(commerce_demo):
    first = await query_product.ainvoke({"product_name": "猫砂盆"})
    second = await query_product.ainvoke({"product_name": "猫砂盆"})
    assert first == second
    assert first["items"][0]["product_name"] == "智能猫砂盆 Pro"
    assert first["items"][0]["stock"] == 46
