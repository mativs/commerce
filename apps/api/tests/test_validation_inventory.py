import asyncio

from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

checkout = checkout_fixture


def test_inventory_check_accepts_matching_reservations(checkout):
    client, _, body, _ = checkout
    client.post("/orders", json=body, headers={"Idempotency-Key": "order"})

    result, findings = run_check(client, "INVENTORY_RESERVATION_MISMATCH")

    assert result["finding_count"] == 0
    assert findings == []


def test_inventory_check_reports_each_product_mismatch(checkout):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def corrupt_reservations():
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE stock SET reserved=0 WHERE warehouse_id=:warehouse_id"),
                {"warehouse_id": order["warehouse_id"]},
            )

    asyncio.run(corrupt_reservations())
    result, findings = run_check(client, "INVENTORY_RESERVATION_MISMATCH")

    assert result["finding_count"] == 2
    assert {finding["product_id"] for finding in findings} == {
        item["product_id"] for item in order["items"]
    }
    assert all(
        finding["evidence"] == {"expected": 2, "actual": 0, "stock_row_missing": False}
        for finding in findings
    )
