import asyncio
from unittest.mock import patch

from sqlalchemy import text
from test_orders import checkout as checkout_fixture

from app.adapters.outbound.persistence.order_validation_checks import CHECKS, ValidationCheck

checkout = checkout_fixture


def run(client, key="validation", **body):
    return client.post("/order-validation-runs", json=body, headers={"Idempotency-Key": key})


def test_clean_run_persistence_replay_and_validation(checkout):
    client, _, body, _ = checkout
    assert (
        client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).status_code == 201
    )
    response = run(client)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["status"] == "COMPLETED", saved
    assert saved["finding_count"] == 0
    assert len(saved["checks"]) == 8
    assert all(c["status"] == "COMPLETED" for c in saved["checks"])
    assert client.get(response.headers["location"]).json() == saved
    assert run(client).json() == saved
    assert len(client.get("/order-validation-runs").json()) == 1
    assert run(client, checks=["ORDER_TOTAL_MISMATCH"]).status_code == 409
    assert run(client, "bad", checks=["DOES_NOT_EXIST"]).status_code == 422
    assert run(client, "excluded", checks=["PAYMENT_REFERENCE_STATUS_MISMATCH"]).status_code == 422
    assert client.get("/order-validation-runs/2147483647").status_code == 404
    assert client.get("/order-validation-runs/2147483647/findings").status_code == 404


def test_findings_include_totals_stock_history_structure_and_payment(checkout):
    client, sessions, body, _ = checkout
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "order"}).json()

    async def corrupt():
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE orders SET total_amount=1, payment_identifier=NULL, "
                    "latitude=NULL, longitude=NULL"
                )
            )
            await session.execute(text("UPDATE stock SET reserved=0"))
            # An invalid terminal-state transition is recorded by the real history trigger.
            await session.execute(text("UPDATE orders SET status='CREATED'"))
            await session.execute(text("UPDATE orders SET status='PAID'"))

    asyncio.run(corrupt())
    saved = run(client).json()
    assert saved["status"] == "COMPLETED", saved
    findings = client.get(f"/order-validation-runs/{saved['id']}/findings").json()
    assert {f["check_code"] for f in findings} == {
        "ORDER_TOTAL_MISMATCH",
        "INVENTORY_RESERVATION_MISMATCH",
        "INVALID_ORDER_STRUCTURE",
        "PAID_WITHOUT_REFERENCE",
        "INCONSISTENT_STATUS_HISTORY",
    }
    totals = [f for f in findings if f["check_code"] == "ORDER_TOTAL_MISMATCH"]
    assert totals[0]["evidence"] == {"expected": "49.36", "actual": "1.00"}
    filtered = client.get(
        f"/order-validation-runs/{saved['id']}/findings",
        params={"check": "ORDER_TOTAL_MISMATCH", "order_id": order["id"]},
    ).json()
    assert filtered == totals
    assert "4242424242424242" not in str(findings)
    assert len(client.get(f"/order-validation-runs/{saved['id']}/findings?limit=1").json()) == 1


def test_pending_age_and_partial_failure(checkout):
    client, sessions, body, _ = checkout
    order = client.post(
        "/orders", json={**body, "notes": "payment-timeout"}, headers={"Idempotency-Key": "order"}
    ).json()
    assert order["status"] == "PAYING"
    assert run(client, "fresh", checks=["PAYMENT_PENDING_TOO_LONG"]).json()["finding_count"] == 0

    async def age():
        async with sessions() as session:
            await session.execute(text("SELECT pg_sleep(1.1)"))

    asyncio.run(age())
    saved = run(
        client, "stale", checks=["PAYMENT_PENDING_TOO_LONG"], thresholds={"payment_age_seconds": 1}
    ).json()
    assert saved["finding_count"] == 1, saved
    with patch.dict(
        CHECKS,
        {
            "ORDER_TOTAL_MISMATCH": ValidationCheck(
                text("SELECT missing_column FROM orders"), "ERROR"
            )
        },
    ):
        saved = run(
            client, "partial", checks=["ORDER_TOTAL_MISMATCH", "PAID_WITHOUT_REFERENCE"]
        ).json()
    assert saved["status"] == "PARTIAL"
    assert [c["status"] for c in saved["checks"]] == ["FAILED", "COMPLETED"]
    assert client.get(f"/order-validation-runs/{saved['id']}").json() == saved


def test_execution_lock_and_abandoned_run(checkout):
    client, sessions, _, _ = checkout

    async def locked_request():
        async with sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(current_schema()),192837)")
            )
            return await asyncio.to_thread(run, client)

    assert asyncio.run(locked_request()).status_code == 409

    async def abandoned():
        async with sessions() as session, session.begin():
            return await session.scalar(
                text(
                    "INSERT INTO order_validation_runs (idempotency_key, parameters, status) "
                    "VALUES ('abandoned','{}','RUNNING') RETURNING id"
                )
            )

    old_id = asyncio.run(abandoned())
    assert run(client).json()["status"] == "COMPLETED"
    assert client.get(f"/order-validation-runs/{old_id}").json()["status"] == "INTERRUPTED"


def test_stalled_stages_and_pre_payment_cancellation(checkout):
    from test_orders import ADDRESS

    from app.adapters.outbound.persistence.orders import SqlAlchemyOrderRepository
    from app.domain.order import CreateOrder, RequestedItem
    from app.domain.shipping import AddressDetails, Coordinates

    client, sessions, body, warehouses = checkout

    async def setup():
        command = CreateOrder(
            AddressDetails(**{**ADDRESS, "country_code": "AR"}),
            tuple(RequestedItem(i["product_id"], 1) for i in body["items"]),
        )
        ids = {}
        async with sessions() as session:
            repo = SqlAlchemyOrderRepository(session)
            for status in ("CREATED", "BOOKED", "PAYING", "CANCELLED"):
                order, _ = await repo.create(command, status, f"payment:{status}")
                ids[status] = order.id
                if status in ("BOOKED", "PAYING"):
                    await repo.locate(order.id, Coordinates(latitude=-38, longitude=-57.57))
                    assert await repo.reserve(order.id, warehouses[0])
                if status == "PAYING":
                    await repo.start_payment(order.id)
                if status == "CANCELLED":
                    await repo.cancel(order.id, "GEOCODING_FAILED")
            await session.execute(text("SELECT pg_sleep(1.1)"))
        return ids

    ids = asyncio.run(setup())
    saved = run(
        client,
        thresholds={
            "created_age_seconds": 1,
            "booked_age_seconds": 1,
            "payment_age_seconds": 1,
        },
    ).json()
    assert saved["status"] == "COMPLETED", saved
    findings = client.get(f"/order-validation-runs/{saved['id']}/findings").json()
    assert {(f["check_code"], f["order_id"]) for f in findings} == {
        ("ORDER_STUCK_CREATED", ids["CREATED"]),
        ("PAYMENT_NOT_STARTED", ids["BOOKED"]),
        ("PAYMENT_PENDING_TOO_LONG", ids["PAYING"]),
    }
