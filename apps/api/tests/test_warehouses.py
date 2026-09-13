import asyncio

from app.adapters.outbound.persistence.models import Warehouse


def test_warehouses_are_read_only(warehouse_client):
    client, sessions = warehouse_client

    async def seed():
        async with sessions() as session, session.begin():
            warehouse = Warehouse(name="Main", latitude=-38, longitude=-57)
            session.add(warehouse)
            await session.flush()
            return warehouse.id

    warehouse_id = asyncio.run(seed())
    warehouse = client.get("/warehouses").json()
    assert len(warehouse) == 1 and warehouse[0]["id"] == warehouse_id
    assert client.get(f"/warehouses/{warehouse_id}").json() == warehouse[0]


def test_warehouse_inventory_filters_and_scope(warehouse_client):
    from decimal import Decimal

    from app.adapters.outbound.persistence.models import Product, Stock

    client, sessions = warehouse_client

    async def seed():
        async with sessions() as session, session.begin():
            warehouses = [Warehouse(name=n, latitude=-38, longitude=-57) for n in ["A", "B"]]
            products = [
                Product(name=n, sku=n.upper(), price=Decimal("1"))
                for n in ["Available", "Booked", "Empty", "Missing"]
            ]
            session.add_all(warehouses + products)
            await session.flush()
            session.add_all(
                [
                    Stock(
                        warehouse_id=warehouses[0].id,
                        product_id=products[0].id,
                        on_hand=8,
                        reserved=3,
                    ),
                    Stock(
                        warehouse_id=warehouses[0].id,
                        product_id=products[1].id,
                        on_hand=4,
                        reserved=4,
                    ),
                    Stock(warehouse_id=warehouses[0].id, product_id=products[2].id, on_hand=0),
                    Stock(warehouse_id=warehouses[1].id, product_id=products[3].id, on_hand=99),
                ]
            )
            return warehouses[0].id

    wid = asyncio.run(seed())
    url = f"/warehouses/{wid}/products"
    rows = client.get(url).json()
    assert [(r["on_hand"], r["booked"], r["available"]) for r in rows] == [
        (8, 3, 5),
        (4, 4, 0),
        (0, 0, 0),
        (0, 0, 0),
    ]
    assert [r["name"] for r in client.get(url + "?stock=available").json()] == ["Available"]
    assert [r["name"] for r in client.get(url + "?stock=on_hand").json()] == ["Available", "Booked"]
    assert client.get(url + "?stock=on_hand&limit=1&offset=1").json() == [rows[1]]
    assert client.get(url + "?stock=invalid").status_code == 422
    assert client.get("/warehouses/2147483647/products").status_code == 404
