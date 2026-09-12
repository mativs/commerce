import asyncio
from decimal import Decimal

from app.adapters.outbound.persistence.models import Product


def test_catalog_is_read_only(database_client):
    client, sessions = database_client
    assert client.get("/products").json() == []

    async def seed():
        async with sessions() as session, session.begin():
            # Catalog EANs are returned as stored, without checkout-time check digit rules.
            product = Product(
                name="Shirt",
                sku="SHIRT-M",
                price=Decimal("19.99"),
                currency="USD",
                ean="5901234123458",
            )
            session.add(product)
            await session.flush()
            return product.id

    product_id = asyncio.run(seed())
    url = f"/products/{product_id}"
    response = client.get(url)
    assert response.status_code == 200
    product = response.json()
    assert product["name"] == "Shirt"
    assert product["price"] == "19.99"
    assert product["ean"] == "5901234123458"
    assert client.get("/products").json() == [product]
    assert client.get("/products/2147483647").status_code == 404
    assert client.post("/products", json={}).status_code == 405
    assert client.put(url, json={"name": "Changed"}).status_code == 405
    assert client.delete(url).status_code == 405
    assert client.get(url).json() == product
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/products"]) == {"get"}
    assert set(paths["/products/{product_id}"]) == {"get"}
    assert "/products/{product_id}/logs" not in paths
