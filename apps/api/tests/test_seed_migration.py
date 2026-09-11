import asyncio
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.product import validate_ean


def load_seed():
    path = Path(__file__).parents[1] / "migrations/versions/0005_seed_demo_data.py"
    spec = importlib.util.spec_from_file_location("seed_demo_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def apply_seed(sessions):
    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            load_seed().upgrade()

    async with sessions() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(upgrade)


def test_seed_data_and_audit(database_client):
    client, sessions = database_client
    asyncio.run(apply_seed(sessions))
    warehouses = client.get("/warehouses").json()
    addresses = client.get("/shipping-addresses").json()
    response = client.get("/products")
    assert response.status_code == 200
    products = response.json()
    assert len(warehouses) == 5 and len(addresses) == 5 and len(products) == 100
    expected = {row["sku"]: row for row in load_seed().product_rows()}
    for product in products:
        row = expected[product["sku"]]
        assert product["name"] == row["name"]
        assert product["price"] == str(row["price"])
        assert product["ean"] == validate_ean(row["ean"])
        assert product["currency"] == "USD" and product["is_active"] is True
    assert len({product["ean"] for product in products}) == 100
    assert {(w["latitude"], w["longitude"]) for w in warehouses}.isdisjoint(
        {(a["latitude"], a["longitude"]) for a in addresses}
    )
    for path, records in [
        ("warehouses", warehouses),
        ("shipping-addresses", addresses),
        ("products", products),
    ]:
        for record in records:
            assert record["created_at"] and record["updated_at"] and record["deleted_at"] is None
            logs = client.get(f"/{path}/{record['id']}/logs").json()
            assert len(logs) == 1 and logs[0]["action"] == "create"


def test_seed_conflict_is_atomic(database_client):
    client, sessions = database_client
    existing = client.post(
        "/products",
        json={
            "name": "Existing product",
            "sku": "ELEC-EMT-050-10",
            "price": "1.00",
            "currency": "USD",
        },
    )
    assert existing.status_code == 201
    with pytest.raises(IntegrityError):
        asyncio.run(apply_seed(sessions))
    assert client.get("/warehouses").json() == []
    assert client.get("/shipping-addresses").json() == []
    assert client.get("/products").json() == [existing.json()]

    async def count_logs():
        async with sessions() as session:
            return await session.scalar(text("SELECT count(*) FROM audit_logs"))

    assert asyncio.run(count_logs()) == 1
