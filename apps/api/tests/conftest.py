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
    settings = Settings()
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
                    f'CREATE TABLE "{schema}".shipping_addresses '
                    "(LIKE public.shipping_addresses INCLUDING ALL)"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER shipping_address_audit BEFORE INSERT OR UPDATE OR DELETE "
                    f'ON "{schema}".shipping_addresses FOR EACH ROW '
                    "EXECUTE FUNCTION public.audit_record_change()"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TRIGGER warehouse_audit BEFORE INSERT OR UPDATE OR DELETE "
                    f'ON "{schema}".warehouses FOR EACH ROW '
                    "EXECUTE FUNCTION public.audit_record_change()"
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
