import asyncio

from sqlalchemy import text


def test_default_limit_and_product_search(database_client):
    client, sessions = database_client

    async def seed():
        async with sessions() as session, session.begin():
            await session.execute(
                text("""
                INSERT INTO products (name,sku,price,is_active)
                SELECT 'Product ' || n, 'PAGE-' || n, 1, true
                FROM generate_series(1, 105) n
            """)
            )

    asyncio.run(seed())
    assert len(client.get("/products").json()) == 50
    assert len(client.get("/products?limit=100").json()) == 100
    assert len(client.get("/products?limit=100&offset=100").json()) == 5
    result = client.get("/products?q=page-105&is_active=true&limit=8").json()
    assert len(result) == 1 and result[0]["sku"] == "PAGE-105"
    assert client.get("/products?q=%25").json() == []
    assert client.get("/products?is_active=false").json() == []
