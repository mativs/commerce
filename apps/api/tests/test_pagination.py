import asyncio

import pytest
from sqlalchemy import text
from test_shipping_addresses import ADDRESS


@pytest.mark.parametrize(
    "path,payload",
    [
        ("warehouses", {"name": "Pagination warehouse"}),
        (
            "products",
            {"name": "Pagination product", "sku": "PAGE", "price": "1.00", "currency": "USD"},
        ),
        ("shipping-addresses", ADDRESS),
    ],
)
def test_pages_and_logs(database_client, path, payload):
    client, _ = database_client
    ids = []
    for i in range(4):
        data = {**payload, **({"sku": f"PAGE-{i}"} if path == "products" else {})}
        response = client.post(f"/{path}", json=data)
        assert response.status_code == 201
        ids.append(response.json()["id"])
    assert client.delete(f"/{path}/{ids[1]}").status_code == 204
    first = client.get(f"/{path}?limit=2&offset=0").json()
    second = client.get(f"/{path}?limit=2&offset=2").json()
    assert [r["id"] for r in first] == [ids[0], ids[2]]
    assert [r["id"] for r in second] == [ids[3]]
    assert client.get(f"/{path}?limit=2&offset=20").json() == []
    logs = client.get(f"/{path}/{ids[1]}/logs?limit=1").json()
    assert [r["action"] for r in logs] == ["create"]
    assert [r["action"] for r in client.get(f"/{path}/{ids[1]}/logs?limit=1&offset=1").json()] == [
        "delete"
    ]
    assert client.get(f"/{path}/{ids[1]}/logs?offset=2").json() == []
    for query in ["limit=0", "limit=101", "offset=-1", "limit=1.5", "offset=x"]:
        assert client.get(f"/{path}?{query}").status_code == 422
        assert client.get(f"/{path}/{ids[0]}/logs?{query}").status_code == 422


def test_default_limit_and_product_search(database_client):
    client, sessions = database_client

    async def seed():
        async with sessions() as session, session.begin():
            await session.execute(
                text("""
                INSERT INTO products (name,sku,price,currency,is_active)
                SELECT 'Product ' || n, 'PAGE-' || n, 1, 'USD', true
                FROM generate_series(1, 105) n
            """)
            )

    asyncio.run(seed())
    assert len(client.get("/products").json()) == 50
    assert len(client.get("/products?limit=100").json()) == 100
    assert len(client.get("/products?limit=100&offset=100").json()) == 5
    result = client.get("/products?q=page-105&is_active=true&currency=USD&limit=8").json()
    assert len(result) == 1 and result[0]["sku"] == "PAGE-105"
    assert client.get("/products?q=%25").json() == []
    assert client.get("/products?is_active=false").json() == []
    assert client.get("/products?currency=ARS").json() == []
