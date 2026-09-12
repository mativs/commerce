import asyncio
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.adapters.outbound.persistence.models import Order, OrderStatusHistory


@pytest.fixture
def order_models(database_client):
    client, sessions = database_client
    address = client.post(
        "/shipping-addresses",
        json={
            "recipient_name": "Order model test",
            "address_line1": "San Martin 2500",
            "city": "Mar del Plata",
            "state": "Buenos Aires",
            "postal_code": "B7600",
            "country_code": "AR",
        },
    ).json()

    def migrate(connection):
        audit_function = connection.scalar(
            text("SELECT pg_get_functiondef('public.audit_record_change()'::regprocedure)")
        )
        connection.execute(
            text(
                audit_function.replace(
                    "FUNCTION public.audit_record_change()", "FUNCTION audit_record_change()"
                )
            )
        )
        for filename in (
            "0006_stock.py",
            "0007_order_models.py",
            "0008_order_items.py",
            "0009_order_checkout.py",
            "0010_seed_stock.py",
            "0011_order_payment.py",
            "0012_customers.py",
        ):
            path = Path(__file__).parents[1] / "migrations/versions" / filename
            spec = importlib.util.spec_from_file_location("migration", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()

    async def setup():
        async with sessions() as session, session.begin():
            await (await session.connection()).run_sync(migrate)

    asyncio.run(setup())
    return sessions, address["id"]


def test_wall_clock_defaults_update_trigger_and_chronology(order_models):
    sessions, address_id = order_models

    async def check():
        async with sessions() as session, session.begin():
            transaction_time = await session.scalar(text("SELECT now()"))
            await session.execute(text("SELECT pg_sleep(0.01)"))
            order = Order(shipping_address_id=address_id)
            session.add(order)
            await session.flush()
            assert order.status == "CREATED" and order.warehouse_id is None
            assert order.total_amount == 0
            created_at, first_updated = order.created_at, order.updated_at
            assert created_at > transaction_time
            await session.execute(text("SELECT pg_sleep(0.01)"))
            order.notes = "New notes"
            await session.flush()
            # FetchedValue marks a database-generated value, not a Python onupdate.
            assert order.updated_at > first_updated
            assert order.created_at == created_at
            await session.execute(text("SELECT pg_sleep(0.01)"))
            order.status = "BOOKED"
            await session.flush()
            await session.execute(text("SELECT pg_sleep(0.01)"))
            await session.execute(
                text(
                    "UPDATE orders SET status='PAID', created_at='2000-01-01', "
                    "updated_at='2000-01-01' WHERE id=:id"
                ),
                {"id": order.id},
            )
            await session.refresh(order)
            assert order.created_at == created_at and order.updated_at > first_updated
            history = (
                await session.scalars(
                    select(OrderStatusHistory)
                    .where(OrderStatusHistory.order_id == order.id)
                    .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
                )
            ).all()
            assert [row.status for row in history] == ["CREATED", "BOOKED", "PAID"]
            assert history[0].created_at < history[1].created_at < history[2].created_at
            assert history[0].created_at > transaction_time
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE table_name IN ('orders', 'order_status_history')"
                    )
                )
                == 0
            )
            columns = (
                await session.execute(
                    text(
                        "SELECT column_name, column_default FROM information_schema.columns "
                        "WHERE table_schema=current_schema() AND table_name='order_status_history'"
                    )
                )
            ).all()
            assert {column.column_name for column in columns} == {
                "id",
                "order_id",
                "status",
                "created_at",
                "reason",
            }
            assert (
                next(c.column_default for c in columns if c.column_name == "created_at")
                == "clock_timestamp()"
            )

    asyncio.run(check())


def test_history_immutable_orders_not_deleted_and_rollback(order_models):
    sessions, address_id = order_models

    async def check():
        async with sessions() as session, session.begin():
            order = Order(shipping_address_id=address_id)
            session.add(order)
            await session.flush()
            order_id = order.id
        for statement in (
            "UPDATE order_status_history SET status='CANCELLED' WHERE order_id=:id",
            "DELETE FROM order_status_history WHERE order_id=:id",
            "DELETE FROM orders WHERE id=:id",
        ):
            async with sessions() as session:
                with pytest.raises(DBAPIError):
                    await session.execute(text(statement), {"id": order_id})
                await session.rollback()
        async with sessions() as session:
            await session.execute(
                text("UPDATE orders SET status='CANCELLED' WHERE id=:id"), {"id": order_id}
            )
            await session.rollback()
        async with sessions() as session:
            assert (await session.get(Order, order_id)).status == "CREATED"
            assert await session.scalar(text("SELECT count(*) FROM order_status_history")) == 1

    asyncio.run(check())


@pytest.mark.parametrize(
    "change", ["status='INVALID'", "total_amount=-1", "shipping_address_id=-1", "warehouse_id=-1"]
)
def test_order_constraints(order_models, change):
    sessions, address_id = order_models

    async def check():
        async with sessions() as session, session.begin():
            session.add(Order(shipping_address_id=address_id))
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(text(f"UPDATE orders SET {change}"))
            await session.rollback()
            assert await session.scalar(text("SELECT count(*) FROM order_status_history")) == 1

    asyncio.run(check())
