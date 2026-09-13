import asyncio

from order_validation_test_helpers import run_check
from sqlalchemy import text
from test_orders import checkout as checkout_fixture

from app.application.ports.payment import PaymentUnavailable

checkout = checkout_fixture


def test_stale_order_check_distinguishes_fresh_and_old_payment_states(checkout):
    client, sessions, body, _ = checkout
    client.app.state.payment_gateway.charge.side_effect = PaymentUnavailable()
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()
    assert order["status"] == "PAYING"

    fresh, fresh_findings = run_check(
        client,
        "PAYMENT_PENDING_TOO_LONG",
        key="fresh",
        thresholds={"payment_age_seconds": 60},
    )
    assert fresh["finding_count"] == 0
    assert fresh_findings == []

    async def wait_for_stale_status():
        async with sessions() as session:
            await session.execute(text("SELECT pg_sleep(1.1)"))

    asyncio.run(wait_for_stale_status())
    stale, stale_findings = run_check(
        client,
        "PAYMENT_PENDING_TOO_LONG",
        key="stale",
        thresholds={"payment_age_seconds": 1},
    )

    assert stale["finding_count"] == 1
    assert stale_findings[0]["order_id"] == order["id"]
    assert stale_findings[0]["evidence"]["status"] == "PAYING"
    assert stale_findings[0]["evidence"]["threshold_seconds"] == 1
