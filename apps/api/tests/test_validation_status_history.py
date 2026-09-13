import asyncio

from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

checkout = checkout_fixture


def test_status_history_check_accepts_consistent_history(checkout):
    client, _, body, _ = checkout
    client.post("/orders", json=body, headers={"Idempotency-Key": "order"})

    result, findings = run_check(client, "INCONSISTENT_STATUS_HISTORY")

    assert result["finding_count"] == 0
    assert findings == []


def test_status_history_check_reports_latest_status_and_reason_mismatch(checkout):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def append_invalid_history():
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO order_status_history (order_id, status, reason) "
                    "VALUES (:id, 'CANCELLED', NULL)"
                ),
                {"id": order["id"]},
            )

    asyncio.run(append_invalid_history())
    result, findings = run_check(client, "INCONSISTENT_STATUS_HISTORY")

    assert result["finding_count"] == 1
    assert findings[0]["order_id"] == order["id"]
    assert findings[0]["evidence"] == {
        "current_status": "PAID",
        "latest_history_status": "CANCELLED",
        "invalid_history": True,
        "failure_reason": None,
        "history_reason": None,
    }
