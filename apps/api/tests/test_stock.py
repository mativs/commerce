import asyncio
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.outbound.persistence.models import Product, Stock, Warehouse


@pytest.fixture
def stock_data(database_client):
    client, sessions = database_client

    def migrate(connection):
        connection.execute(
            text("SELECT set_config('search_path', current_schema() || ',public', true)")
        )
        path = Path(__file__).parents[1] / "migrations/versions/0006_stock.py"
        spec = importlib.util.spec_from_file_location("stock_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Run the real migration in the fixture's isolated schema, including FKs.
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            path = Path(__file__).parents[1] / "migrations/versions/0016_remove_stock_deleted_at.py"
            spec = importlib.util.spec_from_file_location("remove_stock_deleted_at", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()

    async def setup():
        async with sessions() as session, session.begin():
            await (await session.connection()).run_sync(migrate)
            warehouse = Warehouse(name="Stock test", latitude=-38, longitude=-57)
            product = Product(name="Stock test", sku="STOCK-TEST", price=Decimal("1.00"))
            session.add_all([warehouse, product])
            await session.flush()
            return warehouse.id, product.id

    warehouse_id, product_id = asyncio.run(setup())
    return sessions, {"warehouse_id": warehouse_id, "product_id": product_id}


def test_stock_defaults_update_and_audit(stock_data):
    sessions, ids = stock_data

    async def check():
        async with sessions() as session, session.begin():
            row = Stock(**ids)
            session.add(row)
            await session.flush()
            assert row.on_hand == row.reserved == 0
            assert row.created_at and row.updated_at
            stock_id, created_at, updated_at = row.id, row.created_at, row.updated_at
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE stock SET on_hand = 10, reserved = 4 WHERE id = :id"), {"id": stock_id}
            )
        async with sessions() as session:
            row = await session.get(Stock, stock_id)
            assert row.on_hand == 10 and row.reserved == 4
            assert row.created_at == created_at and row.updated_at > updated_at
            logs = (
                await session.execute(
                    text(
                        "SELECT action, new_values FROM audit_logs "
                        "WHERE table_name = 'stock' ORDER BY id"
                    )
                )
            ).all()
            assert [log.action for log in logs] == ["create", "update"]
            assert logs[-1].new_values["reserved"] == 4

    asyncio.run(check())


@pytest.mark.parametrize("on_hand,reserved", [(-1, 0), (1, -1), (1, 2), (None, 0), (0, None)])
def test_invalid_stock_quantities(stock_data, on_hand, reserved):
    sessions, ids = stock_data

    async def check():
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO stock (warehouse_id, product_id, on_hand, reserved) "
                        "VALUES (:warehouse_id, :product_id, :on_hand, :reserved)"
                    ),
                    {**ids, "on_hand": on_hand, "reserved": reserved},
                )
            await session.rollback()
            assert (await session.scalars(select(Stock))).all() == []
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM audit_logs WHERE table_name = 'stock'")
                )
                == 0
            )

    asyncio.run(check())


def test_unique_pair_and_foreign_keys(stock_data):
    sessions, ids = stock_data

    async def check():
        async with sessions() as session, session.begin():
            session.add(Stock(**ids, on_hand=5, reserved=5))
        for values in (ids, {**ids, "warehouse_id": -1}, {**ids, "product_id": -1}):
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    session.add(Stock(**values))
                    await session.flush()
                await session.rollback()
        for table, key in (("warehouses", "warehouse_id"), ("products", "product_id")):
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE id = :id"), {"id": ids[key]}
                    )
                await session.rollback()

    asyncio.run(check())
