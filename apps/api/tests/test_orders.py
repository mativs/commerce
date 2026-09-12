import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from test_order_models import order_models as order_models

from app.adapters.outbound.persistence.models import Product, Stock, Warehouse
from app.adapters.outbound.persistence.orders import SqlAlchemyOrderRepository
from app.application.ports.geocoder import GeocodingUnavailable
from app.application.ports.payment import PaymentResponse, PaymentResult, PaymentUnavailable
from app.application.services.orders import OrderService
from app.domain.order import CreateOrder, RequestedItem, distance_km
from app.domain.shipping import AddressDetails, Coordinates

ADDRESS = {
    "recipient_name": "  Ana Pérez  ",
    "phone": "+54 223 555 0100",
    "address_line1": "San Martín 2500",
    "address_line2": "Floor 2, apartment B",
    "city": "Mar del Plata",
    "state": "Buenos Aires",
    "postal_code": "B7600",
    "country_code": "ar",
    "delivery_instructions": "Ring the bell",
}


@pytest.fixture
def checkout(order_models, database_client):
    sessions = order_models
    client, _ = database_client
    client.app.state.order_geocoder = AsyncMock()
    client.app.state.order_geocoder.geocode.return_value = Coordinates(
        latitude=-38, longitude=-57.57
    )
    client.app.state.payment_gateway = AsyncMock()
    client.app.state.payment_gateway.charge.return_value = PaymentResponse(
        PaymentResult.SUCCEEDED, "pay_test_success"
    )

    async def setup():
        async with sessions() as session, session.begin():
            products = [
                Product(
                    name=f"Product {i}", sku=f"CHECKOUT-{i}", price=Decimal("12.34"), currency="USD"
                )
                for i in range(2)
            ]
            warehouses = [
                Warehouse(name=f"Warehouse {i}", latitude=-38 - i / 10, longitude=-57.57)
                for i in range(2)
            ]
            session.add_all(products + warehouses)
            await session.flush()
            session.add_all(
                [
                    Stock(warehouse_id=w.id, product_id=p.id, on_hand=10)
                    for w in warehouses
                    for p in products
                ]
            )
            return [p.id for p in products], [w.id for w in warehouses]

    products, warehouses = asyncio.run(setup())
    body = {
        "customer": {
            "first_name": "Ana",
            "last_name": "Perez",
            "phone": "+54 223 555 0100",
            "email": "ana@example.com",
        },
        "shipping_address": ADDRESS,
        "items": [{"product_id": p, "quantity": 2} for p in products],
        "credit_card_number": "4242424242424242",
        "payment_description": "Demo checkout",
    }
    return client, sessions, body, warehouses


def stock_rows(sessions):
    async def read():
        async with sessions() as session:
            return [
                (s.warehouse_id, s.product_id, s.on_hand, s.reserved)
                for s in await session.scalars(select(Stock).order_by(Stock.id))
            ]

    return asyncio.run(read())


def test_checkout_snapshots_duplicates_history_and_replay(checkout):
    client, sessions, body, warehouses = checkout
    body["items"].append(body["items"][0])
    response = client.post("/orders", json=body, headers={"Idempotency-Key": "one"})
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "PAID" and order["warehouse_id"] == warehouses[0]
    assert order["payment_description"] == "Demo checkout"
    assert order["payment_identifier"].startswith("pay_")
    assert order["customer"]["email"] == "ana@example.com"
    assert order["total_amount"] == "74.04"
    assert [i["quantity"] for i in order["items"]] == [4, 2]
    assert [h["status"] for h in order["history"]] == ["CREATED", "BOOKED", "PAID"]
    assert order["shipping_address"]["recipient_name"] == "Ana Pérez"
    assert client.get(response.headers["location"]).json() == order
    assert client.get("/orders").json() == [order]
    assert client.post("/orders", json=body, headers={"Idempotency-Key": "one"}).json() == order
    client.app.state.order_geocoder.geocode.assert_awaited_once()
    client.app.state.payment_gateway.charge.assert_awaited_once()
    assert [s[3] for s in stock_rows(sessions)] == [4, 2, 0, 0]
    changed = {**body, "notes": "Different order"}
    assert (
        client.post("/orders", json=changed, headers={"Idempotency-Key": "one"}).status_code == 409
    )
    assert client.delete(response.headers["location"]).status_code == 405


