import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.adapters.inbound.http.dependencies import get_session
from app.infrastructure.config import Settings
from app.main import create_app


@pytest.fixture
def database_client():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("PostgreSQL DATABASE_URL required; run make test")
    # Pyright cannot infer values supplied by Pydantic Settings from the environment.
    settings = Settings()  # pyright: ignore[reportCallIssue]
    schema = f"test_crud_{uuid4().hex}"
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)

    async def setup():
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(
                text(f'CREATE TABLE "{schema}".products (LIKE public.products INCLUDING ALL)')
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER product_audit BEFORE INSERT OR UPDATE OR DELETE "
                    f'ON "{schema}".products FOR EACH ROW '
                    "EXECUTE FUNCTION public.audit_record_change()"
                )
            )
            for field in ("sku", "ean"):
                await connection.execute(
                    text(
                        f'ALTER TABLE "{schema}".products RENAME CONSTRAINT products_{field}_key '
                        f"TO uq_products_{field}"
                    )
                )
            # Copy the migrated table so tests exercise real migration constraints.
            await connection.execute(
                text(f'CREATE TABLE "{schema}".warehouses (LIKE public.warehouses INCLUDING ALL)')
            )
            await connection.execute(
                text(f'CREATE TABLE "{schema}".audit_logs (LIKE public.audit_logs INCLUDING ALL)')
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER warehouse_audit BEFORE INSERT OR UPDATE OR DELETE "
                    f'ON "{schema}".warehouses FOR EACH ROW '
                    "EXECUTE FUNCTION public.audit_record_change()"
                )
            )
            for table in (
                "stock",
                "customers",
                "orders",
                "order_status_history",
                "order_items",
                "order_validation_runs",
                "order_validation_check_results",
                "order_validation_findings",
            ):
                await connection.execute(
                    text(f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)')
                )
            for table, constraints in (
                ("stock", ("stock_warehouse_id_fkey", "stock_product_id_fkey")),
                ("orders", ("orders_customer_id_fkey", "orders_warehouse_id_fkey")),
                ("order_status_history", ("order_status_history_order_id_fkey",)),
                ("order_items", ("order_items_order_id_fkey", "order_items_product_id_fkey")),
            ):
                for constraint in constraints:
                    await connection.execute(
                        text(
                            f'ALTER TABLE "{schema}".{table} DROP CONSTRAINT IF EXISTS {constraint}'
                        )
                    )
            await connection.execute(
                text(
                    f'ALTER TABLE "{schema}".stock '
                    f'ADD FOREIGN KEY (warehouse_id) REFERENCES "{schema}".warehouses(id) '
                    "ON DELETE RESTRICT, "
                    f'ADD FOREIGN KEY (product_id) REFERENCES "{schema}".products(id) '
                    "ON DELETE RESTRICT"
                )
            )
            await connection.execute(
                text(
                    f'ALTER TABLE "{schema}".orders '
                    f'ADD FOREIGN KEY (customer_id) REFERENCES "{schema}".customers(id) '
                    "ON DELETE RESTRICT, "
                    f'ADD FOREIGN KEY (warehouse_id) REFERENCES "{schema}".warehouses(id) '
                    "ON DELETE RESTRICT"
                )
            )
            await connection.execute(
                text(
                    f'ALTER TABLE "{schema}".order_status_history '
                    f'ADD FOREIGN KEY (order_id) REFERENCES "{schema}".orders(id) '
                    "ON DELETE RESTRICT"
                )
            )
            await connection.execute(
                text(
                    f'ALTER TABLE "{schema}".order_items '
                    f'ADD FOREIGN KEY (order_id) REFERENCES "{schema}".orders(id) '
                    "ON DELETE RESTRICT, "
                    f'ADD FOREIGN KEY (product_id) REFERENCES "{schema}".products(id) '
                    "ON DELETE RESTRICT"
                )
            )
            for table, trigger, function, events in (
                (
                    "stock",
                    "stock_audit",
                    "audit_record_change",
                    "BEFORE INSERT OR UPDATE OR DELETE",
                ),
                ("orders", "order_timestamp", "touch_order_timestamp", "BEFORE UPDATE"),
                ("orders", "order_status_record", "record_order_status", "AFTER INSERT OR UPDATE"),
                ("orders", "order_no_delete", "reject_order_removal", "BEFORE DELETE"),
                (
                    "order_status_history",
                    "order_status_history_immutable",
                    "protect_order_status_history",
                    "BEFORE UPDATE OR DELETE",
                ),
                (
                    "order_items",
                    "order_item_values",
                    "set_order_item_values",
                    "BEFORE INSERT OR UPDATE",
                ),
            ):
                await connection.execute(
                    text(
                        f'CREATE TRIGGER {trigger} {events} ON "{schema}".{table} '
                        f"FOR EACH ROW EXECUTE FUNCTION public.{function}()"
                    )
                )

    async def cleanup():
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()

    asyncio.run(setup())
    test_engine = create_async_engine(
        str(settings.database_url),
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def session_override():
        async with sessions() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        asyncio.run(test_engine.dispose())
        asyncio.run(cleanup())


@pytest.fixture
def warehouse_client(database_client):
    return database_client
