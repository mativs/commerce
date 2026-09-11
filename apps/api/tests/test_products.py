import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.product import validate_ean

PRODUCT = {
    "name": " Shirt ",
    "sku": " shirt-m ",
    "price": "19.99",
    "currency": "ars",
}


def test_product_crud(database_client):
    client, _ = database_client
    assert client.get("/products").json() == []
    created = client.post("/products", json=PRODUCT)
    assert created.status_code == 201
    data = created.json()
    assert data["name"] == "Shirt" and data["sku"] == "SHIRT-M"
    assert data["price"] == "19.99" and data["currency"] == "ARS"
    assert data["is_active"] is True
    url = created.headers["location"]
    assert client.get(url).json() == data
    updated = client.put(url, json={**PRODUCT, "price": "25.10", "is_active": False})
    assert updated.status_code == 200
    assert updated.json()["price"] == "25.10"
    assert updated.json()["ean"] == data["ean"]
    assert validate_ean(data["ean"]) == data["ean"]
    assert updated.json()["created_at"] == data["created_at"]
    assert updated.json()["updated_at"] != data["updated_at"]
    assert client.get("/products").json() == [updated.json()]
    deleted = client.delete(url)
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get("/products").json() == []
    assert client.get(url).status_code == 404
    assert client.put(url, json=PRODUCT).status_code == 404
    assert client.delete(url).status_code == 404
    logs = client.get(f"{url}/logs").json()
    assert [log["action"] for log in logs] == ["create", "update", "delete"]
    assert logs[1]["old_values"]["price"] == 19.99
    assert logs[1]["new_values"]["price"] == 25.10
    assert logs[-1]["new_values"]["deleted_at"] is not None


@pytest.mark.parametrize("field,value", [("sku", " SHIRT-m ")])
def test_identifiers_reserved_and_failed_update_rolled_back(database_client, field, value):
    client, _ = database_client
    first = client.post("/products", json=PRODUCT)
    second_data = {**PRODUCT, "sku": "SECOND"}
    second = client.post("/products", json=second_data)
    assert second.status_code == 201
    for deleted in (False, True):
        if deleted:
            assert client.delete(first.headers["location"]).status_code == 204
        conflict = client.post("/products", json={**second_data, "sku": "THIRD", field: value})
        assert conflict.status_code == 409
        assert field.upper() in conflict.json()["detail"]
        conflict = client.put(second.headers["location"], json={**second_data, field: value})
        assert conflict.status_code == 409
        assert client.get(second.headers["location"]).json() == second.json()
        assert len(client.get(second.headers["location"] + "/logs").json()) == 1


def test_generated_ean_and_duplicate_names(database_client):
    client, _ = database_client
    for index in range(3):
        response = client.post("/products", json={**PRODUCT, "sku": str(index)})
        assert response.status_code == 201
        assert validate_ean(response.json()["ean"]) == response.json()["ean"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"name": " "},
        {"sku": " "},
        {"sku": "x" * 101},
        {"ean": "5901234123458"},
        {"ean": "5901234123457"},
        {"ean": None},
        {"ean": 96385074},
        {"ean": "１２３４５６７０"},
        {"price": "-0.01"},
        {"price": "NaN"},
        {"price": "Infinity"},
        {"price": "1.001"},
        {"price": "10000000000"},
        {"currency": "12A"},
        {"is_active": "true"},
        {"size": "M"},
        {"color": "Blue"},
    ],
)
def test_validation(database_client, invalid):
    client, _ = database_client
    assert client.post("/products", json={**PRODUCT, **invalid}).status_code == 422
    assert client.put("/products/1", json={**PRODUCT, **invalid}).status_code == 422


@pytest.mark.parametrize("ean", ["5901234123457", "96385074", "01234565", "4006381333931"])
def test_ean_check_digit(ean):
    assert validate_ean(ean) == ean
    with pytest.raises(ValueError):
        validate_ean(ean[:-1] + str((int(ean[-1]) + 1) % 10))


def test_concurrent_duplicate_create(database_client):
    client, _ = database_client
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post("/products", json=PRODUCT), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    products = client.get("/products").json()
    assert len(products) == 1
    assert len(client.get(f"/products/{products[0]['id']}/logs").json()) == 1


def test_database_constraints_and_audit(database_client):
    client, sessions = database_client
    response = client.post("/products", json=PRODUCT)
    product_id = response.json()["id"]

    async def check():
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO products (name, sku, price, currency) "
                        "VALUES ('Duplicate', 'SHIRT-M', 1, 'ARS')"
                    )
                )
            await session.rollback()
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text("UPDATE products SET price = -1 WHERE id = :id"), {"id": product_id}
                )
            await session.rollback()
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE products SET description = 'Updated by SQL' WHERE id = :id"),
                {"id": product_id},
            )

    asyncio.run(check())
    logs = client.get(response.headers["location"] + "/logs").json()
    assert len(logs) == 2
    assert logs[-1]["new_values"]["description"] == "Updated by SQL"


@pytest.mark.parametrize("deleted", [False, True])
def test_generated_collision_retries_without_extra_audit(database_client, deleted):
    client, _ = database_client
    with patch("app.adapters.inbound.http.products.random_ean", return_value="4006381333931"):
        first = client.post("/products", json=PRODUCT)
    if deleted:
        client.delete(first.headers["location"])
    with patch("app.adapters.inbound.http.products.random_ean") as generate:
        generate.side_effect = [first.json()["ean"], "5901234123457"]
        created = client.post("/products", json={**PRODUCT, "sku": "SECOND"})
    assert created.status_code == 201
    assert generate.call_count == 2
    assert created.json()["ean"] == "5901234123457"
    logs = client.get(created.headers["location"] + "/logs").json()
    assert len(logs) == 1 and logs[0]["new_values"]["ean"] == "5901234123457"


def test_collision_exhaustion_does_not_save(database_client):
    client, sessions = database_client
    first = client.post("/products", json=PRODUCT)
    with patch(
        "app.adapters.inbound.http.products.random_ean", return_value=first.json()["ean"]
    ) as generate:
        response = client.post("/products", json={**PRODUCT, "sku": "SECOND"})
    assert response.status_code == 503
    assert generate.call_count == 5
    assert len(client.get("/products").json()) == 1

    async def count_logs():
        async with sessions() as session:
            return await session.scalar(text("SELECT count(*) FROM audit_logs"))

    assert asyncio.run(count_logs()) == 1


def test_generator_preserves_zeros_and_check_digit():
    from app.adapters.outbound.identifiers.ean import random_ean

    with patch("app.adapters.outbound.identifiers.ean.randbelow", return_value=123456789):
        ean = random_ean()
    assert len(ean) == 13 and ean.startswith("000")
    assert validate_ean(ean) == ean