@pytest.mark.parametrize(
    "failure,reason,history,reserved",
    [
        ("geo", "GEOCODING_FAILED", ["CREATED", "CANCELLED"], 0),
        ("stock", "OUT_OF_STOCK", ["CREATED", "CANCELLED"], 0),
        ("payment", "PAYMENT_FAILED", ["CREATED", "BOOKED", "CANCELLED"], 0),
        ("unknown", None, ["CREATED", "BOOKED"], 4),
    ],
)
def test_failures_are_durable(checkout, failure, reason, history, reserved):
    client, sessions, body, _ = checkout
    if failure == "geo":
        client.app.state.order_geocoder.geocode.side_effect = GeocodingUnavailable()
    elif failure == "stock":
        body["items"][0]["quantity"] = 11
    elif failure == "payment":
        client.app.state.payment_gateway.charge.return_value = PaymentResult.DECLINED
    else:
        client.app.state.payment_gateway.charge.side_effect = PaymentUnavailable()
    response = client.post("/orders", json=body, headers={"Idempotency-Key": failure})
    assert response.status_code == (202 if failure == "unknown" else 201), response.text
    order = response.json()
    assert [h["status"] for h in order["history"]] == history
    assert order["failure_reason"] == reason
    assert order["history"][-1]["reason"] == reason
    assert sum(s[3] for s in stock_rows(sessions)) == reserved
    assert all(s[2] == 10 for s in stock_rows(sessions))
    assert client.get(response.headers["location"]).json() == order
    if failure in ("geo", "stock"):
        client.app.state.payment_gateway.charge.assert_not_awaited()


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"product_id": 1, "quantity": -1}],
        [{"product_id": 1, "quantity": True}],
        [{"product_id": 1, "quantity": 0}],
        [{"product_id": 1, "quantity": 2147483647}, {"product_id": 1, "quantity": 1}],
        [{"product_id": 2147483647, "quantity": 1}],
    ],
)
def test_invalid_input_leaves_no_order(checkout, items):
    client, sessions, body, _ = checkout
    response = client.post(
        "/orders", json={**body, "items": items}, headers={"Idempotency-Key": "invalid"}
    )
    assert response.status_code == 422, response.text
    assert client.get("/orders").json() == []
    client.app.state.order_geocoder.geocode.assert_not_awaited()


def test_concurrent_requests_same_key_only_process_once(checkout):
    client, sessions, body, _ = checkout
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post("/orders", json=body, headers={"Idempotency-Key": "same"}),
                range(2),
            )
        )
    assert all(r.status_code in (201, 202) for r in results)
    assert len({r.json()["id"] for r in results}) == 1
    assert len(client.get("/orders").json()) == 1
    client.app.state.payment_gateway.charge.assert_awaited_once()
    assert sum(s[3] for s in stock_rows(sessions)) == 4


def test_payment_does_not_hold_stock_locks_and_no_overselling(checkout):
    client, sessions, body, warehouses = checkout

    async def check():
        async with sessions() as session, session.begin():
            await session.execute(text("UPDATE stock SET on_hand=2"))
        payment_entered = asyncio.Event()
        release_payment = asyncio.Event()

        class BlockingPayment:
            async def charge(self, amount, *, idempotency_key):
                payment_entered.set()
                await release_payment.wait()
                return PaymentResult.SUCCEEDED

        command = CreateOrder(
            AddressDetails(**{**ADDRESS, "country_code": "AR"}),
            tuple(RequestedItem(i["product_id"], i["quantity"]) for i in body["items"]),
        )
        async with sessions() as first, sessions() as second:
            first_service = OrderService(
                SqlAlchemyOrderRepository(first), client.app.state.order_geocoder, BlockingPayment()
            )
            task = asyncio.create_task(first_service.create(command, "first"))
            try:
                await asyncio.wait_for(payment_entered.wait(), 5)
                # NOWAIT proves inventory locks were released during payment.
                async with sessions() as probe, probe.begin():
                    await probe.execute(text("SELECT * FROM stock FOR UPDATE NOWAIT"))
                second_service = OrderService(
                    SqlAlchemyOrderRepository(second),
                    client.app.state.order_geocoder,
                    client.app.state.payment_gateway,
                )
                order2 = await asyncio.wait_for(second_service.create(command, "second"), 5)
                assert order2.status == "PAID" and order2.warehouse_id == warehouses[1]
                order3 = await second_service.create(command, "third")
                assert order3.failure_reason == "OUT_OF_STOCK"
            finally:
                release_payment.set()
                order1 = await task
            assert order1.status == "PAID" and order1.warehouse_id == warehouses[0]

    asyncio.run(check())
    assert all(s[2] == s[3] == 2 for s in stock_rows(sessions))


