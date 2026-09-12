import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_order_models import order_models as order_models

from app.adapters.outbound.persistence.models import Order, OrderItem, Product


@pytest.fixture
def item_data(order_models):
    sessions, address_id = order_models

    async def setup():
        async with sessions() as session, session.begin():
            order = Order(shipping_address_id=address_id)
            product = Product(
                name="Snapshot test", sku="ITEM-TEST", price=Decimal("12.34"), currency="USD"
            )
            session.add_all([order, product])
            await session.flush()
            return order.id, product.id

    order_id, product_id = asyncio.run(setup())
    return sessions, {"order_id": order_id, "product_id": product_id}


def test_price_snapshot_without_item_timestamps(item_data):
    sessions, ids = item_data

    async def check():
        async with sessions() as session, session.begin():
            item = OrderItem(**ids, quantity=2)
            session.add(item)
            await session.flush()
            assert item.unit_price == Decimal("12.34")
            await session.execute(
                text("UPDATE products SET price=99.99 WHERE id=:id"), {"id": ids["product_id"]}
            )
            item.quantity = 3
            await session.flush()
            assert item.unit_price == Decimal("12.34")
            columns = (
                (
                    await session.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema=current_schema() AND table_name='order_items'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert set(columns) == {"id", "order_id", "product_id", "quantity", "unit_price"}
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM audit_logs WHERE table_name='order_items'")
                )
                == 0
            )

    asyncio.run(check())


def test_direct_insert_copies_price_and_unique_pair(item_data):
    sessions, ids = item_data

    async def check():
        async with sessions() as session, session.begin():
            price = await session.scalar(
                text(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                    "VALUES (:order_id, :product_id, 1, 0) RETURNING unit_price"
                ),
                ids,
            )
            assert price == Decimal("12.34")
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                session.add(OrderItem(**ids, quantity=1))
                await session.flush()
            await session.rollback()
        async with sessions() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text("UPDATE order_items SET unit_price=0"))
            await session.rollback()

    asyncio.run(check())


@pytest.mark.parametrize(
    "changes", [{"quantity": 0}, {"quantity": -1}, {"order_id": -1}, {"product_id": -1}]
)
def test_item_constraints(item_data, changes):
    sessions, ids = item_data

    async def check():
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                session.add(OrderItem(**{**ids, "quantity": 1, **changes}))
                await session.flush()
            await session.rollback()
            assert await session.scalar(text("SELECT count(*) FROM order_items")) == 0

    asyncio.run(check())
