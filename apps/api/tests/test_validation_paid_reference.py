import asyncio

import pytest
from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

checkout = checkout_fixture


@pytest.mark.parametrize("identifier", [None, "   "])
def test_paid_without_reference_check_reports_missing_values(checkout, identifier):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def remove_reference():
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE orders SET payment_identifier=:identifier WHERE id=:id"),
                {"identifier": identifier, "id": order["id"]},
            )

    asyncio.run(remove_reference())
    result, findings = run_check(client, "PAID_WITHOUT_REFERENCE")

    assert result["finding_count"] == 1
    assert findings[0]["order_id"] == order["id"]
    assert findings[0]["evidence"] == {
        "status": "PAID",
        "payment_reference_missing": True,
    }