def test_stale_candidates_fall_back_and_release_once(checkout):
    client, sessions, body, warehouses = checkout

    async def check():
        command = CreateOrder(
            AddressDetails(**{**ADDRESS, "country_code": "AR"}),
            tuple(RequestedItem(i["product_id"], 10) for i in body["items"]),
        )
        async with sessions() as s1, sessions() as s2:
            repo1, repo2 = SqlAlchemyOrderRepository(s1), SqlAlchemyOrderRepository(s2)
            first, _ = await repo1.create(command, "a")
            second, _ = await repo2.create(command, "b")
            assert len(await repo1.candidates(first.id)) == 2
            assert len(await repo2.candidates(second.id)) == 2
            outcomes = await asyncio.gather(
                repo1.reserve(first.id, warehouses[0]), repo2.reserve(second.id, warehouses[0])
            )
            assert sorted(outcomes) == [False, True]
            loser_repo, loser = (repo2, second) if outcomes[0] else (repo1, first)
            assert await loser_repo.reserve(loser.id, warehouses[1])
            await loser_repo.cancel(loser.id, "PAYMENT_FAILED")
            await loser_repo.cancel(loser.id, "PAYMENT_FAILED")
            await loser_repo.pay(loser.id)
            assert (await loser_repo.get(loser.id)).status == "CANCELLED"

    asyncio.run(check())
    rows = stock_rows(sessions)
    assert [r[3] for r in rows if r[0] == warehouses[1]] == [0, 0]
    assert [r[3] for r in rows if r[0] == warehouses[0]] == [10, 10]


def test_haversine():
    origin = Coordinates(latitude=0, longitude=0)
    assert distance_km(origin, origin) == 0
    assert distance_km(origin, Coordinates(latitude=0, longitude=1)) == pytest.approx(
        111.195, rel=1e-5
    )


def test_failed_finalization_rolls_back_stock_and_history(checkout):
    _, sessions, body, warehouses = checkout

    async def check():
        command = CreateOrder(
            AddressDetails(**{**ADDRESS, "country_code": "AR"}),
            tuple(RequestedItem(i["product_id"], 2) for i in body["items"]),
        )
        async with sessions() as session:
            repository = SqlAlchemyOrderRepository(session)
            order, _ = await repository.create(command, "rollback")
            assert await repository.reserve(order.id, warehouses[0])
            async with session.begin():
                await session.execute(
                    text("""
                    CREATE FUNCTION fail_cancel() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        IF NEW.status = 'CANCELLED' THEN
                            RAISE EXCEPTION 'Simulated finalization failure';
                        END IF;
                        RETURN NEW;
                    END;
                    $$
                """)
                )
                await session.execute(
                    text(
                        "CREATE TRIGGER fail_cancel BEFORE UPDATE ON orders "
                        "FOR EACH ROW EXECUTE FUNCTION fail_cancel()"
                    )
                )
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError):
                await repository.cancel(order.id, "PAYMENT_FAILED")
            saved = await repository.get(order.id)
            assert saved.status == "BOOKED" and saved.failure_reason is None
            assert [h.status for h in saved.history] == ["CREATED", "BOOKED"]

    asyncio.run(check())
    assert sum(s[3] for s in stock_rows(sessions)) == 4


@pytest.mark.parametrize(
    "change", ["currency='ARS'", "is_active=false", "deleted_at=clock_timestamp()"]
)
def test_product_eligibility(checkout, change):
    client, sessions, body, _ = checkout

    async def update():
        async with sessions() as session, session.begin():
            await session.execute(text(f"UPDATE products SET {change}"))

    asyncio.run(update())
    response = client.post("/orders", json=body, headers={"Idempotency-Key": "ineligible"})
    assert response.status_code == 422
    assert client.get("/orders").json() == []


def test_missing_stock_cannot_partially_book(checkout):
    client, sessions, body, _ = checkout

    async def remove_stock():
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE stock SET deleted_at=clock_timestamp() WHERE product_id=:pid"),
                {"pid": body["items"][0]["product_id"]},
            )

    asyncio.run(remove_stock())
    order = client.post("/orders", json=body, headers={"Idempotency-Key": "missing"}).json()
    assert order["failure_reason"] == "OUT_OF_STOCK"
    assert sum(s[3] for s in stock_rows(sessions)) == 0
