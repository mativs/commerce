import asyncio

from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

checkout = checkout_fixture


def test_order_structure_check_accepts_complete_order(checkout):
    client, _, body, _ = checkout
    client.post("/orders", json=body, headers={"Idempotency-Key": "order"})

    result, findings = run_check(client, "INVALID_ORDER_STRUCTURE")

    assert result["finding_count"] == 0
    assert findings == []


def test_order_structure_check_reports_missing_items_and_coordinates(checkout):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def corrupt_structure():
        async with sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM order_items WHERE order_id=:id"), {"id": order["id"]}
            )
            await session.execute(
                text("UPDATE orders SET latitude=NULL, longitude=NULL WHERE id=:id"),
                {"id": order["id"]},
            )

    asyncio.run(corrupt_structure())
    result, findings = run_check(client, "INVALID_ORDER_STRUCTURE")

    assert result["finding_count"] == 1
    assert findings[0]["order_id"] == order["id"]
    assert findings[0]["evidence"] == {
        "empty_items": True,
        "missing_warehouse": False,
        "missing_coordinates": True,
        "invalid_items": False,
    }
