import asyncio

from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

checkout = checkout_fixture


def test_order_total_check_accepts_matching_total(checkout):
    client, _, body, _ = checkout
    client.post("/orders", json=body, headers={"Idempotency-Key": "order"})

    result, findings = run_check(client, "ORDER_TOTAL_MISMATCH")

    assert result["finding_count"] == 0
    assert findings == []


def test_order_total_check_reports_mismatch_with_both_totals(checkout):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def corrupt_total():
        async with sessions() as session, session.begin():
            await session.execute(text("UPDATE orders SET total_amount=1 WHERE id=:id"), order)

    asyncio.run(corrupt_total())
    result, findings = run_check(client, "ORDER_TOTAL_MISMATCH", key="mismatch")

    assert result["finding_count"] == 1
    assert findings[0]["order_id"] == order["id"]
    assert findings[0]["evidence"] == {"expected": "49.36", "actual": "1.00"}
